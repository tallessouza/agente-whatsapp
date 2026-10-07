"""Replay Evolution fixtures against the FastAPI app with all integrations stubbed."""

import asyncio
import json
import os
from pathlib import Path

import httpx

import app as bridge


fixture_dir = Path(os.getenv("FIXTURES_DIR", "/fixtures/fixtures"))
calls: list[tuple[str, object]] = []


async def fake_ensure(jid: str, name: str):
    calls.append(("ensure_conversation", jid))
    return "fixture-source", 99


async def fake_add(source: str, conversation: int, content: str, private=False, outgoing=False, media=None, suppress_evolution=False):
    calls.append(("chatwoot_message", {"content": content, "outgoing": outgoing}))
    return {"id": 100}


async def fake_hermes(content: str, session: str, media=None):
    calls.append(("hermes", content))
    return "resposta fixture"


async def fake_send(number: str, content: str, reply_to=None, retry=False):
    calls.append(("evolution_send", {"number": number, "content": content}))


bridge.ensure_conversation = fake_ensure
bridge.add_chatwoot_message = fake_add
bridge.ask_hermes = fake_hermes
bridge.send_evolution = fake_send


async def main() -> None:
    transport = httpx.ASGITransport(app=bridge.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://fixture") as client:
        for path in sorted(fixture_dir.glob("*.json")):
            payload = json.loads(path.read_text())
            response = await client.post("/evolution/webhook", json=payload)
            print(path.name, response.status_code, response.json())
    print("calls:", json.dumps(calls, ensure_ascii=False))


asyncio.run(main())
