"""Fila para o Hermes: 429 vira espera e nova tentativa, e nunca passam de HERMES_MAX_CONCURRENCY ao mesmo tempo."""
import asyncio
import os
import tempfile
import unittest

os.environ.setdefault("BRIDGE_DB", os.path.join(tempfile.mkdtemp(), "t.db"))
import app  # noqa: E402


class FakeResponse:
    def __init__(self, status, payload=None):
        self.status_code = status
        self.headers = {"Retry-After": "0"} if status == 429 else {}
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class HermesQueueTests(unittest.TestCase):
    def setUp(self):
        self.real_client = app.httpx.AsyncClient
        self.real_slots = app.hermes_slots
        self.real_key = app.HERMES_KEY
        app.HERMES_KEY = "test"

    def tearDown(self):
        app.httpx.AsyncClient = self.real_client
        app.hermes_slots = self.real_slots
        app.HERMES_KEY = self.real_key

    def fake_client(self, responses, active, peak):
        class Client:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, *a, **k):
                active[0] += 1
                peak[0] = max(peak[0], active[0])
                await asyncio.sleep(0.01)
                active[0] -= 1
                return responses.pop(0) if responses else FakeResponse(200, {"choices": [{"message": {"content": "oi"}}]})

        return Client

    def test_429_waits_and_retries_instead_of_failing(self):
        active, peak = [0], [0]
        responses = [FakeResponse(429), FakeResponse(429)]
        app.httpx.AsyncClient = self.fake_client(responses, active, peak)
        reply = asyncio.run(app.ask_hermes("E aí", "wa:test:1"))
        self.assertEqual(reply, "oi")
        self.assertEqual(responses, [])

    def test_never_more_than_the_cap_at_once(self):
        active, peak = [0], [0]
        app.httpx.AsyncClient = self.fake_client([], active, peak)

        async def run():
            app.hermes_slots = asyncio.Semaphore(3)
            return await asyncio.gather(*(app.ask_hermes("E aí", f"wa:test:{i}") for i in range(12)))

        replies = asyncio.run(run())
        self.assertEqual(replies, ["oi"] * 12)
        self.assertLessEqual(peak[0], 3)


if __name__ == "__main__":
    unittest.main()
