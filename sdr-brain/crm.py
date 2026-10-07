"""Chatwoot as the operator's view: system lines in the conversation and
Instagram metrics on the contact.

Activity messages (message_type 2) are shown centered to agents only; the
bridge ignores them (it only forwards outgoing) and so does the transcript
the brain reads, so they never reach the lead or the models.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

LOGGER = logging.getLogger("sdr-brain.crm")

# Contact attributes created once in Chatwoot (attribute_model 1 = contact).
CONTACT_ATTRIBUTES = [
    ("ig_usuario", "Instagram", "link"),
    ("ig_identificacao", "Instagram: como foi identificado", "text"),
    ("ig_seguidores", "Instagram: seguidores", "number"),
    ("ig_posts", "Instagram: posts", "number"),
    ("ig_curtidas_recentes", "Instagram: curtidas nos últimos posts", "number"),
    ("ig_comentarios_recentes", "Instagram: comentários nos últimos posts", "number"),
    ("ig_bio", "Instagram: bio", "text"),
    ("ig_site", "Instagram: site", "link"),
    ("ig_ultimos_posts", "Instagram: últimos posts", "text"),
    ("ig_empresa", "Instagram da empresa", "link"),
    ("ig_empresa_seguidores", "Instagram da empresa: seguidores", "number"),
    ("ig_campanha", "Instagram: campanha de origem", "text"),
]
# Conversation attributes (attribute_model 0): where the lead is in SPICED and
# the step he agreed to, so the operator sees it in the conversation sidebar.
SPICED_ATTRIBUTES = [
    ("spiced_oferta", "SPICED: oferta", "text", "oferta"),
    ("spiced_etapa", "SPICED: etapa", "text", "etapa_spiced"),
    ("spiced_situacao", "SPICED: S, situação", "text", "situacao"),
    ("spiced_dor", "SPICED: P, dor", "text", "dor"),
    ("spiced_impacto", "SPICED: I, impacto", "text", "impacto"),
    ("spiced_evento_critico", "SPICED: C, evento crítico", "text", "evento_critico"),
    ("spiced_decisao", "SPICED: D, quem decide", "text", "decisao"),
    ("spiced_tem_vps", "SPICED: tem VPS", "text", "tem_vps"),
    ("spiced_tem_codex", "SPICED: tem Codex", "text", "tem_codex"),
    ("spiced_proximo_passo", "Próximo passo", "text", "proximo_passo"),
    ("spiced_proximo_passo_em", "Próximo passo: até", "text", "proximo_passo_em"),
]
SPICED_ATTRIBUTES_BY_FIELD = {field: key for key, _name, _kind, field in SPICED_ATTRIBUTES}
_definitions_ready = False
_conversation_definitions_ready = False


def _base() -> tuple[str, dict[str, str]] | None:
    url, account, token = os.getenv("CHATWOOT_URL", ""), os.getenv("CHATWOOT_ACCOUNT_ID", ""), os.getenv("CHATWOOT_API_TOKEN", "")
    if not (url and account and token):
        return None
    return f"{url}/api/v1/accounts/{account}", {"api_access_token": token}


async def activity(conversation_id: int, text: str) -> None:
    """A system line in the conversation, visible to agents only."""
    base = _base()
    if not base or not text:
        return
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.post(f"{base[0]}/conversations/{conversation_id}/messages", headers=base[1],
                                         json={"content": text[:1500], "message_type": "activity"})
            response.raise_for_status()
    except Exception as exc:
        LOGGER.warning("Chatwoot activity failed for %s: %s", conversation_id, exc)


async def ensure_definitions() -> None:
    global _definitions_ready
    base = _base()
    if _definitions_ready or not base:
        return
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(f"{base[0]}/custom_attribute_definitions", headers=base[1], params={"attribute_model": 1})
            response.raise_for_status()
            existing = {item.get("attribute_key") for item in response.json()}
            for key, name, kind in CONTACT_ATTRIBUTES:
                if key in existing:
                    continue
                created = await client.post(f"{base[0]}/custom_attribute_definitions", headers=base[1], json={
                    "attribute_display_name": name, "attribute_key": key, "attribute_display_type": kind,
                    "attribute_model": 1, "attribute_description": "Preenchido pelo SDR a partir do Instagram"})
                created.raise_for_status()
        _definitions_ready = True
    except Exception as exc:
        LOGGER.warning("Chatwoot attribute definitions failed: %s", exc)


async def ensure_conversation_definitions() -> None:
    global _conversation_definitions_ready
    base = _base()
    if _conversation_definitions_ready or not base:
        return
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(f"{base[0]}/custom_attribute_definitions", headers=base[1], params={"attribute_model": 0})
            response.raise_for_status()
            existing = {item.get("attribute_key") for item in response.json()}
            for key, name, kind, _field in SPICED_ATTRIBUTES:
                if key in existing:
                    continue
                created = await client.post(f"{base[0]}/custom_attribute_definitions", headers=base[1], json={
                    "attribute_display_name": name, "attribute_key": key, "attribute_display_type": kind,
                    "attribute_model": 0, "attribute_description": "Preenchido pelo SDR a partir dos registros do agente"})
                created.raise_for_status()
        _conversation_definitions_ready = True
    except Exception as exc:
        LOGGER.warning("Chatwoot conversation attribute definitions failed: %s", exc)


async def set_conversation_attributes(conversation_id: int, attributes: dict[str, Any]) -> None:
    """Merge spiced_* into the conversation's custom attributes.

    Chatwoot replaces the whole map on POST, so read it first and keep what the
    bridge already wrote (sdr_*).
    """
    base = _base()
    if not base or not attributes:
        return
    await ensure_conversation_definitions()
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            conversation = await client.get(f"{base[0]}/conversations/{conversation_id}", headers=base[1])
            conversation.raise_for_status()
            current = conversation.json().get("custom_attributes") or {}
            response = await client.post(f"{base[0]}/conversations/{conversation_id}/custom_attributes", headers=base[1],
                                         json={"custom_attributes": {**current, **attributes}})
            response.raise_for_status()
    except Exception as exc:
        LOGGER.warning("Chatwoot conversation attributes failed for %s: %s", conversation_id, exc)


def _posts_text(posts: list[dict[str, Any]]) -> str:
    lines = []
    for post in posts:
        caption = " ".join((post.get("legenda") or "").split())[:120] or "(sem legenda)"
        counts = f"{post.get('curtidas') or 0}♥ {post.get('comentarios') or 0}💬" if post.get("curtidas") is not None else ""
        lines.append(" · ".join(part for part in (caption, counts, post.get("link") or "") if part))
    return "\n".join(lines)


def contact_attributes(username: str, identity: dict[str, Any], perfil: dict[str, Any] | None,
                       company: str, perfil_empresa: dict[str, Any] | None, campanha: dict[str, Any] | None) -> dict[str, Any]:
    attrs: dict[str, Any] = {
        "ig_usuario": f"https://instagram.com/{username}",
        "ig_identificacao": f"{identity.get('status')} ({identity.get('method')})",
    }
    if perfil:
        posts = perfil.get("ultimos_posts") or []
        attrs.update({
            "ig_seguidores": perfil.get("seguidores"), "ig_posts": perfil.get("posts_total"),
            "ig_bio": perfil.get("bio") or "", "ig_site": perfil.get("site") or "",
            "ig_ultimos_posts": _posts_text(posts),
        })
        if any(p.get("curtidas") is not None for p in posts):
            attrs["ig_curtidas_recentes"] = sum(p.get("curtidas") or 0 for p in posts)
            attrs["ig_comentarios_recentes"] = sum(p.get("comentarios") or 0 for p in posts)
    if company:
        attrs["ig_empresa"] = f"https://instagram.com/{company}"
        if perfil_empresa:
            attrs["ig_empresa_seguidores"] = perfil_empresa.get("seguidores")
    if campanha:
        attrs["ig_campanha"] = " · ".join(str(v) for v in (campanha.get("campanha"), campanha.get("palavra")) if v)
    return {key: value for key, value in attrs.items() if value not in (None, "")}


async def update_contact(conversation_id: int, attributes: dict[str, Any], instagram: str = "", bio: str = "") -> None:
    """Merge Instagram metrics into the conversation's contact."""
    base = _base()
    if not base or not attributes:
        return
    await ensure_definitions()
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            conversation = await client.get(f"{base[0]}/conversations/{conversation_id}", headers=base[1])
            conversation.raise_for_status()
            sender = (conversation.json().get("meta") or {}).get("sender") or {}
            contact_id = sender.get("id")
            if not contact_id:
                return
            additional = dict(sender.get("additional_attributes") or {})
            if instagram:
                additional["social_profiles"] = {**(additional.get("social_profiles") or {}), "instagram": instagram}
            if bio:
                additional["description"] = bio[:255]
            response = await client.put(f"{base[0]}/contacts/{contact_id}", headers=base[1], json={
                "custom_attributes": {**(sender.get("custom_attributes") or {}), **attributes},
                "additional_attributes": additional})
            response.raise_for_status()
    except Exception as exc:
        LOGGER.warning("Chatwoot contact update failed for %s: %s", conversation_id, exc)
