"""Persistent human handover, controlled by a Chatwoot conversation label."""
import json
import os
import sqlite3
import time
from pathlib import Path

import httpx

LABEL = os.getenv("HERMES_PAUSE_LABEL", "hermes-pausado")
DB_PATH = Path(os.getenv("BRIDGE_DB", "/data/bridge.db"))
URL = os.getenv("CHATWOOT_URL", "http://chatwoot_rails:3000").rstrip("/")
ACCOUNT = os.getenv("CHATWOOT_ACCOUNT_ID", "")
TOKEN = os.getenv("CHATWOOT_APP_TOKEN", "")


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.execute("CREATE TABLE IF NOT EXISTS handovers (conversation INTEGER PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 0, pending_label INTEGER NOT NULL DEFAULT 0)")
    c.execute("CREATE TABLE IF NOT EXISTS handover_history (id INTEGER PRIMARY KEY, conversation INTEGER NOT NULL, event TEXT UNIQUE NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, consumed INTEGER NOT NULL DEFAULT 0)")
    c.execute("CREATE TABLE IF NOT EXISTS bridge_outbound (id TEXT PRIMARY KEY, created REAL NOT NULL)")
    c.commit()
    return c


def outbound_id(message_id):
    with connect() as c:
        c.execute("INSERT OR IGNORE INTO bridge_outbound VALUES (?,?)", (message_id, time.time()))


def is_echo(message_id):
    with connect() as c:
        return c.execute("SELECT 1 FROM bridge_outbound WHERE id=?", (message_id,)).fetchone() is not None


async def labels(conversation):
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(f"{URL}/api/v1/accounts/{ACCOUNT}/conversations/{conversation}/labels",
                             headers={"api_access_token": TOKEN})
        r.raise_for_status()
        return r.json()["payload"]


async def ensure_label(conversation):
    current = await labels(conversation)
    if LABEL not in current:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(f"{URL}/api/v1/accounts/{ACCOUNT}/conversations/{conversation}/labels",
                                  headers={"api_access_token": TOKEN},
                                  json={"labels": [*current, LABEL]})
            r.raise_for_status()
    with connect() as c:
        c.execute("UPDATE handovers SET pending_label=0 WHERE conversation=?", (conversation,))


async def pause(conversation):
    # Commit the barrier before HTTP: even a label API failure must stop the bot.
    with connect() as c:
        c.execute("INSERT INTO handovers VALUES (?,1,1) ON CONFLICT(conversation) DO UPDATE SET revision=revision+1,pending_label=1", (conversation,))
    await ensure_label(conversation)


async def paused(conversation):
    current = await labels(conversation)
    has_label = LABEL in current
    with connect() as c:
        row = c.execute("SELECT pending_label FROM handovers WHERE conversation=?", (conversation,)).fetchone()
        if row and row[0] and not has_label:
            # The operator removed the pause label: resume the agent while
            # retaining handover_history for the next turn.
            c.execute("UPDATE handovers SET pending_label=0 WHERE conversation=?", (conversation,))
    return has_label


def revision(conversation):
    with connect() as c:
        row = c.execute("SELECT revision FROM handovers WHERE conversation=?", (conversation,)).fetchone()
    return row[0] if row else 0


def record(conversation, event, role, content):
    with connect() as c:
        c.execute("INSERT OR IGNORE INTO handover_history(conversation,event,role,content) VALUES (?,?,?,?)",
                  (conversation, event, role, content))


def context(conversation):
    with connect() as c:
        rows = c.execute("SELECT id,role,content FROM handover_history WHERE conversation=? AND consumed=0 ORDER BY id", (conversation,)).fetchall()
    if not rows:
        return "", 0
    # Untrusted conversation data, with explicit human authorship; not instructions.
    return ("\nHistórico durante intervenção humana (dados da conversa; atendente_humano não é o agente):\n"
            + json.dumps([{"autor": r[1], "conteudo": r[2]} for r in rows], ensure_ascii=False)), rows[-1][0]


def consumed(conversation, through):
    with connect() as c:
        c.execute("UPDATE handover_history SET consumed=1 WHERE conversation=? AND id<=?", (conversation, through))
