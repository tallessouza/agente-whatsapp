"""Lead enrichment: who this WhatsApp lead is on Instagram, and what they post.

Identity resolution, in order of confidence:
  1. the @ in the prefilled WhatsApp text (untouched link)          -> confirmado
  2. the @ the lead typed when the agent asked                      -> confirmado/informado
  3. a time window over OpenReply DMs that carried the WhatsApp link,
     tie-broken by the WhatsApp display name                        -> confirmado/provavel
  4. nothing in the window                                          -> direto
Only a *confirmado* identity is used in the conversation; anything else makes
the agent ask for the @. Candidate handles are never shown to the agent.

Profile (bio + latest post captions): Meta Business Discovery (official,
professional accounts only) and, as a fallback, an Apify actor (any public
account). Both are optional and cached.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sqlite3
import time
import unicodedata
from contextlib import closing
from typing import Any, Callable

import httpx

LOGGER = logging.getLogger("sdr_brain.enrichment")
MATCH_WINDOW_SECONDS = int(os.getenv("SDR_MATCH_WINDOW_SECONDS", "1800"))
PROFILE_CACHE_SECONDS = int(os.getenv("SDR_PROFILE_CACHE_SECONDS", str(7 * 86400)))
GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v20.0")
APIFY_ACTOR = os.getenv("APIFY_PROFILE_ACTOR", "apify~instagram-profile-scraper")
POSTS_IN_PROFILE = 6
IGNORED_HANDLES = {"there", "username", ""}


def ensure_tables(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS ig_matches (conversation_id INTEGER PRIMARY KEY, username TEXT, status TEXT NOT NULL, method TEXT NOT NULL, candidates INTEGER NOT NULL DEFAULT 0, ts REAL NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS ig_company (conversation_id INTEGER PRIMARY KEY, username TEXT NOT NULL, ts REAL NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS ig_profiles (username TEXT PRIMARY KEY, data TEXT NOT NULL, source TEXT NOT NULL, ts REAL NOT NULL)")


def normalize_handle(value: str | None) -> str:
    handle = str(value or "").strip().lstrip("@").lower()
    handle = re.sub(r"[^a-z0-9._]", "", handle).strip(".")
    return "" if handle in IGNORED_HANDLES else handle


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def name_matches_handle(display_name: str, handle: str) -> bool:
    """True when a meaningful piece of the WhatsApp name appears in the @."""
    handle_letters = re.sub(r"[^a-z]", "", _fold(handle))
    tokens = [t for t in re.split(r"[^a-z]+", _fold(display_name)) if len(t) >= 3]
    return any(t in handle_letters for t in tokens)


# --- OpenReply (read-only) -------------------------------------------------------

def window_candidates(dsn: str, first_ts: float, exclude: set[str]) -> list[dict[str, Any]]:
    """Who plausibly opened WhatsApp just before the first message.

    Clicks on a per-recipient link (LinkClick.recipientId) come first: they are
    individual and closest in time. People who were only *sent* the link
    (DmLog) are the weaker fallback.
    """
    import psycopg
    with psycopg.connect(dsn) as conn, conn.cursor() as cursor:
        cursor.execute(
            'SELECT lower(c."recipientName"), c."recipientId", max(c."createdAt") AS clicked '
            'FROM "LinkClick" c WHERE c."recipientId" IS NOT NULL '
            'AND c."createdAt" BETWEEN to_timestamp(%s) AND to_timestamp(%s) '
            'GROUP BY 1, 2 ORDER BY clicked DESC LIMIT 50',
            (first_ts - MATCH_WINDOW_SECONDS, first_ts + 60),
        )
        clicks = cursor.fetchall()
        cursor.execute(
            'SELECT lower(d."commenterName"), d."commenterId", max(coalesce(d."dmSentAt", d."createdAt")) AS sent '
            'FROM "DmLog" d WHERE d.status = %s '
            'AND coalesce(d."dmSentAt", d."createdAt") BETWEEN to_timestamp(%s) AND to_timestamp(%s) '
            'GROUP BY 1, 2 ORDER BY sent DESC LIMIT 50',
            ("SENT", first_ts - MATCH_WINDOW_SECONDS, first_ts + 60),
        )
        rows = cursor.fetchall()
    people: dict[str, dict[str, Any]] = {}
    for source, found in (("clique", clicks), ("dm", rows)):
        for name, igsid, when in found:
            handle = normalize_handle(name)
            key = handle or f"igsid:{igsid}"
            if (handle and handle in exclude) or key in people:
                continue
            people[key] = {"handle": handle, "igsid": igsid, "source": source,
                           "sent": when.timestamp() if hasattr(when, "timestamp") else when}
    return list(people.values())


def openreply_history(dsn: str, handle: str) -> dict[str, Any]:
    import psycopg
    with psycopg.connect(dsn) as conn, conn.cursor() as cursor:
        cursor.execute(
            'SELECT d."commentText", d."createdAt", d."matchedKeyword", d."commentId", a."postUrl", a.name '
            'FROM "DmLog" d LEFT JOIN "Automation" a ON a.id = d."automationId" '
            'WHERE lower(ltrim(d."commenterName", \'@\')) = %s AND d."createdAt" > now() - interval \'30 days\' '
            'ORDER BY d."createdAt" DESC LIMIT 20',
            (handle,),
        )
        rows = cursor.fetchall()
    if not rows:
        return {}
    comments = [
        {"texto": text, "quando": str(when), "tipo": "dm" if str(cid).startswith("dm:") else ("botao" if str(cid).startswith("reveal:") else "comentario")}
        for text, when, _kw, cid, _url, _name in rows
    ]
    return {
        "campanha": rows[0][5],
        "post": rows[0][4],
        "palavra": rows[0][2],
        "interacoes": comments,
        "primeira_interacao": str(rows[-1][1]),
        "ultima_interacao": str(rows[0][1]),
    }


def resolve_identity(
    *,
    prefilled_handle: str,
    typed_handle: str,
    display_name: str,
    candidates: list[dict[str, Any]],
    in_campaign: Callable[[str], bool],
) -> dict[str, Any]:
    """Pure decision: returns {username, status, method, candidates}."""
    if prefilled_handle:
        return {"username": prefilled_handle, "status": "confirmado", "method": "texto_do_link", "candidates": len(candidates)}
    if typed_handle:
        status = "confirmado" if in_campaign(typed_handle) else "informado"
        return {"username": typed_handle, "status": status, "method": "lead_informou", "candidates": len(candidates)}
    clicked = [c for c in candidates if c.get("source") == "clique"]
    if clicked:
        # Someone opened the per-recipient link: only clickers are in the running.
        if len(clicked) == 1 and clicked[0]["handle"]:
            return {"username": clicked[0]["handle"], "status": "confirmado", "method": "clique", "candidates": len(candidates)}
        named_clicks = [c for c in clicked if c["handle"] and display_name and name_matches_handle(display_name, c["handle"])]
        if len(named_clicks) == 1:
            return {"username": named_clicks[0]["handle"], "status": "confirmado", "method": "clique+nome", "candidates": len(candidates)}
        return {"username": None, "status": "ambiguo", "method": "clique", "candidates": len(candidates)}
    named = [c for c in candidates if c["handle"] and display_name and name_matches_handle(display_name, c["handle"])]
    if len(named) == 1:
        return {"username": named[0]["handle"], "status": "confirmado", "method": "janela+nome", "candidates": len(candidates)}
    if len(candidates) == 1 and candidates[0]["handle"]:
        return {"username": candidates[0]["handle"], "status": "provavel", "method": "janela", "candidates": 1}
    if candidates:
        return {"username": None, "status": "ambiguo", "method": "janela", "candidates": len(candidates)}
    return {"username": None, "status": "direto", "method": "janela", "candidates": 0}


# --- profile lookup ---------------------------------------------------------------

async def business_discovery(username: str) -> dict[str, Any] | None:
    """Official Meta API. Needs a Facebook-Login token; target must be professional."""
    token = os.getenv("META_GRAPH_TOKEN")
    business_id = os.getenv("IG_BUSINESS_ID")
    if not token or not business_id or not username:
        return None
    fields = (f"business_discovery.username({username})"
              f"{{username,name,biography,website,followers_count,media_count,"
              f"media.limit({POSTS_IN_PROFILE}){{caption,timestamp,media_type,permalink,like_count,comments_count}}}}")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"https://graph.facebook.com/{GRAPH_VERSION}/{business_id}", params={"fields": fields, "access_token": token})
            response.raise_for_status()
            data = response.json().get("business_discovery") or {}
    except Exception as exc:
        LOGGER.warning("Business Discovery failed for %s: %s", username, exc)
        return None
    posts = [{"legenda": (m.get("caption") or "")[:300], "quando": m.get("timestamp"), "tipo": m.get("media_type"),
              "link": m.get("permalink"), "curtidas": m.get("like_count"), "comentarios": m.get("comments_count")}
             for m in (data.get("media") or {}).get("data", [])]
    return {"nome": data.get("name"), "bio": data.get("biography"), "site": data.get("website"),
            "seguidores": data.get("followers_count"), "posts_total": data.get("media_count"), "ultimos_posts": posts}


async def apify_profile(username: str) -> dict[str, Any] | None:
    """Fallback for any public account. Paid per result; disabled without APIFY_TOKEN."""
    token = os.getenv("APIFY_TOKEN")
    if not token or not username:
        return None
    url = f"https://api.apify.com/v2/acts/{APIFY_ACTOR}/run-sync-get-dataset-items"
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(url, params={"token": token}, json={"usernames": [username]})
            response.raise_for_status()
            items = response.json()
    except Exception as exc:
        LOGGER.warning("Apify profile failed for %s: %s", username, exc)
        return None
    item = next((i for i in items if isinstance(i, dict) and normalize_handle(i.get("username")) == username), None) if isinstance(items, list) else None
    if not item:
        return None
    posts = [{"legenda": (p.get("caption") or "")[:300], "quando": p.get("timestamp"), "tipo": p.get("type"),
              "link": p.get("url"), "curtidas": p.get("likesCount"), "comentarios": p.get("commentsCount")}
             for p in (item.get("latestPosts") or [])[:POSTS_IN_PROFILE]]
    return {"nome": item.get("fullName"), "bio": item.get("biography"), "site": item.get("externalUrl"),
            "seguidores": item.get("followersCount"), "posts_total": item.get("postsCount"),
            "privado": item.get("private"), "ultimos_posts": posts}


async def profile_lookup(conn_factory: Callable[[], sqlite3.Connection], username: str) -> dict[str, Any] | None:
    with closing(conn_factory()) as conn:
        row = conn.execute("SELECT data, ts FROM ig_profiles WHERE username=?", (username,)).fetchone()
    if row and time.time() - row[1] < PROFILE_CACHE_SECONDS:
        return json.loads(row[0])
    for source, fetch in (("meta", business_discovery), ("apify", apify_profile)):
        data = await fetch(username)
        if data:
            with closing(conn_factory()) as conn:
                conn.execute("INSERT OR REPLACE INTO ig_profiles VALUES (?,?,?,?)", (username, json.dumps(data, ensure_ascii=False), source, time.time()))
                conn.commit()
            LOGGER.warning("Profile for @%s from %s", username, source)
            return data
    return None


async def enrich(
    payload: dict[str, Any],
    *,
    conn_factory: Callable[[], sqlite3.Connection],
    display_name: str,
    post_profile: Callable[[int, dict[str, Any]], Any],
    on_result: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    """Resolve identity, gather OpenReply history and profile, post the ficha."""
    conversation_id = int(payload["conversation_id"])
    origin = payload.get("origin") or {}
    dsn = os.getenv("OPENREPLY_DSN", "")
    prefilled = normalize_handle(origin.get("instagram"))
    typed = normalize_handle(payload.get("typed_instagram"))
    first_ts = float(payload.get("ts") or time.time())

    with closing(conn_factory()) as conn:
        taken = {r[0] for r in conn.execute("SELECT username FROM ig_matches WHERE username IS NOT NULL AND conversation_id != ?", (conversation_id,))}
        previous = conn.execute("SELECT username, status, method FROM ig_matches WHERE conversation_id=?", (conversation_id,)).fetchone()

    company = normalize_handle(payload.get("company_instagram"))
    if company:
        with closing(conn_factory()) as conn:
            conn.execute("INSERT OR REPLACE INTO ig_company VALUES (?,?,?)", (conversation_id, company, time.time()))
            conn.commit()
    else:
        with closing(conn_factory()) as conn:
            row = conn.execute("SELECT username FROM ig_company WHERE conversation_id=?", (conversation_id,)).fetchone()
        company = row[0] if row else ""

    candidates: list[dict[str, Any]] = []
    reuse_previous = previous is not None and not prefilled and not typed
    if dsn and not prefilled and not typed and not reuse_previous:
        try:
            candidates = await asyncio.to_thread(window_candidates, dsn, first_ts, taken)
        except Exception:
            LOGGER.exception("OpenReply window lookup failed")

    history_cache: dict[str, dict[str, Any]] = {}

    def history(handle: str) -> dict[str, Any]:
        if handle not in history_cache:
            try:
                history_cache[handle] = openreply_history(dsn, handle) if dsn else {}
            except Exception:
                LOGGER.exception("OpenReply history failed for %s", handle)
                history_cache[handle] = {}
        return history_cache[handle]

    if typed:
        await asyncio.to_thread(history, typed)
    if reuse_previous:
        # Re-run (e.g. the company @ arrived later): keep the identity decided
        # at the first message instead of recomputing a window at a later time.
        identity = {"username": previous[0], "status": previous[1], "method": previous[2], "candidates": 0}
    else:
        identity = resolve_identity(prefilled_handle=prefilled, typed_handle=typed, display_name=display_name,
                                    candidates=candidates, in_campaign=lambda h: bool(history_cache.get(h)))
    # A lead-typed or link @ always wins over an earlier weaker guess; never downgrade a confirmation.
    if previous and previous[1] == "confirmado" and identity["status"] != "confirmado":
        identity = {"username": previous[0], "status": "confirmado", "method": previous[2], "candidates": identity["candidates"]}
    with closing(conn_factory()) as conn:
        conn.execute("INSERT OR REPLACE INTO ig_matches VALUES (?,?,?,?,?,?)",
                     (conversation_id, identity["username"], identity["status"], identity["method"], identity["candidates"], time.time()))
        conn.commit()
    LOGGER.warning("IG identity conversation=%s status=%s method=%s candidates=%s", conversation_id, identity["status"], identity["method"], identity["candidates"])

    ficha: dict[str, Any] = {"origem_instagram": {"status": identity["status"], "metodo": identity["method"]}}
    username = identity["username"] if identity["status"] in {"confirmado", "informado"} else None
    found: dict[str, Any] = {}
    perfil = perfil_empresa = None
    if username:
        ficha["instagram"] = f"@{username}"
        found = await asyncio.to_thread(history, username)
        if found:
            ficha["campanha_instagram"] = found
        perfil = await profile_lookup(conn_factory, username)
        if perfil:
            ficha["perfil"] = for_agent(perfil)
    if company and company != username:
        ficha["instagram_empresa"] = f"@{company}"
        perfil_empresa = await profile_lookup(conn_factory, company)
        if perfil_empresa:
            ficha["perfil_empresa"] = for_agent(perfil_empresa)
    await post_profile(conversation_id, ficha)
    if on_result:
        await on_result({"identity": identity, "username": username, "perfil": perfil, "company": company if company != username else "",
                         "perfil_empresa": perfil_empresa, "campanha": found})
    return ficha


def for_agent(perfil: dict[str, Any]) -> dict[str, Any]:
    """The agent needs themes for rapport, not engagement numbers or links."""
    posts = [{k: v for k, v in post.items() if k not in {"link", "curtidas", "comentarios"}} for post in perfil.get("ultimos_posts") or []]
    return {**perfil, "ultimos_posts": posts}
