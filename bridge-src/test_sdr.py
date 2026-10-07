import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import app
import handover
import sdr


class ParseReplyTests(unittest.TestCase):
    def test_directives_are_stripped_and_parsed(self):
        reply = ("Sou o agente do Talles.[[QUEBRA]]O que trava na sua operação quando você fica uma semana fora?"
                 "\n[[REGISTRO: dor = \"tudo para quando eu saio\"]]\n[[FOTO: entregas]]")
        parts, directives = sdr.parse_reply(reply)
        self.assertEqual(parts, ["Sou o agente do Talles.", "O que trava na sua operação quando você fica uma semana fora?"])
        self.assertIn({"type": "registro", "campo": "dor", "valor": "\"tudo para quando eu saio\""}, directives)
        self.assertIn({"type": "foto", "nome": "entregas"}, directives)
        self.assertNotIn("[[", "".join(parts))

    def test_escalation_directive(self):
        _parts, directives = sdr.parse_reply("Vou chamar ele agora. [[ESCALAR: indecisão | preciso pensar melhor]]")
        self.assertEqual(directives, [{"type": "escalar", "motivo": "indecisão", "frase": "preciso pensar melhor"}])

    def test_unknown_and_malformed_markers_never_reach_the_lead(self):
        parts, directives = sdr.parse_reply("Oi [[OUTRA: x]] tudo bem? [[REGISTRO: Campo Invalido = x]] [[quebrado")
        self.assertEqual(directives, [])
        self.assertEqual(parts, ["Oi  tudo bem?  quebrado"])

    def test_blank_lines_and_quebra_split_into_at_most_three_bubbles(self):
        parts, _ = sdr.parse_reply("a[[QUEBRA]]b[[QUEBRA]]c[[QUEBRA]]d")
        self.assertEqual(parts, ["a", "b", "c\n\nd"])
        parts, _ = sdr.parse_reply("Entendo totalmente.\n\nQuantas pessoas dependem de você?")
        self.assertEqual(parts, ["Entendo totalmente.", "Quantas pessoas dependem de você?"])
        parts, _ = sdr.parse_reply("linha 1\nlinha 2 do mesmo balão")
        self.assertEqual(parts, ["linha 1\nlinha 2 do mesmo balão"])


    def test_silence_sends_nothing_but_keeps_records(self):
        parts, directives = sdr.parse_reply("[[SILENCIO]] [[REGISTRO: desfecho = desqualificado]]")
        self.assertEqual(parts, [])
        self.assertEqual(directives, [{"type": "registro", "campo": "desfecho", "valor": "desqualificado"}])


class NoDashesTests(unittest.TestCase):
    def test_dashes_between_sentences_become_commas(self):
        cases = {
            "Entendo totalmente — e essa parte eu prefiro que você fale com o Talles.": "Entendo totalmente, e essa parte eu prefiro que você fale com o Talles.",
            "Resolver isso de ponta a ponta — de 3 a 5 fluxos, rodando em 21 dias — é a implantação: R$ 48.000.": "Resolver isso de ponta a ponta, de 3 a 5 fluxos, rodando em 21 dias, é a implantação: R$ 48.000.",
            "O Raio-X — 7 dias.": "O Raio-X, 7 dias.",
            "Fechado — Raio-X, 7 dias —, começando no dia 1.": "Fechado, Raio-X, 7 dias, começando no dia 1.",
            "Isso fica com ele —": "Isso fica com ele",
            "— primeiro ponto\n– segundo": "primeiro ponto\nsegundo",
            "o gargalo mapeado–o fluxo rodando": "o gargalo mapeado, o fluxo rodando",
            "Resposta rápida - sem enrolação.": "Resposta rápida, sem enrolação.",
            "dias 2-3 e o e-mail; R$ 12 a 18 mil": "dias 2-3 e o e-mail; R$ 12 a 18 mil",
        }
        for raw, expected in cases.items():
            self.assertEqual(sdr.no_dashes(raw), expected, raw)
        for dash in "\u2014\u2013\u2012\u2015":
            self.assertNotIn(dash, sdr.no_dashes(f"a {dash} b{dash}c {dash}"))


class NoColonsTests(unittest.TestCase):
    def test_colons_chaining_sentences_are_split(self):
        cases = {
            "O Raio-X custa R$ 12.000 e dura 7 dias: o Talles também abate na implantação.": "O Raio-X custa R$ 12.000 e dura 7 dias. O Talles também abate na implantação.",
            "Resolver isso de ponta a ponta é a implantação: R$ 48.000.": "Resolver isso de ponta a ponta é a implantação, R$ 48.000.",
            "São 4 vagas: 3 já foram.": "São 4 vagas, 3 já foram.",
            "Antes, três perguntas rápidas:": "Antes, três perguntas rápidas.",
            "Te respondo às 10:30, link https://wa.me/55": "Te respondo às 10:30, link https://wa.me/55",
        }
        for raw, expected in cases.items():
            self.assertEqual(sdr.no_colons(raw), expected, raw)
        self.assertEqual(sdr.plain_style("Fechado — Raio-X: 7 dias: começando no dia 1."), "Fechado, Raio-X, 7 dias. Começando no dia 1.")


class GuardrailTests(unittest.TestCase):
    def test_blocks_stack_names_accent_insensitive(self):
        self.assertEqual(sdr.leaked_terms(["Eu rodo no Hermes com Gêmini? não, gemini"]), ["hermes", "gemini"])
        self.assertEqual(sdr.leaked_terms(["arquivo em /opt/data/x"]), ["/opt/"])

    def test_offer_prerequisites_are_not_leaks(self):
        allowed = ["Sem Codex? Dá pra levar a Conta do Gemini junto na compra.",
                   "O Codex vem no plano pago do ChatGPT, Plus ou maior. Conta grátis não funciona.",
                   "Se você já assina o ChatGPT Plus, está resolvido."]
        self.assertEqual(sdr.leaked_terms(allowed), [])
        self.assertEqual(sdr.leaked_terms(["Eu rodo no Gemini da Google"]), ["gemini"])
        self.assertEqual(sdr.leaked_terms(["Sou um ChatGPT treinado"]), ["chatgpt"])

    def test_installer_script_of_the_soul_passes_the_guardrail(self):
        soul = (Path(__file__).resolve().parent.parent / "hermes-sdr" / "SOUL.md").read_text(encoding="utf-8")
        installer = soul.split("═══ CAMINHO DO INSTALADOR ═══")[1].split("═══ CAMINHO DO RAIO-X ═══")[0]
        self.assertEqual(sdr.leaked_terms([installer]), [])

    def test_normal_sales_text_passes(self):
        text = ["Entendo totalmente. A implantação é R$ 48.000, 21 dias. A evolução do seu time aparece no dia 3, faz sentido?"]
        self.assertEqual(sdr.leaked_terms(text), [])


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.patches = [
            patch.object(sdr, "DB_PATH", self.dir / "bridge.db"),
            patch.object(sdr, "CAPACITY_FILE", self.dir / "capacidade.json"),
            patch.object(sdr, "MEDIA_DIR", self.dir / "midia"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def write_capacity(self, **overrides):
        data = {"mes": "outubro/2026", "vagas_total": 4, "vagas_restantes": 3, "horas_comprometidas": 40,
                "horas_limite": 75, "proximo_mes": "novembro/2026", "atualizado_em": datetime.now().isoformat()}
        data.update(overrides)
        (self.dir / "capacidade.json").write_text(json.dumps(data))

    def test_capacity_unknown_when_missing(self):
        self.assertEqual(sdr.capacity(), {"status": "desconhecido"})

    def test_capacity_ok_and_full(self):
        self.write_capacity()
        self.assertTrue(sdr.capacity()["pode_oferecer_este_mes"])
        self.write_capacity(horas_comprometidas=76)
        self.assertFalse(sdr.capacity()["pode_oferecer_este_mes"])
        self.write_capacity(vagas_restantes=0)
        self.assertFalse(sdr.capacity()["pode_oferecer_este_mes"])

    def test_capacity_stale(self):
        self.write_capacity(atualizado_em=(datetime.now() - timedelta(days=9)).isoformat())
        self.assertEqual(sdr.capacity(), {"status": "desatualizado"})

    def test_only_described_media_is_offered_and_loadable(self):
        media = self.dir / "midia"
        media.mkdir()
        (media / "entregas.jpg").write_bytes(b"\xff\xd8jpg")
        (media / "sem-descricao.png").write_bytes(b"png")
        (media / "descricoes.json").write_text(json.dumps({"entregas.jpg": "painel de entregas"}))
        self.assertEqual(sdr.media_catalog(), [{"nome": "entregas", "descricao": "painel de entregas"}])
        self.assertIsNotNone(sdr.load_media("entregas"))
        self.assertIsNone(sdr.load_media("sem-descricao"))
        self.assertIsNone(sdr.load_media("../../etc/passwd"))

    def test_origin_from_prefilled_instagram_text(self):
        self.assertEqual(sdr.origin_from_text("Oi! Sou @loja.da_ana [R3]"), {"instagram": "@loja.da_ana", "peca": "R3", "canal": "instagram", "oferta": "raiox"})
        self.assertEqual(sdr.origin_from_text("Oi! Sou @there [R2]"), {"peca": "R2", "canal": "instagram", "oferta": "raiox"})
        self.assertIsNone(sdr.origin_from_text("bom dia, quanto custa?"))

    def test_offer_from_the_campaign_text(self):
        instalador = sdr.origin_from_text("Oi! Sou o @ana.studio e quero o meu Time de IA instalado")
        self.assertEqual(instalador, {"instagram": "@ana.studio", "canal": "instagram", "oferta": "instalador"})
        raiox = sdr.origin_from_text("E aí! Sou o @marina.escala e quero saber mais sobre o Raio-X")
        self.assertEqual(raiox["oferta"], "raiox")
        self.assertEqual(sdr.offer_from_text("quero o raiox"), "raiox")
        self.assertEqual(sdr.offer_from_text("quero meu TIME DE IA"), "instalador")
        self.assertIsNone(sdr.offer_from_text("meu time é bom, quanto custa?"))
        self.assertEqual(sdr.origin_from_text("quero o meu Time de IA instalado"), {"oferta": "instalador"})

    def test_offer_and_next_step_reach_the_context(self):
        sdr.remember_lead(11, "55@s.whatsapp.net", "Oi! Sou o @ana e quero o meu Time de IA instalado")
        payload = json.loads(sdr.trusted_context(11).split("\n")[1])
        self.assertEqual(payload["oferta"], "instalador")
        self.assertEqual(payload["lead"]["origem"]["oferta"], "instalador")
        with sdr.connect() as c:
            for field, value in (("tem_vps", "não"), ("proximo_passo", "contratar a VPS"), ("proximo_passo_em", "2026-10-08")):
                c.execute("INSERT INTO sdr_records VALUES (?,?,?,?)", (11, field, value, 1.0))
        lead = sdr.context_payload(11)["lead"]
        self.assertEqual(lead["registros"]["proximo_passo_em"], "2026-10-08")
        self.assertEqual(lead["proximo_passo"], {"texto": "contratar a VPS", "ate": "2026-10-08"})
        # What the agent records later wins over the campaign text.
        with sdr.connect() as c:
            c.execute("INSERT INTO sdr_records VALUES (?,?,?,?)", (11, "oferta", "raiox", 2.0))
        self.assertEqual(sdr.context_payload(11)["oferta"], "raiox")
        # No campaign and no record: the agent discovers it in the conversation.
        sdr.remember_lead(12, "56@s.whatsapp.net", "bom dia, quanto custa?")
        self.assertNotIn("oferta", sdr.context_payload(12))

    def test_offer_facts_file(self):
        with patch.object(sdr, "OFFERS_FILE", self.dir / "ofertas.json"):
            self.assertEqual(sdr.offers(), {"status": "desconhecido"})
        with patch.object(sdr, "OFFERS_FILE", Path(__file__).resolve().parent.parent / "hermes-sdr" / "ofertas.json"):
            facts = sdr.offers()
            self.assertEqual(facts["instalador"]["preco"], "R$ 47")
            self.assertEqual(facts["instalador"]["link_compra"], "https://instalador.talles.dev/antes")
            self.assertEqual(facts["raiox"]["preco"], "R$ 12.000")
            self.assertEqual(sdr.context_payload(13)["ofertas"], facts)

    def test_corrections_reach_the_next_turn(self):
        sdr.record_correction(8, ["Dados ficam comigo.", "A implantação é R$ 48.000."], ["Dados ficam comigo."], "review")
        sdr.record_correction(8, ["igual"], ["igual"], "review")  # unchanged: not stored
        payload = json.loads(sdr.trusted_context(8).split("\n")[1])
        self.assertEqual(payload["mensagens_corrigidas"], [{"voce_escreveu": "Dados ficam comigo.\n\nA implantação é R$ 48.000.", "o_lead_recebeu": "Dados ficam comigo."}])
        self.assertNotIn("mensagens_corrigidas", json.loads(sdr.trusted_context(9).split("\n")[1]))

    def test_origin_recorded_once_and_in_context(self):
        sdr.remember_lead(7, "55@s.whatsapp.net", "Oi! Sou @ana [R1]")
        sdr.remember_lead(7, "55@s.whatsapp.net", "Sou @outra [R9]")
        context = sdr.trusted_context(7, guidance=[(1, "traga a âncora agora")])
        payload = json.loads(context.split("\n")[1])
        self.assertEqual(payload["lead"]["origem"]["instagram"], "@ana")
        self.assertEqual(payload["orientacoes"], ["traga a âncora agora"])
        self.assertEqual(payload["capacidade"], {"status": "desconhecido"})


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db = Path(self.tmp.name) / "bridge.db"
        self.patches = [patch.object(sdr, "DB_PATH", db), patch.object(handover, "DB_PATH", db), patch.object(app, "DB_PATH", db),
                        patch.object(sdr, "typing_seconds", return_value=0), patch.object(app, "send_presence", AsyncMock())]
        for p in self.patches:
            p.start()
        self.send = AsyncMock()
        self.chatwoot = AsyncMock()
        self.escalate = AsyncMock()
        self.record = AsyncMock()
        self.patches += [patch.object(app, "send_evolution", self.send), patch.object(app, "add_chatwoot_message", self.chatwoot),
                         patch.object(app, "escalate", self.escalate), patch.object(sdr, "record", self.record),
                         patch.object(sdr, "private_note", AsyncMock())]
        for p in self.patches[5:]:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    async def test_split_messages_records_and_escalation(self):
        reply = "Entendo.[[QUEBRA]]Vou chamar o Talles, pode ser?[[REGISTRO: desfecho = escalado]][[ESCALAR: pediu pessoa | quero falar com alguém]]"
        await app.deliver_agent_reply("5511@s.whatsapp.net", "src", 3, reply, "msg-1", "quero falar com alguém")
        self.assertEqual([c.args[1] for c in self.send.await_args_list], ["Entendo.", "Vou chamar o Talles, pode ser?"])
        self.assertEqual(self.send.await_args_list[0].kwargs["reply_to"], "msg-1")
        self.assertIsNone(self.send.await_args_list[1].kwargs["reply_to"])
        self.record.assert_awaited_once_with(3, "desfecho", "escalado")
        self.assertEqual(self.escalate.await_args.args[3]["motivo"], "pediu pessoa")

    async def test_guardrail_replaces_leaking_reply_and_escalates(self):
        await app.deliver_agent_reply("5511@s.whatsapp.net", "src", 3, "Eu sou o Hermes Agent da Nous Research.", None, "que IA é você?")
        self.assertEqual([c.args[1] for c in self.send.await_args_list], [sdr.FALLBACK_REPLY])
        self.assertIn("guardrail", self.escalate.await_args.args[3]["motivo"])

    async def test_campaign_offer_is_recorded_like_a_directive(self):
        with patch.object(app, "brain_event", AsyncMock()) as event:
            await app.record_offer_from_origin(5, {"instagram": "@ana", "oferta": "instalador"})
            await app.record_offer_from_origin(6, {"instagram": "@ana"})
            await app.record_offer_from_origin(7, None)
            await asyncio.sleep(0)
        self.record.assert_awaited_once_with(5, "oferta", "instalador")
        self.assertEqual(event.await_args.args[0], "/events/record")
        self.assertEqual({k: event.await_args.args[1][k] for k in ("conversation_id", "campo", "valor")},
                         {"conversation_id": 5, "campo": "oferta", "valor": "instalador"})

    def test_session_prefix_defaults_to_v13(self):
        import importlib, os
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HERMES_SESSION_PREFIX", None)
            self.assertEqual(importlib.reload(app).HERMES_SESSION_PREFIX, "wa:v13:")

    async def test_owner_messages_are_not_leads(self):
        with patch.object(sdr, "OWNER_IDS", {"5564999425822", "556499425822", "148563086540988"}):
            self.assertTrue(sdr.is_owner("556499425822@s.whatsapp.net"))
            self.assertTrue(sdr.is_owner("148563086540988@lid"))
            self.assertTrue(sdr.is_owner("5564999425822@s.whatsapp.net"))
            self.assertFalse(sdr.is_owner("5511@s.whatsapp.net"))
        with patch.object(sdr, "OWNER_IDS", set()):
            self.assertFalse(sdr.is_owner("556499425822@s.whatsapp.net"))


class AuditFilterAndOfferTests(unittest.TestCase):
    """Audit of SOUL v13 (06/10): the bridge filter and the offer of the first message."""

    def test_offer_answers_about_the_leads_own_ai_pass(self):
        allowed = [
            "o Codex, que é o plano pago do ChatGPT (Plus ou maior), referência R$ 100 por mês. Conta grátis não funciona.",
            "Sem Codex, dá para levar a Conta do Gemini junto na compra.",
            "A conta grátis do ChatGPT não funciona, precisa ser a paga.",
            "Serve se o seu ChatGPT for o Plus.",
            "O ChatGPT Pro também serve.",
            "quem levou a Conta do Gemini autoriza pela Conta do Gemini",
            "autoriza pelo OAuth do Gemini",
            "O Gemini Advanced serve no lugar?",
            "Seu ChatGPT Plus precisa estar ativo.",
            "Dá pra usar o seu Gemini? Só a Conta do Gemini levada na compra.",
        ]
        for text in allowed:
            self.assertEqual(sdr.leaked_terms([text]), [], text)

    def test_what_runs_the_agent_is_still_blocked(self):
        for text, expected in [("Com 4 GB roda só o Hermes e mais 1 módulo.", ["hermes"]),
                               ("Roda num Docker na sua VPS.", ["docker"]),
                               ("Eu rodo no Gemini.", ["gemini"]),
                               ("Quem levou o Gemini autoriza pelo próprio Gemini.", ["gemini"]),
                               ("Eu rodo no ChatGPT Plus, igual ao seu.", ["modelo próprio"]),
                               ("Por trás de mim tem um ChatGPT Pro.", ["modelo próprio"])]:
            self.assertEqual(sdr.leaked_terms([text]), expected, text)

    def test_what_the_person_wants_wins_over_the_word_she_cites(self):
        cases = {
            "Oi! Sou o @ana.studio e quero o meu Time de IA instalado": "instalador",
            "E aí! Sou o @marina.escala e quero saber mais sobre o Raio-X": "raiox",
            "Oi, vi o raio x e quero montar um time de IA na empresa": "instalador",
            "não quero raio-x, quero o time": "instalador",
            "vi o raio x e quero montar um time": "instalador",
            "TIME": "instalador",
            "quero o time instalado": "instalador",
            "Oi! Sou @x [R5] quero o meu time de ia": "instalador",
            "não quero o raio x": None,
            "meu time é bom, quanto custa?": None,
            "bom dia, quanto custa?": None,
        }
        for text, offer in cases.items():
            self.assertEqual(sdr.offer_from_text(text), offer, text)

    def test_old_reel_tag_is_still_the_raiox(self):
        # "Oi! Sou @x [R<n>]" was the reel DM when the Raio-X was the only offer (HERMES_OPS_LOG 27/09).
        self.assertEqual(sdr.origin_from_text("Oi! Sou @loja.da_ana [R3]")["oferta"], "raiox")
        self.assertEqual(sdr.origin_from_text("Oi! Sou @x [R5] quero o meu time de ia")["oferta"], "instalador")


class CredentialTests(unittest.IsolatedAsyncioTestCase):
    """A password the lead pastes never reaches Chatwoot, Hermes or the brain."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db = Path(self.tmp.name) / "bridge.db"
        self.patches = [patch.object(sdr, "DB_PATH", db), patch.object(handover, "DB_PATH", db), patch.object(app, "DB_PATH", db)]
        for p in self.patches:
            p.start()
        app.hermes_pending.clear(); app.hermes_tasks.clear()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_redaction_rules(self):
        cases = {
            "a senha é Abc123! e o ip 203.0.113.7": "a senha é [credencial removida]! e o ip [credencial removida]",
            "senha: banana": "senha: [credencial removida]",
            "usuario root senha 9988": "usuario root senha [credencial removida]",
            "token 123456789:AAH-abcdefghijklmnopqrstuvwxyz0123": "token [credencial removida]",
            "minha senha do servidor é Xpto2026.": "minha senha do servidor é [credencial removida].",
        }
        for text, expected in cases.items():
            self.assertEqual(sdr.redact_credentials(text), (expected, True), text)
        for text in ("a senha é segura?", "onde eu coloco a senha?", "quanto custa a VPS de 8 GB?", "o login é pelo e-mail"):
            self.assertEqual(sdr.redact_credentials(text), (text, False), text)

    def test_webhook_stores_only_the_redacted_text(self):
        payload = json.loads((Path(__file__).parent / "fixtures" / "message-text.json").read_text(encoding="utf-8"))
        payload["data"]["key"]["id"] = "fixture-secret-001"
        payload["data"]["message"]["conversation"] = "meu ip é 203.0.113.7 e a senha: Segredo#1"
        chatwoot, queue = AsyncMock(return_value={"id": 1}), Mock()
        from fastapi.testclient import TestClient
        with patch.object(app, "ensure_conversation", AsyncMock(return_value=("src", 41))), \
                patch.object(app, "add_chatwoot_message", chatwoot), patch.object(app, "queue_hermes_turn", queue), \
                patch.object(app, "BRIDGE_WEBHOOK_TOKEN", ""):
            self.assertEqual(TestClient(app.app).post("/evolution/webhook", json=payload).status_code, 200)
        stored, queued = chatwoot.await_args.args[2], queue.call_args.args[1]
        for text in (stored, queued):
            self.assertNotIn("Segredo#1", text)
            self.assertNotIn("203.0.113.7", text)
            self.assertIn(sdr.CREDENTIAL_MARK, text)

    async def test_turn_sends_the_notice_and_hermes_gets_the_mark(self):
        jid = "5511@s.whatsapp.net"
        app.hermes_pending[jid] = [("ok, a senha é " + sdr.CREDENTIAL_MARK + ", e quanto custa?", None, "src", 42, "m-1", None)]
        ask, send, chatwoot, record = AsyncMock(return_value=""), AsyncMock(), AsyncMock(), AsyncMock()
        with patch.object(app, "HERMES_MESSAGE_DEBOUNCE_SECONDS", 0), patch.object(handover, "paused", AsyncMock(return_value=False)), \
                patch.object(app, "ask_hermes", ask), patch.object(app, "send_evolution", send), patch.object(app, "add_chatwoot_message", chatwoot), \
                patch.object(app, "brain_event", AsyncMock()), patch.object(sdr, "record", record), \
                patch.object(app, "record_offer_from_origin", AsyncMock()):
            await app.hermes_batch_worker(jid)
        self.assertEqual(send.await_args.args[1], sdr.CREDENTIAL_NOTICE)
        record.assert_any_await(42, "mandou_credencial", "sim")
        prompt, system = ask.await_args.args[0], ask.await_args.args[4]
        self.assertIn(sdr.CREDENTIAL_MARK, prompt)
        self.assertIn("credencial_removida", system)

    async def test_audio_transcript_with_a_password_is_redacted_too(self):
        jid = "5512@s.whatsapp.net"
        app.hermes_pending[jid] = [("", [(b"ogg", "audio/ogg", "a.ogg")], "src", 43, "m-2", None)]
        ask = AsyncMock(return_value="")
        with patch.object(app, "HERMES_MESSAGE_DEBOUNCE_SECONDS", 0), patch.object(handover, "paused", AsyncMock(return_value=False)), \
                patch.object(app, "transcribe_audio_media", AsyncMock(return_value=["a senha é Casa2026 tá"])), \
                patch.object(app, "ask_hermes", ask), patch.object(app, "send_evolution", AsyncMock()), patch.object(app, "add_chatwoot_message", AsyncMock()), \
                patch.object(app, "brain_event", AsyncMock()), patch.object(sdr, "record", AsyncMock()), \
                patch.object(app, "record_offer_from_origin", AsyncMock()):
            await app.hermes_batch_worker(jid)
        self.assertNotIn("Casa2026", ask.await_args.args[0])


class ProfileEscalationTests(unittest.TestCase):
    """Installer lead with the Raio-X profile: record it and keep selling until the purchase."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = patch.object(sdr, "DB_PATH", Path(self.tmp.name) / "bridge.db")
        self.patch.start()
        sdr.remember_lead(51, "55@s.whatsapp.net", "Oi! Sou o @ana e quero o meu Time de IA instalado")

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def held(self, last_message="tenho 12 pessoas e faturo uns 300 mil"):
        parts = ["Com 12 pessoas, o time tira bastante coisa das suas mãos.", "Vou chamar o Talles por aqui."]
        directives = [{"type": "escalar", "motivo": "perfil para Raio-X", "frase": last_message}]
        return app.hold_profile_escalation(51, parts, directives, last_message)

    def test_before_the_purchase_the_profile_is_recorded_not_escalated(self):
        parts, directives = self.held()
        self.assertEqual(parts, ["Com 12 pessoas, o time tira bastante coisa das suas mãos."])
        self.assertEqual(directives, [{"type": "registro", "campo": "perfil_raiox", "valor": "sim"}])

    def test_a_blocked_reply_that_cites_the_raiox_still_escalates(self):
        directives = [{"type": "escalar", "motivo": "verificação automática: Raio-X ou Copiar a minha operação antes da compra da instalação", "frase": "x"}]
        self.assertEqual(app.hold_profile_escalation(51, [sdr.FALLBACK_REPLY], directives, "x"), ([sdr.FALLBACK_REPLY], directives))

    def test_after_the_purchase_or_when_he_asks_it_escalates(self):
        self.assertEqual(self.held("quero falar com o Talles sobre o raio-x")[1][0]["type"], "escalar")
        with sdr.connect() as c:
            c.execute("INSERT INTO sdr_records VALUES (?,?,?,?)", (51, "comprou", "sim", 1.0))
        self.assertEqual(self.held()[1][0]["type"], "escalar")


if __name__ == "__main__":
    unittest.main()
