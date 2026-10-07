import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
import app
import handover
import sdr


class HandoverTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = handover.DB_PATH
        self.old_app_db = app.DB_PATH
        self.old_sdr_db = sdr.DB_PATH
        handover.DB_PATH = Path(self.tmp.name) / "bridge.db"
        app.DB_PATH = handover.DB_PATH
        sdr.DB_PATH = handover.DB_PATH
        app.hermes_pending.clear()
        app.hermes_tasks.clear()

    def tearDown(self):
        handover.DB_PATH = self.old
        app.DB_PATH = self.old_app_db
        sdr.DB_PATH = self.old_sdr_db
        self.tmp.cleanup()

    async def batch(self, during=None, paused=False):
        app.hermes_pending["test"] = [("oi", None, "src", 1, "msg-1", None)]
        ask = AsyncMock(return_value="resposta", side_effect=during)
        send = AsyncMock()
        with patch.object(app, "HERMES_MESSAGE_DEBOUNCE_SECONDS", 0), patch.object(handover, "paused", AsyncMock(return_value=paused)), patch.object(app, "ask_hermes", ask), patch.object(app, "send_evolution", send), patch.object(app, "add_chatwoot_message", AsyncMock()), patch.object(app, "send_presence", AsyncMock()), patch.object(sdr, "typing_seconds", return_value=0):
            await app.hermes_batch_worker("test")
        return ask, send

    async def test_pause_preserves_client_without_generation(self):
        ask, send = await self.batch(paused=True)
        ask.assert_not_called()
        send.assert_not_called()
        self.assertIn("oi", handover.context(1)[0])

    async def test_resume_includes_human_and_paused_client(self):
        handover.record(1, "a", "atendente_humano", "combinei entrega amanhã")
        handover.record(1, "b", "cliente", "obrigado")
        ask, send = await self.batch()
        prompt = ask.call_args.args[0]
        self.assertIn("combinei entrega amanhã", prompt)
        self.assertIn("obrigado", prompt)
        send.assert_awaited_once()
        self.assertEqual(handover.context(1), ("", 0))

    async def test_owner_during_generation_discards_reply_even_if_resumed(self):
        async def interrupt(*args):
            with handover.connect() as c:
                c.execute("INSERT INTO handovers VALUES (1,1,0)")
            return "stale"
        ask, send = await self.batch(during=interrupt)
        send.assert_not_called()
        self.assertIn("oi", handover.context(1)[0])

    async def test_echo_ids_persist_and_do_not_match_owner(self):
        handover.outbound_id("bot-id")
        self.assertTrue(handover.is_echo("bot-id"))
        self.assertFalse(handover.is_echo("owner-id"))

    async def test_failed_label_write_keeps_local_barrier(self):
        with patch.object(handover, "ensure_label", AsyncMock(side_effect=RuntimeError("offline"))):
            with self.assertRaises(RuntimeError):
                await handover.pause(1)
        with handover.connect() as c:
            self.assertEqual(c.execute("SELECT pending_label FROM handovers WHERE conversation=1").fetchone(), (1,))

    async def test_removing_label_resumes_without_erasing_history(self):
        handover.record(1, "h", "atendente_humano", "contexto")
        with handover.connect() as c:
            c.execute("INSERT INTO handovers VALUES (1,1,1)")
        with patch.object(handover, "labels", AsyncMock(return_value=[])):
            self.assertFalse(await handover.paused(1))
        self.assertIn("contexto", handover.context(1)[0])

    async def test_labels_preserved_on_pause(self):
        response = unittest.mock.Mock()
        response.raise_for_status = unittest.mock.Mock()
        client = AsyncMock()
        client.post.return_value = response
        manager = AsyncMock()
        manager.__aenter__.return_value = client
        with patch.object(handover, "labels", AsyncMock(return_value=["venda"])), patch.object(handover.httpx, "AsyncClient", return_value=manager):
            await handover.pause(1)
        self.assertEqual(client.post.call_args.kwargs["json"], {"labels": ["venda", handover.LABEL]})


if __name__ == "__main__":
    unittest.main()
