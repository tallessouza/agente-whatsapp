import asyncio
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import app
import handover
import prospeccao
import sdr

TZ = sdr.BUSINESS_TZ


def ts(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=TZ).timestamp()


class ProspeccaoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db = Path(self.tmp.name) / "bridge.db"
        self.patches = [patch.object(sdr, "DB_PATH", db), patch.object(handover, "DB_PATH", db), patch.object(app, "DB_PATH", db)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_normalize_and_enqueue_dedupes(self):
        self.assertEqual(prospeccao.normalize_number("(48) 99999-0000"), "5548999990000")
        self.assertEqual(prospeccao.normalize_number("+55 47 3333-0000"), "554733330000")
        self.assertIsNone(prospeccao.normalize_number("0800 123 4567"))
        result = prospeccao.enqueue([
            {"telefone_e164": "+5548999990000", "nome": "Clínica A", "nicho": "clínica odontológica", "cidade": "São José", "extra": "x"},
            {"telefone_e164": "5548999990000", "nome": "Clínica A de novo"},
            {"telefone_e164": "123"},
        ])
        self.assertEqual(result, {"novos": 1, "repetidos": 1, "invalidos": 1})
        numero, dados = prospeccao.next_queued()
        self.assertEqual(numero, "5548999990000")
        self.assertNotIn("extra", dados)

    def test_window_holiday_and_ramp(self):
        self.assertTrue(prospeccao.in_window(datetime(2026, 10, 13, 19, 0, tzinfo=TZ), "0-4@18:30-21:00"))   # terça
        self.assertFalse(prospeccao.in_window(datetime(2026, 10, 13, 21, 0, tzinfo=TZ), "0-4@18:30-21:00"))
        self.assertFalse(prospeccao.in_window(datetime(2026, 10, 10, 19, 0, tzinfo=TZ), "0-4@18:30-21:00"))  # sábado
        self.assertFalse(prospeccao.in_window(datetime(2026, 10, 12, 19, 0, tzinfo=TZ), "0-4@18:30-21:00"))  # feriado
        self.assertTrue(prospeccao.in_window(datetime(2026, 10, 10, 10, 0, tzinfo=TZ), "0-4@18:30-21:00,5@09:00-12:00"))
        with patch.object(prospeccao, "PROSPECT_RAMP", [40, 60]):
            self.assertEqual(prospeccao.daily_cap(ts(2026, 10, 13, 19)), 40)
            prospeccao.enqueue([{"numero": "5548999990001"}])
            prospeccao.update("5548999990001", status="enviado", enviado_em=ts(2026, 10, 13, 19))
            self.assertEqual(prospeccao.daily_cap(ts(2026, 10, 13, 20)), 40)   # same day
            self.assertEqual(prospeccao.daily_cap(ts(2026, 10, 14, 19)), 60)
            self.assertEqual(prospeccao.daily_cap(ts(2026, 10, 22, 19)), 60)   # last step repeats

    def test_gap_stays_inside_bounds(self):
        with patch.object(prospeccao, "PROSPECT_MIN_GAP", 10), patch.object(prospeccao, "PROSPECT_MAX_GAP", 240):
            gaps = [prospeccao.next_gap() for _ in range(200)]
        self.assertTrue(all(10 <= g <= 240 for g in gaps))
        self.assertGreater(max(gaps) - min(gaps), 60)

    def test_test_text_varies_and_greets_by_hour(self):
        night = datetime(2026, 10, 13, 19, 0, tzinfo=TZ)
        texts = {prospeccao.test_text(night) for _ in range(80)}
        self.assertGreater(len(texts), 1)
        self.assertTrue(all("boa noite" in t.lower() for t in texts))
        self.assertTrue(all("{" not in t for t in texts))

    def test_origin_reply_time_and_pitch_skips_weekend_and_holiday(self):
        sent = ts(2026, 10, 9, 20, 12)   # sexta; segunda 12/10 é feriado
        prospeccao.enqueue([{"numero": "5548999990002", "nome": "Imobiliária B", "cidade": "Itajaí"}])
        prospeccao.update("5548999990002", status="enviado", enviado_em=sent, jid="554899990002@s.whatsapp.net", conversation=77, texto="Boa noite! ...")
        self.assertIsNotNone(prospeccao.schedule_pitch(77, sent, now=sent))
        self.assertIsNone(prospeccao.schedule_pitch(77, sent, now=sent))   # only one
        row = sdr.pending_followups(77)[0]
        pitch_at = datetime.fromtimestamp(row[2], TZ)
        self.assertEqual(pitch_at.date().isoformat(), "2026-10-13")         # terça
        self.assertTrue(9 * 60 + 30 <= pitch_at.hour * 60 + pitch_at.minute < 12 * 60)
        self.assertIn("Na sexta às 20h12", row[3])
        self.assertIn("é normal", row[3])
        self.assertIn("não mando mais nada", row[3])
        self.assertEqual(sdr.leaked_terms([row[3]]), [])
        self.assertTrue(prospeccao.replied("554899990002@s.whatsapp.net", ts=sent + 47 * 60))
        self.assertFalse(prospeccao.replied("554899990002@s.whatsapp.net", ts=sent + 60 * 60))
        self.assertTrue(sdr.remember_lead(77, "554899990002@s.whatsapp.net", "Boa noite, sim! Como posso ajudar?"))
        state = sdr.lead_state(77)
        self.assertEqual(state["origem"]["canal"], "prospeccao")
        self.assertEqual(state["origem"]["minutos_para_responder"], 47)
        self.assertEqual(state["origem"]["negocio"]["nome"], "Imobiliária B")
        self.assertEqual(state["oferta"], "atendimento")
        self.assertIn("atendimento", sdr.OFFERS)

    def test_pitch_uses_the_enriched_hook(self):
        sent = ts(2026, 10, 13, 19, 40)
        prospeccao.enqueue([{"numero": "5548999990006", "nome": "Clínica E", "gancho": "Vi que o site de vocês leva o cliente direto pro WhatsApp."}])
        prospeccao.update("5548999990006", status="enviado", enviado_em=sent, conversation=66)
        prospeccao.schedule_pitch(66, sent, now=sent)
        text = sdr.pending_followups(66)[0][3]
        self.assertIn("Vi que o site de vocês leva o cliente direto pro WhatsApp. Eu instalo", text)
        self.assertNotIn("\n\n\n", text)

    def test_pitch_says_yesterday_on_the_next_day(self):
        sent = ts(2026, 10, 13, 19, 40)
        self.assertEqual(prospeccao.when_label(sent, ts(2026, 10, 14, 10, 0)), "ontem às 19h40")

    def test_automatic_greeting_brings_the_pitch_back(self):
        sent = ts(2026, 10, 13, 19, 5)
        prospeccao.enqueue([{"numero": "5548999990003", "nome": "Escritório C"}])
        prospeccao.update("5548999990003", status="enviado", enviado_em=sent, jid="554899990003@s.whatsapp.net", conversation=88)
        prospeccao.schedule_pitch(88, sent, now=sent)
        prospeccao.replied("554899990003@s.whatsapp.net", ts=sent + 2)
        sdr.cancel_followups(88, "lead_message")          # what the bridge does on any incoming message
        self.assertEqual(sdr.pending_followups(88), [])
        with patch.object(sdr, "_chatwoot", AsyncMock()):
            asyncio.run(sdr.record(88, "resposta_automatica", "sim"))
        pending = sdr.pending_followups(88)
        self.assertEqual(len(pending), 1)
        self.assertIn("menu automático", pending[0][3])
        row = prospeccao.for_jid("554899990003@s.whatsapp.net")
        self.assertEqual(row["status"], "automatica")
        self.assertIsNone(row["respondeu_em"])

    def test_prospect_once_respects_switch_window_gap_and_sends(self):
        prospeccao.enqueue([{"numero": "5548999990004", "nome": "Locadora D"}])
        tuesday_night = ts(2026, 10, 13, 19, 0)
        with patch.object(prospeccao, "PROSPECT_ENABLED", False):
            self.assertEqual(asyncio.run(app.prospect_once(now=tuesday_night)), "desligada")
        with patch.object(prospeccao, "PROSPECT_ENABLED", True):
            self.assertEqual(asyncio.run(app.prospect_once(now=ts(2026, 10, 13, 15, 0))), "fora_da_janela")
            check = {"IsInWhatsapp": True, "JID": "554899990004@s.whatsapp.net", "LID": "1234@lid", "VerifiedName": "Locadora D"}
            with patch.object(app, "check_whatsapp", AsyncMock(return_value=check)), \
                 patch.object(app, "ensure_conversation", AsyncMock(return_value=("src", 99))), \
                 patch.object(app, "send_presence", AsyncMock()), patch.object(app, "send_evolution", AsyncMock()) as send, \
                 patch.object(app, "add_chatwoot_message", AsyncMock()), patch.object(sdr, "add_label", AsyncMock()), \
                 patch.object(sdr, "private_note", AsyncMock()), patch.object(app.asyncio, "sleep", AsyncMock()):
                self.assertEqual(asyncio.run(app.prospect_once(now=tuesday_night)), "enviado")
                self.assertEqual(send.await_args.args[0], "554899990004")
                self.assertEqual(asyncio.run(app.prospect_once(now=tuesday_night + 5)), "intervalo")
        row = prospeccao.for_jid("1234@lid")
        self.assertEqual(row["status"], "enviado")
        self.assertEqual(row["conversation"], 99)
        self.assertEqual(len(sdr.pending_followups(99)), 1)

    def test_number_without_whatsapp_is_skipped(self):
        prospeccao.enqueue([{"numero": "554733330000"}])
        with patch.object(prospeccao, "PROSPECT_ENABLED", True), \
             patch.object(app, "check_whatsapp", AsyncMock(return_value={"IsInWhatsapp": False})):
            self.assertEqual(asyncio.run(app.prospect_once(now=ts(2026, 10, 13, 19))), "sem_whatsapp")
        self.assertIsNone(prospeccao.next_queued())

    def test_stats(self):
        prospeccao.enqueue([{"numero": "5548999990005"}])
        stats = prospeccao.stats(now=ts(2026, 10, 13, 19))
        self.assertEqual(stats["por_status"], {"fila": 1})
        self.assertEqual(stats["teto_hoje"], prospeccao.PROSPECT_RAMP[0])


if __name__ == "__main__":
    unittest.main()
