"""Validate representative Evolution webhook fixtures without contacting services."""

import json
from pathlib import Path

from app import payment_event, text_from_message


root = Path(__file__).with_name("fixtures")
expected = {
    "message-text.json": "Olá, esta é uma mensagem de teste.",
    "message-media.json": "Legenda da imagem de teste",
    "message-reaction.json": "[Reação recebida: 👍 na mensagem fixture-text-001]",
    "message-outgoing.json": "Resposta enviada de teste",
}

for filename, content in expected.items():
    payload = json.loads((root / filename).read_text())
    assert payload["event"] in {"Message", "SEND_MESSAGE"}
    assert payload["data"]["key"]["id"].startswith("fixture-")
    assert text_from_message(payload["data"]["message"]) == content

group = json.loads((root / "message-group-ignored.json").read_text())
assert group["data"]["key"]["remoteJid"].endswith("@g.us")

evolution_go = json.loads((root / "message-evolution-go.json").read_text())
assert evolution_go["data"]["Info"]["SenderAlt"].endswith("@s.whatsapp.net")
assert text_from_message(evolution_go["data"]["Message"]) == "Payload no formato Evolution Go"
payment = json.loads((root / "message-pix-payment.json").read_text())
payment_event_data = payment_event(payment["data"]["message"], key=payment["data"]["key"], data=payment["data"])
assert payment_event_data["amount"] == 50.0
assert payment_event_data["currency"] == "BRL"
assert payment_event_data["provider_message_type"] == "requestPaymentMessage"
assert payment_event_data["execution"] == {"authorized": False, "executed": False}
pix = json.loads((root / "message-pix-interactive.json").read_text())
pix_event = payment_event(pix["data"]["message"], key=pix["data"]["key"], data=pix["data"])
assert pix_event["payment_type"] == "pix"
assert pix_event["pix_key"] == "+5548999425822"
print(f"validated {len(expected) + 4} Evolution webhook fixtures")
