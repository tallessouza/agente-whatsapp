import asyncio, json, tempfile, time, unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
from zoneinfo import ZoneInfo
from datetime import datetime

from fastapi.testclient import TestClient
import app, sdr, handover


class PhaseB(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.db = Path(self.tmp.name) / "b.db"
        self.ps = [patch.object(app, "DB_PATH", self.db), patch.object(sdr, "DB_PATH", self.db), patch.object(handover, "DB_PATH", self.db)]
        for p in self.ps: p.start()
        app.hermes_pending.clear(); app.hermes_tasks.clear()
        self.oldtoken, self.oldurl = app.SDR_BRAIN_TOKEN, app.SDR_BRAIN_URL
        app.SDR_BRAIN_TOKEN = "tok"; app.SDR_BRAIN_URL = "http://brain"

    def tearDown(self):
        app.SDR_BRAIN_TOKEN, app.SDR_BRAIN_URL = self.oldtoken, self.oldurl
        for p in self.ps: p.stop()
        self.tmp.cleanup()

    def test_endpoint_auth_all_routes(self):
        routes = [
            ("post", "/sdr/guidance", {"conversation_id": 1, "text": "x"}),
            ("post", "/sdr/escalate", {"conversation_id": 1}),
            ("post", "/sdr/lead-profile", {"conversation_id": 1, "profile": {}}),
            ("post", "/sdr/followups", {"conversation_id": 1, "send_at": 0, "text": "x"}),
            ("delete", "/sdr/followups/1", None), ("get", "/sdr/conversations/1", None)]
        with TestClient(app.app) as c:
            for method, path, body in routes:
                fn = getattr(c, method)
                kwargs = {"json": body} if body is not None else {}
                app.SDR_BRAIN_TOKEN = ""
                self.assertEqual(fn(path, **kwargs).status_code, 503, path)
                app.SDR_BRAIN_TOKEN = "tok"
                self.assertEqual(fn(path, headers={"Authorization": "Bearer wrong"}, **kwargs).status_code, 401, path)

    async def test_guidance_profile_context_and_consumption(self):
        with TestClient(app.app) as c:
            h = {"Authorization": "Bearer tok"}
            self.assertEqual(c.post("/sdr/guidance", json={"conversation_id": 3, "text": "ligar agora"}, headers=h).status_code, 200)
            self.assertEqual(c.post("/sdr/lead-profile", json={"conversation_id": 3, "profile": {"nome": "Ana"}}, headers=h).status_code, 200)
        p = json.loads(sdr.trusted_context(3, sdr.pending_guidance(3)).split("\n", 1)[1].split("\n", 1)[0])
        self.assertEqual(p["orientacoes"], ["ligar agora"]); self.assertEqual(p["lead"]["ficha"]["nome"], "Ana")
        # Guidance is consumed by the turn worker once a reply was delivered.
        app.hermes_pending["5511@s.whatsapp.net"] = [("oi", None, "src", 3, "msg-1", None)]
        ask = AsyncMock(return_value="Faz sentido?")
        with patch.object(app, "HERMES_MESSAGE_DEBOUNCE_SECONDS", 0), patch.object(handover, "paused", AsyncMock(return_value=False)), \
                patch.object(app, "ask_hermes", ask), patch.object(app, "send_evolution", AsyncMock()), patch.object(app, "add_chatwoot_message", AsyncMock()), \
                patch.object(app, "send_presence", AsyncMock()), patch.object(sdr, "typing_seconds", return_value=0), patch.object(app, "brain_event", AsyncMock()), \
                patch.object(app, "review_reply", AsyncMock(side_effect=lambda jid, conv, last, parts, directives: (parts, directives))):
            await app.hermes_batch_worker("5511@s.whatsapp.net")
        self.assertIn("ligar agora", ask.await_args.args[4])
        self.assertEqual(sdr.pending_guidance(3), [])

    async def test_review_decisions_and_failures(self):
        async def review(data):
            class R:
                def json(self): return data
            m = AsyncMock(); m.__aenter__.return_value.post = AsyncMock(return_value=R()); return m
        for decision, payload, expected in [("aprovar", {"decision":"aprovar"}, ["draft"]), ("reescrever", {"decision":"reescrever","parts":["novo [[REGISTRO: dor = x]]"]}, ["novo"]), ("bloquear", {"decision":"bloquear","motivo":"ruim"}, [sdr.FALLBACK_REPLY])]:
            mgr = await review(payload)
            with patch.object(app.httpx, "AsyncClient", return_value=mgr):
                parts, directives = await app.review_reply("j", 1, "lead", ["draft"], [{"type":"registro","campo":"a","valor":"b"}])
            self.assertEqual(parts, expected)
            if decision == "reescrever": self.assertEqual(directives[0]["type"], "registro")
            if decision == "bloquear": self.assertEqual(directives[0]["type"], "escalar")
        mgr = Mock(); mgr.__aenter__ = AsyncMock(side_effect=TimeoutError())
        with patch.object(app.httpx, "AsyncClient", return_value=mgr): self.assertEqual((await app.review_reply("j",1,"x",["draft"],[]))[0], ["draft"])
        mgr = await review({"decision":"reescrever","parts":["Hermes"]})
        with patch.object(app.httpx, "AsyncClient", return_value=mgr), patch.object(app, "send_evolution", AsyncMock()) as send, patch.object(app, "add_chatwoot_message", AsyncMock()), patch.object(app, "send_presence", AsyncMock()), patch.object(sdr, "typing_seconds", return_value=0):
            await app.deliver_agent_reply("5511@s.whatsapp.net", "s", 1, "draft", None, "x")
        self.assertEqual(send.await_args.args[1], sdr.FALLBACK_REPLY)

    async def test_events_are_swallowed_and_disabled(self):
        with patch.object(app, "brain_event", AsyncMock(side_effect=RuntimeError("no"))), patch.object(app, "send_evolution", AsyncMock()), patch.object(app, "add_chatwoot_message", AsyncMock()), patch.object(app, "send_presence", AsyncMock()), patch.object(sdr, "typing_seconds", return_value=0):
            await app.deliver_agent_reply("5511@s.whatsapp.net", "s", 1, "ok [[REGISTRO: dor = x]]", None, "lead")
        with patch.object(app, "httpx") as hx:
            app.SDR_BRAIN_URL = ""
            await app.brain_event("/events/exchange", {})
            hx.AsyncClient.assert_not_called()

    async def test_queue_cancels_followups(self):
        sdr.add_followup(8, time.time()+100, "x")
        app.queue_hermes_turn("5511@s.whatsapp.net", "oi", None, "s", 8, "m")
        self.assertEqual(sdr.pending_followups(8), [])

    async def test_conversation_endpoint(self):
        with app.db() as c: c.execute("INSERT INTO contacts VALUES (?,?,?,?)", ("5511@s.whatsapp.net","src",9,9))
        sdr.touch_activity(9, lead=True); sdr.touch_activity(9, agent=True); sdr.add_followup(9, time.time()+10, "retoma")
        with patch.object(handover, "paused", AsyncMock(return_value=False)), TestClient(app.app) as c:
            r=c.get("/sdr/conversations/9",headers={"Authorization":"Bearer tok"}); self.assertEqual(r.status_code,200)
            self.assertEqual(r.json()["jid"],"5511@s.whatsapp.net"); self.assertEqual(r.json()["source_id"],"src"); self.assertTrue(r.json()["followups"])
            self.assertEqual(c.get("/sdr/conversations/99",headers={"Authorization":"Bearer tok"}).status_code,404)


class OwnerTestMode(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db = Path(self.tmp.name) / "o.db"
        self.patches = [patch.object(app, "DB_PATH", db), patch.object(sdr, "DB_PATH", db), patch.object(handover, "DB_PATH", db),
                        patch.object(sdr, "OWNER_IDS", {"556499425822", "148563086540988"}), patch.object(sdr, "NOTIFY_NUMBER", "556499425822")]
        for p in self.patches:
            p.start()
        self.send = AsyncMock()
        p = patch.object(app, "send_evolution", self.send); p.start(); self.patches.append(p)
        conn = app.db(); conn.execute("INSERT INTO contacts VALUES ('556499425822@s.whatsapp.net','src',7,NULL)"); conn.commit(); conn.close()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    async def test_start_and_stop(self):
        jid = "556499425822@s.whatsapp.net"
        self.assertEqual(sdr.session_suffix(jid), "")
        fid = sdr.add_followup(7, 0, "x?", "", 0, "5min")
        await app.owner_test_command(jid, "#teste")
        self.assertEqual(sdr.owner_test_run(jid), 1)
        self.assertEqual(sdr.session_suffix(jid), ":teste1")
        conn = app.db(); self.assertIsNone(conn.execute("SELECT 1 FROM contacts WHERE jid=?", (jid,)).fetchone()); conn.close()
        with sdr.connect() as c:
            self.assertEqual(c.execute("SELECT status FROM sdr_followups WHERE id=?", (fid,)).fetchone()[0], "cancelled")
        self.assertEqual(self.send.await_args.args[0], "556499425822")
        self.assertIn("Modo teste 1 ligado", self.send.await_args.args[1])
        await app.owner_test_command(jid, "#teste")
        self.assertEqual(sdr.session_suffix(jid), ":teste2")
        await app.owner_test_command(jid, "#fim")
        self.assertIsNone(sdr.owner_test_run(jid))
        self.assertEqual(sdr.session_suffix(jid), "")
        self.assertIn("desligado", self.send.await_args.args[1])

    def test_non_owner_never_gets_suffix(self):
        self.assertEqual(sdr.session_suffix("5511@s.whatsapp.net"), "")


class Interruption(unittest.IsolatedAsyncioTestCase):
    """A lead message during generation or sending must not get a stale answer."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db = Path(self.tmp.name) / "i.db"
        self.patches = [patch.object(app, "DB_PATH", db), patch.object(sdr, "DB_PATH", db), patch.object(handover, "DB_PATH", db),
                        patch.object(sdr, "typing_seconds", return_value=0), patch.object(app, "send_presence", AsyncMock()),
                        patch.object(app, "add_chatwoot_message", AsyncMock()), patch.object(app, "brain_event", AsyncMock()),
                        patch.object(app, "review_reply", AsyncMock(side_effect=lambda jid, conv, last, parts, directives: (parts, directives)))]
        for p in self.patches:
            p.start()
        app.hermes_pending.clear(); app.hermes_tasks.clear()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        app.hermes_pending.clear(); app.hermes_tasks.clear()
        self.tmp.cleanup()

    async def test_reply_generated_during_new_message_is_discarded_and_regenerated(self):
        jid = "5511@s.whatsapp.net"
        app.hermes_pending[jid] = [("quanto custa?", None, "src", 3, "m1", None)]
        replies = []

        async def ask(prompt, session, media, events, ctx):
            replies.append(prompt)
            if len(replies) == 1:  # the lead writes again while the 1st answer is generated
                app.hermes_pending[jid].append(("e como funciona?", None, "src", 3, "m2", None))
                return "Resposta sobre o preço."
            return "Resposta que cobre as duas perguntas."

        send = AsyncMock()
        with patch.object(app, "HERMES_MESSAGE_DEBOUNCE_SECONDS", 0), patch.object(handover, "paused", AsyncMock(return_value=False)), \
                patch.object(app, "ask_hermes", AsyncMock(side_effect=ask)), patch.object(app, "send_evolution", send):
            await app.hermes_batch_worker(jid)
        self.assertEqual([c.args[1] for c in send.await_args_list], ["Resposta que cobre as duas perguntas."])
        self.assertIn("quanto custa?", replies[1])
        self.assertIn("e como funciona?", replies[1])
        corrections = sdr.recent_corrections(3)
        self.assertEqual(corrections[0], {"voce_escreveu": "Resposta sobre o preço.", "o_lead_recebeu": ""})

    async def test_interruption_between_bubbles_stops_the_rest(self):
        jid = "5511@s.whatsapp.net"
        sent = []

        async def send(number, text, reply_to=None):
            sent.append(text)
            app.hermes_pending[jid] = [("espera", None, "src", 3, "m3", None)]

        with patch.object(app, "send_evolution", AsyncMock(side_effect=send)):
            delivered = await app.deliver_agent_reply(jid, "src", 3, "Primeira.[[QUEBRA]]Segunda.[[QUEBRA]]Terceira.", None, "oi")
        self.assertTrue(delivered)
        self.assertEqual(sent, ["Primeira."])
        self.assertEqual(sdr.recent_corrections(3)[-1]["o_lead_recebeu"], "Primeira.")


class Escalation(unittest.IsolatedAsyncioTestCase):
    async def test_escalation_is_idempotent_when_already_paused(self):
        note = AsyncMock(); pause = AsyncMock()
        with patch.object(handover, "paused", AsyncMock(side_effect=[False, True])), patch.object(sdr, "private_note", note), \
                patch.object(sdr, "add_label", AsyncMock()), patch.object(handover, "pause", pause), patch.object(sdr, "NOTIFY_NUMBER", ""):
            directive = {"type": "escalar", "motivo": "capacidade incerta", "frase": "x"}
            await app.escalate("5511@s.whatsapp.net", "src", 7, directive, "x")
            await app.escalate("5511@s.whatsapp.net", "src", 7, directive, "x")
        self.assertEqual(note.await_count, 1)
        self.assertEqual(pause.await_count, 1)


class Dispatcher(unittest.IsolatedAsyncioTestCase):
    """Follow-up dispatcher: deterministic guardrails around brain-written touches."""

    NOON = datetime(2026, 9, 28, 12, 0, tzinfo=ZoneInfo("America/Sao_Paulo")).timestamp()
    NIGHT = datetime(2026, 9, 28, 22, 0, tzinfo=ZoneInfo("America/Sao_Paulo")).timestamp()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db = Path(self.tmp.name) / "d.db"
        self.patches = [patch.object(app, "DB_PATH", db), patch.object(sdr, "DB_PATH", db), patch.object(handover, "DB_PATH", db),
                        patch.object(app, "SDR_BRAIN_URL", "http://brain"), patch.object(sdr, "typing_seconds", return_value=0)]
        for p in self.patches:
            p.start()
        conn = app.db()
        conn.execute("INSERT INTO contacts VALUES (?,?,?,NULL)", ("5511999@s.whatsapp.net", "src-9", 9))
        conn.commit(); conn.close()
        self.send = AsyncMock(); self.chatwoot = AsyncMock(); self.presence = AsyncMock(); self.note = AsyncMock()
        self.paused = AsyncMock(return_value=False)
        for p in (patch.object(app, "send_evolution", self.send), patch.object(app, "add_chatwoot_message", self.chatwoot),
                  patch.object(app, "send_presence", self.presence), patch.object(sdr, "private_note", self.note),
                  patch.object(handover, "paused", self.paused)):
            p.start(); self.patches.append(p)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    async def run_at(self, ts):
        with patch.object(sdr.time, "time", return_value=ts):
            await app.process_followups_once(now=ts)

    def status(self, fid):
        with sdr.connect() as c:
            return c.execute("SELECT status, reason FROM sdr_followups WHERE id=?", (fid,)).fetchone()

    async def test_success_path(self):
        sdr.touch_activity(9, agent=True, ts=self.NOON - 3600)
        fid = sdr.add_followup(9, self.NOON - 10, "Você falou do financeiro. Isso trava uma pessoa ou o time todo?", "dor", self.NOON - 7200, "2h")
        await self.run_at(self.NOON)
        self.assertEqual(self.status(fid)[0], "sent")
        self.assertEqual(self.send.await_args.args[0], "5511999")  # number, not jid
        self.presence.assert_awaited_with("5511999", "composing")
        self.assertTrue(self.chatwoot.await_args.kwargs["outgoing"])
        self.assertIn("retomada_enviada", handover.context(9)[0])
        self.assertEqual(sdr.activity(9)[1], self.NOON - 3600)  # cadence anchor untouched

    async def test_cancel_rules(self):
        sdr.touch_activity(9, lead=True, ts=self.NOON - 100)
        after_lead = sdr.add_followup(9, self.NOON - 10, "a?", "", self.NOON - 200, "5min")
        await self.run_at(self.NOON)
        self.assertEqual(self.status(after_lead), ("cancelled", "lead_message"))

        paused = sdr.add_followup(9, self.NOON - 10, "b?", "", self.NOON, "30min")
        self.paused.return_value = True
        await self.run_at(self.NOON)
        self.assertEqual(self.status(paused), ("cancelled", "paused"))
        self.paused.return_value = False

        leak = sdr.add_followup(9, self.NOON - 10, "Aqui é o Hermes, lembra?", "", self.NOON, "2h")
        await self.run_at(self.NOON)
        self.assertEqual(self.status(leak)[0], "cancelled")
        self.assertTrue(self.status(leak)[1].startswith("guardrail"))
        self.note.assert_awaited()

        with sdr.connect() as c:
            c.execute("INSERT INTO sdr_records VALUES (9,'desfecho','perdido',?)", (self.NOON,))
        done = sdr.add_followup(9, self.NOON - 10, "c?", "", self.NOON, "d1")
        await self.run_at(self.NOON)
        self.assertEqual(self.status(done), ("cancelled", "desfecho"))
        self.send.assert_not_awaited()

    async def test_night_hold_and_superseded(self):
        first = sdr.add_followup(9, self.NIGHT - 10, "primeiro?", "", 0, "5min")
        second = sdr.add_followup(9, self.NIGHT - 5, "segundo?", "", 0, "30min")
        await self.run_at(self.NIGHT)
        self.assertEqual(self.status(first)[0], "pending")
        self.send.assert_not_awaited()
        await self.run_at(self.NOON + 86400)
        self.assertEqual(self.send.await_count, 1)
        self.assertEqual({self.status(first)[0], self.status(second)[0]}, {"sent", "cancelled"})

    async def test_daily_cap(self):
        with sdr.connect() as c:
            for i in range(4):
                c.execute("INSERT INTO sdr_followups(conversation,send_at,text,status,sent_at) VALUES (9,?,?, 'sent', ?)", (self.NOON - 100, f"t{i}", self.NOON - 100 + i))
        fid = sdr.add_followup(9, self.NOON - 10, "quinto?", "", 0, "d1")
        await self.run_at(self.NOON)
        self.assertEqual(self.status(fid), ("cancelled", "daily_cap"))


if __name__ == "__main__":
    unittest.main()
