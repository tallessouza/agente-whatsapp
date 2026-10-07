import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import app
import handover


class PaymentRequestTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fixture = json.loads((Path(__file__).parent / "fixtures/message-pix-payment.json").read_text())

    def test_request_payment_is_structured_and_keeps_provider_fields(self):
        data = self.fixture["data"]
        event = app.payment_event(data["message"], key=data["key"], data=data)
        self.assertEqual(app.text_from_message(data["message"]), "[Solicitação de pagamento: BRL 50.00]")
        self.assertEqual(event["event_type"], "payment_request")
        self.assertEqual(event["provider_message_type"], "requestPaymentMessage")
        self.assertEqual(event["amount"], 50.0)
        self.assertEqual(event["amount1000"], 50000)
        self.assertEqual(event["currency"], "BRL")
        self.assertEqual(event["request_from"], data["message"]["requestPaymentMessage"]["requestFrom"])
        self.assertEqual(event["context"]["message_id"], "fixture-payment-001")
        self.assertEqual(event["execution"], {"authorized": False, "executed": False})

    def test_interactive_pix_card_is_structured(self):
        payload = json.loads((Path(__file__).parent / "fixtures/message-pix-interactive.json").read_text())["data"]
        event = app.payment_event(payload["message"], key=payload["key"], data=payload)
        self.assertEqual(event["provider_message_type"], "interactiveMessage.payment_info")
        self.assertEqual(event["payment_type"], "pix")
        self.assertEqual(event["pix_key"], "+5548999425822")
        self.assertEqual(event["pix_key_type"], "PHONE")

    def test_nested_payment_info_params_are_structured(self):
        message = {"interactiveMessage": {"nativeFlowMessage": {"messageParamsJson": json.dumps({"payment_info": {"type": "pix", "currency": "BRL", "name": "Talles", "keyType": "PHONE", "key": "+5548999425822"}})}}}
        event = app.payment_event(message, key={"id": "nested-1", "remoteJid": "x@s.whatsapp.net"})
        self.assertEqual(event["payment_type"], "pix")
        self.assertEqual(event["pix_key"], "+5548999425822")

    async def test_structured_event_reaches_hermes_request(self):
        old_key, old_db = app.HERMES_KEY, app.DB_PATH
        tmp = tempfile.TemporaryDirectory()
        app.HERMES_KEY = "test-key"
        app.DB_PATH = Path(tmp.name) / "bridge.db"
        captured = {}

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {"choices": [{"message": {"content": "ok"}}]}

        class Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def post(self, _url, **kwargs):
                captured.update(kwargs["json"])
                return Response()

        try:
            data = self.fixture["data"]
            event = app.payment_event(data["message"], key=data["key"], data=data)
            with patch.object(app.httpx, "AsyncClient", return_value=Client()):
                result = await app.ask_hermes("[Solicitação de pagamento: BRL 50.00]", "wa:test", structured_events=[event])
            self.assertEqual(result, "ok")
            self.assertEqual(captured["metadata"]["bridge_structured_events"][0]["amount"], 50.0)
            self.assertIn("EVENTO_ESTRUTURADO_BRIDGE", captured["messages"][0]["content"])
        finally:
            app.HERMES_KEY, app.DB_PATH = old_key, old_db
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
