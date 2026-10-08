"""Audit of SOUL v13 (06/10): each finding, and the 41 audit phrases, as tests.

Facts: OFERTA-ATUAL.md (sections 9 and 9.1 win) and hermes-sdr/ofertas.json.
"""
import asyncio
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.setdefault("SDR_BRAIN_TOKEN", "test")
os.environ.setdefault("SDR_BRAIN_DB", os.path.join(tempfile.gettempdir(), "sdr-brain-auditoria.db"))
import app  # noqa: E402
import oferta  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OFERTAS = {k: v for k, v in json.loads((ROOT / "hermes-sdr" / "ofertas.json").read_text(encoding="utf-8")).items() if k in oferta.OFFERS}
SOUL = (ROOT / "hermes-sdr" / "SOUL.md").read_text(encoding="utf-8").replace("\r\n", "\n")
RAIOX = SOUL.split("═══ CAMINHO DO RAIO-X ═══")[1].split("═══ COMO ESCALAR")[0]
I = {"oferta": "instalador", "ofertas": OFERTAS}
R = {"oferta": "raiox", "ofertas": OFERTAS}
U = {"ofertas": OFERTAS}
BOUGHT = {"oferta": "instalador", "ofertas": OFERTAS, "lead": {"registros": {"comprou": "sim"}}}

# (phrase, context, must be flagged): the audit script's 41 phrases.
AUDIT_PHRASES = [
    ("A instalação é R$ 47, pagamento único. Por fora ficam o seu servidor, na faixa de R$ 120 a R$ 200 por mês, e o Codex, cerca de R$ 100 por mês, pagos direto a eles, no seu nome. O caminho é por aqui https://instalador.talles.dev/antes. Consegue fazer hoje?", I, False),
    ("O caminho é por aqui https://instalador.talles.dev/antes", I, False),
    ("Ele trabalha a qualquer hora, 24 horas por dia, e não depende de contratar ninguém.", I, False),
    ("Apaga essa mensagem, por favor, e depois troca essa senha. Isso vai só no formulário cifrado, depois da compra.", I, False),
    ("Ela vai só no formulário cifrado, depois da compra, nunca por aqui; e a área avisa para você trocar a senha.", I, False),
    ("Isso eu não prometo. O que muda é responder cliente sair das suas mãos.", I, False),
    ("Gestão do time, quinzenal R$ 150, semanal R$ 450 ou diário R$ 1.300 por mês.", I, False),
    ("Atendimento no WhatsApp, R$ 3.000, único.", I, False),
    ("Não vou te prometer que você vai faturar mais. O que muda é o seu dia.", I, False),
    ("Não tem cupom nem desconto, é R$ 47 para todo mundo.", I, False),
    ("Desconto não tem, o valor é esse.", I, False),
    ("Pode me mandar a senha do servidor que eu adianto?", I, True),
    ("Me envia os dados do servidor por aqui que eu confiro.", I, True),
    ("Preciso do IP e da senha da VPS pra começar.", I, True),
    ("Me passa o token do bot?", I, True),
    ("Qual o IP do seu servidor?", I, True),
    ("Manda um print do painel da Hostinger com o acesso", I, True),
    ("Isso vai te ajudar a faturar mais já no primeiro mês.", I, True),
    ("O time aumenta suas vendas porque responde rápido.", I, True),
    ("Com R$ 47 isso se paga no primeiro cliente que você fechar.", I, True),
    ("Fica pronto em até 24 h depois do formulário.", I, True),
    ("Fica pronto em 1 dia depois do formulário.", I, True),
    ("Normalmente amanhã já está pronto.", I, True),
    ("Isso, depois da nº 50 vai para R$ 97.", I, True),  # the lead cited R$ 97 from an old ad
    ("Compra direto aqui: https://pay.kiwify.com.br/ju44Xqc", I, True),
    ("Contrata em hostinger.com.br, a KVM2.", I, True),
    ("Pelo seu tamanho, o Raio-X de R$ 12.000 faz mais sentido.", I, True),
    ("Tem o Copiar a minha operação, R$ 48.000.", I, True),
    ("Bom dia, Naia! Pare de contratar. Comece a implantar.", I, True),
    ("Pare de contratar. Comece a implantar.", I, True),
    ("A IA atua no lugar do Chefe.", I, True),
    ("Dá pra fazer R$ 100 mil nos próximos 30 dias.", I, True),
    ("O Rafael e a Juliana já usam e o Davi também.", I, True),
    ("Com o Raio-X você vai faturar o dobro.", R, True),
    ("Me passa a senha do seu servidor pra eu olhar.", R, True),
    ("Te dou 10% de desconto se fechar hoje.", R, True),
    ("O Raio-X é R$ 9.000.", R, True),
    ("Me passa a senha da VPS.", U, True),
    ("Você vai faturar mais com isso.", U, True),
    ("A instalação é R$ 27.", U, True),
    ("Nada de squads aqui.", I, True),
]


def check(text, context=I, lead=("",)):
    return oferta.check([text], context, list(lead))


class AuditPhrases(unittest.TestCase):
    def test_no_wrong_phrase_passes_and_no_right_phrase_is_blocked(self):
        self.assertEqual(len(AUDIT_PHRASES), 41)
        for text, context, flagged in AUDIT_PHRASES:
            lead = ["vi no anúncio que vai pra R$ 97"] if "R$ 97" in text else [""]
            self.assertEqual(bool(check(text, context, lead)), flagged, f"{text!r}: {check(text, context, lead)}")


class Finding01WhatsAppIsNotTheInstallation(unittest.TestCase):
    def test_the_check(self):
        self.assertTrue(any("WhatsApp" in i for i in check("Com o time instalado, ele responde os seus clientes no WhatsApp por você.")))
        self.assertTrue(any("WhatsApp" in i for i in check("Por R$ 47 o time atende seus clientes no zap.", U)))
        self.assertEqual(check("Atender os seus clientes no WhatsApp é o Atendimento no WhatsApp, R$ 3.000, separado; não vem nos R$ 47."), [])
        self.assertEqual(check("O time responde, escreve, organiza e lembra por você no Telegram."), [])

    def test_the_soul(self):
        equation = SOUL.split("A OFERTA PELA EQUAÇÃO DE VALOR")[1].split("O PREÇO (quando")[0]
        self.assertIn("Atendimento no WhatsApp", equation)
        self.assertIn("ANTES", equation)
        self.assertIn("(R$ 3.000)", equation)
        self.assertNotIn("studio.bela", SOUL)
        self.assertIn("I9.", app.prompt("revisor.md"))
        self.assertIn("não atende os clientes dele no WhatsApp", OFERTAS["instalador"]["o_que_nao_faz"])


class Finding02TwoProductsOf48k(unittest.TestCase):
    def test_names_are_separate_in_ofertas_and_soul(self):
        self.assertEqual(OFERTAS["raiox"]["implantacao"]["nome"], "Implantação do Raio-X")
        self.assertEqual(OFERTAS["raiox"]["copiar_a_minha_operacao"]["nome"], "Copiar a minha operação")
        self.assertIn("São DOIS produtos de R$ 48.000", SOUL)
        self.assertIn("X7.", app.prompt("revisor.md"))

    def test_the_swap_is_flagged(self):
        self.assertTrue(any("dois produtos" in i for i in check("O Copiar a minha operação são 21 dias, de 3 a 5 fluxos.", R)))
        self.assertTrue(any("dois produtos" in i for i in check("A implantação reproduz a operação do Talles no seu servidor.", R)))
        self.assertEqual(check("Resolver isso de ponta a ponta, de 3 a 5 fluxos, rodando em 21 dias, é a implantação, R$ 48.000.", R), [])


class Finding03ProfileBeforeThePurchase(unittest.TestCase):
    def test_soul_and_supervisor(self):
        escada = SOUL.split("A ESCADA (quando")[1].split("OBJEÇÕES DO INSTALADOR")[0]
        self.assertIn("[[REGISTRO: perfil_raiox = sim]]", escada)
        self.assertIn("Não escale por isso", escada)
        self.assertIn("`spiced.comprou` = sim", app.prompt("supervisor.md"))

    def test_supervisor_escalation_is_held_until_the_purchase(self):
        posted = []

        async def post(path, payload): posted.append(path)

        def run(records, lead_message="somos 12 e faturamos 300 mil"):
            posted.clear()
            with patch.object(app, "conversation_records", return_value=records), patch.object(app, "chatwoot_messages", AsyncMock(return_value=[])), \
                    patch.object(app, "ask_llm", AsyncMock(return_value={"guidance": None, "escalate": True, "motivo": "perfil para Raio-X", "frase": "x"})), \
                    patch.object(app, "bridge_post", post), patch.object(app.crm, "activity", AsyncMock()):
                asyncio.run(app.supervisor({"conversation_id": 901, "lead_message": lead_message}))
            return list(posted)

        self.assertEqual(run({"oferta": "instalador"}), ["/sdr/guidance"])
        self.assertEqual(run({"oferta": "instalador", "comprou": "sim"}), ["/sdr/escalate"])
        self.assertEqual(run({"oferta": "instalador"}, "quero falar com o Talles sobre o raio-x"), ["/sdr/escalate"])
        self.assertEqual(oferta.spiced_state({"comprou": "sim", "perfil_raiox": "sim"}, "instalador")["perfil_raiox"], "sim")


class Finding04ChecksForEveryOffer(unittest.TestCase):
    def test_raiox_and_unknown(self):
        for context in (R, U):
            self.assertTrue(check("Me passa a senha do servidor.", context))
            self.assertTrue(check("Você vai faturar o dobro.", context))
            self.assertTrue(check("Te faço um desconto.", context))
            self.assertTrue(check("É igual ao Denderson.", context))
        self.assertTrue(any("9.000" in i for i in check("O Raio-X é R$ 9.000.", R)))
        self.assertEqual(check("O Raio-X é R$ 12.000; um dev pleno custa R$ 12 a 18 mil por mês.", R), [])

    def test_raiox_section_of_the_soul_only_quotes_real_values(self):
        self.assertEqual(oferta.amounts(RAIOX) - oferta.offer_amounts(OFERTAS, "raiox"), set())


class Finding05GapsAndNegation(unittest.TestCase):
    def test_negation_passes(self):
        for text in ("Não vou te prometer que você vai faturar mais.", "Não me mande a senha por aqui.",
                     "Você vai informar o IP no formulário cifrado, depois da compra."):
            self.assertEqual(check(text), [], text)

    def test_raiox_price_in_installer_only_after_the_purchase(self):
        self.assertTrue(check("O Raio-X é R$ 12.000."))
        self.assertEqual(check("O Raio-X é R$ 12.000.", BOUGHT), [])


class Finding06OnlyOfferValues(unittest.TestCase):
    def test_lead_value_echoed_as_price_is_flagged_but_his_own_cost_passes(self):
        self.assertTrue(check("Isso, depois da nº 50 vai para R$ 97.", I, ["vi que depois da 50 vai pra R$ 97"]))
        self.assertTrue(check("Você disse R$ 97, e é isso mesmo.", I, ["vi que vai pra R$ 97"]))
        self.assertEqual(check("Você me disse que paga R$ 2.000 pra sua secretária.", I, ["pago uns R$ 2 mil pra ela"]), [])

    def test_soul_answer_for_old_ads(self):
        self.assertIn("o preço hoje é R$ 47 e o prazo é até 48 h", SOUL)


class Finding08NoResale(unittest.TestCase):
    def test_wording(self):
        for text in (SOUL, json.dumps(OFERTAS, ensure_ascii=False)):
            self.assertNotIn("revende", text.lower())
        self.assertIn("não vende o servidor nem o Codex; a Conta do Gemini é opcional na compra", OFERTAS["instalador"]["regras"])
        self.assertIn("Não vende o servidor nem o Codex", SOUL)


class Finding09NoCompetitorBenefitLine(unittest.TestCase):
    def test_removed(self):
        self.assertNotIn("24 horas por dia", SOUL)
        self.assertNotIn("não depende de", SOUL)


class Finding10TriageLabels(unittest.TestCase):
    def test_own_words(self):
        self.assertNotIn("quem vende conhecimento", SOUL)


class Finding11OneForbiddenList(unittest.TestCase):
    def test_every_prompt_shows_the_same_list(self):
        listed = oferta.forbidden_list()
        for name in ("revisor.md", "fup.md"):
            self.assertIn("{{PROIBIDOS}}", (Path(app.BASE_DIR) / "prompts" / name).read_text(encoding="utf-8"))
            self.assertIn(listed, app.prompt(name))
            self.assertNotIn("{{", app.prompt(name))
        self.assertIn(oferta.soul_line(), SOUL)  # python oferta.py soul ../hermes-sdr/SOUL.md
        for item in ("Naia", "Squad", "Avalanche", "Bom dia, Naia", "Pare de contratar", "no lugar do Chefe", "Rafael", "Juliana", "Davi", "Paulo", "Jonathan"):
            self.assertIn(item, listed)

    def test_a_lead_named_paulo_is_not_the_competitor(self):
        self.assertTrue(check("O Paulo já usa."))
        self.assertEqual(check("Oi, Paulo! Sou o agente do Talles.", I, ["oi, aqui é o Paulo"]), [])


class Finding12MonthlyCost(unittest.TestCase):
    def test_gemini_buyer_pays_only_the_vps(self):
        price = SOUL.split("O PREÇO (sempre")[1].split("O FECHAMENTO")[0]
        gemini = price.split("Quem vai levar a Conta do Gemini")[1].split("Quem já disse que tem o Codex")[0]
        self.assertIn("paga por mês só o\nservidor", gemini)
        self.assertNotIn("R$ 100 por mês", gemini)
        self.assertIn("não cite o Codex", gemini)
        self.assertIn("quem vai levar a Conta do Gemini paga por mês só a VPS", app.prompt("revisor.md"))
        self.assertIn("com_conta_do_gemini", OFERTAS["instalador"]["custo_mensal"])


class Finding13OnlyEightGB(unittest.TestCase):
    def test_no_4gb(self):
        installer = SOUL.split("═══ CAMINHO DO INSTALADOR ═══")[1].split("═══ CAMINHO DO RAIO-X ═══")[0]
        for text in (installer, json.dumps(OFERTAS["instalador"], ensure_ascii=False)):
            self.assertNotIn("4 GB", text)
            self.assertNotIn("módulo", text)  # the Copiar's "núcleo e módulos" is another product
        self.assertNotIn("4 GB", SOUL)


class Finding14NoVideo(unittest.TestCase):
    def test_check_and_soul(self):
        self.assertTrue(check("Te mando o vídeo de como contratar a VPS."))
        self.assertTrue(check("Tem um vídeo que mostra o passo a passo.", U))
        self.assertEqual(check("Hoje não há vídeo para mostrar."), [])
        self.assertEqual(check("No dia 6, a prova: vídeo do fluxo rodando.", R), [])
        self.assertIn('"Como eu contrato?": o caminho curto', SOUL)
        self.assertIn("como_contratar", OFERTAS["instalador"])


class Finding15Slots(unittest.TestCase):
    def test_vagas_total(self):
        self.assertNotIn("4 vagas", SOUL)
        self.assertNotIn("são 4;", SOUL)
        self.assertIn("capacidade.vagas_total", SOUL)


class Finding16NoOfferStartsWithTheInstaller(unittest.TestCase):
    def test_soul(self):
        self.assertIn("Sem `oferta`, comece pelo CAMINHO DO INSTALADOR", SOUL)
        self.assertNotIn("Você quer o seu time de IA instalado, ou quer que", SOUL)

    def test_review_takes_the_offer_the_draft_records(self):
        seen = []

        async def llm(instruction, **kwargs):
            seen.append(instruction); return {"decision": "aprovar"}

        with patch.object(app, "ask_llm", new=llm):
            asyncio.run(app.run_review({"draft_parts": ["Pelo seu caso, o Raio-X é R$ 12.000."], "lead_message": "quero o raio-x",
                                        "directives": [{"type": "registro", "campo": "oferta", "valor": "raiox"}],
                                        "context": {"ofertas": OFERTAS}, "transcript": []}))
        self.assertEqual(json.loads(seen[0].split("\nDADOS:\n", 1)[1])["oferta"], "raiox")


class Finding17NoContactPromise(unittest.TestCase):
    def test_check_and_soul(self):
        self.assertTrue(check("Combinado, te chamo na sexta pra ver se deu certo."))
        self.assertTrue(check("Te procuro amanhã.", R))
        self.assertEqual(check("Combinado. Fica à vontade para me chamar quando contratar a VPS."), [])
        self.assertEqual(check("Vou chamar o Talles e ele te responde por aqui."), [])
        self.assertNotIn("te chamo [dia]", SOUL)
        self.assertIn("fica à vontade para me chamar quando", SOUL)


class Finding18Closing(unittest.TestCase):
    def test_exceptions(self):
        # TSX-78 (07/10): the price turn no longer ends on the price; it carries the link and the next step.
        revisor = app.prompt("revisor.md")
        self.assertIn("o turno do PREÇO sai COM o link https://instalador.talles.dev/antes", revisor)
        self.assertIn("o turno do link leva JUNTOS o exemplo do caso do lead, o preço", revisor)
        self.assertNotIn("Este turno NÃO termina em pergunta", SOUL)
        self.assertNotIn("não acrescente pergunta", revisor)


INSTALLER = SOUL.split("═══ CAMINHO DO INSTALADOR ═══")[1].split("═══ CAMINHO DO RAIO-X ═══")[0]


class Tsx77BuySignalSkipsDiscovery(unittest.TestCase):
    """Conversa 16 (07/10): the hot lead never got the link."""

    def test_soul_buy_signal(self):
        signal = INSTALLER.split("O SINAL DE COMPRA (vale")[1].split("A ABERTURA")[0]
        for text in ("será que seria meu caso?", "quanto custa?", "NÃO volte à descoberta", "crie 10\n      jogos de vocabulário A2",
                     "O preço (O PREÇO)", "a ÚNICA pergunta"):
            self.assertIn(text, signal)
        self.assertIn("no máximo UMA pergunta antes do link", SOUL)
        self.assertNotIn("S, P e D (com VPS e Codex) antes do link", SOUL)

    def test_soul_price_always_with_link(self):
        price = INSTALLER.split("O PREÇO (sempre junto com o link e o próximo passo)")[1].split("O FECHAMENTO")[0]
        self.assertIn("O preço nunca sai sozinho", price)
        self.assertIn("https://instalador.talles.dev/antes", price)
        self.assertIn("Consegue\nfazer hoje?", price)

    def test_soul_no_way_out_reactions_and_second_person(self):
        self.assertIn('antes de o link ter saído, nunca oferece saída', SOUL)
        self.assertIn("REAÇÃO NÃO É RESPOSTA", SOUL)
        self.assertIn('Você fala COM o lead', SOUL)

    def test_soul_server_is_value_not_triage(self):
        self.assertIn("O SERVIDOR (VPS) é valor, não triagem", INSTALLER)
        for text in ("trabalha mesmo com o\n  computador desligado", "R$ 120 a R$ 200 por mês", "vários agentes", "KVM 8 da Hostinger"):
            self.assertIn(text, INSTALLER)
        for wrong in ("KVM2", "KVM 2", "119"):
            self.assertNotIn(wrong, SOUL)
            self.assertNotIn(wrong, json.dumps(OFERTAS, ensure_ascii=False))
        for name in ("revisor.md", "fup.md", "supervisor.md"):  # the reviser names KVM2 only to forbid it
            self.assertNotIn("119", app.prompt(name))
            self.assertNotIn("a KVM2 da Hostinger", app.prompt(name))
        self.assertIn("nunca outro plano (KVM2, KVM 2)", app.prompt("revisor.md"))
        self.assertIn("1 Ano de Tokens", INSTALLER)

    def test_prompts(self):
        revisor, fup, supervisor = app.prompt("revisor.md"), app.prompt("fup.md"), app.prompt("supervisor.md")
        for rule in ("I1. SINAL DE COMPRA PULA A DESCOBERTA", "C14. FALA COM O LEAD", "C15. SEM SAÍDA ANTES DO LINK", 'C16. REAÇÃO NÃO É "SIM"',
                     "A REESCRITA FALA COM O LEAD"):
            self.assertIn(rule, revisor)
        self.assertIn("o toque É o link", fup)
        self.assertIn("Nunca oriente mais descoberta depois de sinal de compra", supervisor)
        self.assertIn("não é \"sim\"", supervisor)


class Tsx78PriceCtaAndThirdPerson(unittest.TestCase):
    PRICE = "A instalação é R$ 47, pagamento único. Por fora fica só o seu servidor, na faixa de R$ 120 a R$ 200 por mês."

    def test_price_without_link_is_detected(self):
        self.assertTrue(oferta.price_without_link([self.PRICE], I))
        self.assertTrue(oferta.price_without_link(["O time sai por R$ 47."], U))
        self.assertFalse(oferta.price_without_link([self.PRICE + " " + oferta.PRICE_CTA], I))
        self.assertFalse(oferta.price_without_link(["Não vem nos R$ 47: é o Atendimento no WhatsApp, R$ 3.000."], I))
        self.assertFalse(oferta.price_without_link([self.PRICE], BOUGHT))
        self.assertFalse(oferta.price_without_link([self.PRICE], R))

    def test_cta_is_added_as_a_message_or_to_the_last_one(self):
        self.assertEqual(oferta.with_price_cta([self.PRICE]), [self.PRICE, oferta.PRICE_CTA])
        three = ["Exemplo.", "Preço R$ 47, pagamento único.", "Faz sentido pro seu caso? [[REGISTRO: preco_dado = sim]]"]
        fixed = oferta.with_price_cta(three)
        self.assertEqual(len(fixed), 3)
        self.assertIn(oferta.PRICE_CTA, fixed[2])
        self.assertTrue(fixed[2].endswith("[[REGISTRO: preco_dado = sim]]"))
        self.assertEqual(oferta.with_price_cta(["Toque."], toque=True), ["Toque. " + oferta.PRICE_CTA])

    def test_review_adds_the_link_when_the_model_approves_or_is_down(self):
        for verdict in ({"decision": "aprovar"}, None,
                        {"decision": "reescrever", "parts": ["A instalação é R$ 47, pagamento único. Por fora fica só o seu servidor, na faixa de R$ 120 a R$ 200 por mês."], "motivo": "C8"}):
            with patch.object(app, "ask_llm", AsyncMock(return_value=verdict)):
                result = asyncio.run(app.run_review({"draft_parts": [self.PRICE], "lead_message": "quanto custa?", "context": I, "transcript": []}))
            self.assertEqual(result["decision"], "reescrever", verdict)
            self.assertIn("https://instalador.talles.dev/antes", " ".join(result["parts"]))
            self.assertTrue(re.sub(r"\s*\[\[.*?\]\]", "", result["parts"][-1]).endswith("?"))

    def test_toque_gets_the_link_in_its_only_message(self):
        with patch.object(app, "ask_llm", AsyncMock(return_value={"decision": "aprovar"})):
            result = asyncio.run(app.run_review({"tipo": "toque", "draft_parts": [self.PRICE], "lead_message": "", "context": I, "transcript": []}))
        self.assertEqual(len(result["parts"]), 1)
        self.assertIn(oferta.PRICE_CTA, result["parts"][0])

    def test_reviewer_sees_the_cta_issue(self):
        seen = []

        async def llm(instruction, **kwargs):
            seen.append(instruction); return {"decision": "aprovar"}

        with patch.object(app, "ask_llm", new=llm):
            asyncio.run(app.run_review({"draft_parts": [self.PRICE], "lead_message": "quanto custa?", "context": I, "transcript": []}))
        self.assertIn(app.PRICE_WITHOUT_LINK, json.loads(seen[0].split("\nDADOS:\n", 1)[1])["verificacao_automatica"])

    def test_third_person_is_flagged(self):
        # Conversa 16, 20:47: "fica só a VPS direto pra empresa dela".
        self.assertTrue(any("3ª pessoa" in i for i in check("Por fora fica só o servidor, direto pra empresa dela.")))
        self.assertTrue(any("3ª pessoa" in i for i in check("Mando o link do lead agora.", U)))
        self.assertEqual(check("Por fora fica só o seu servidor, no seu nome."), [])
        self.assertEqual(check("Pergunta pro seu sócio o que ele acha da agenda dele.", I, ["meu sócio cuida da agenda dele"]), [])
        bad = {"decision": "reescrever", "parts": ["Fica só o servidor, no nome dela."], "motivo": "x"}
        with patch.object(app, "ask_llm", AsyncMock(return_value=bad)):
            result = asyncio.run(app.run_review({"draft_parts": ["Fica direto pra empresa dela."], "lead_message": "ok", "context": I, "transcript": []}))
        self.assertEqual(result["decision"], "bloquear")

    def test_way_out_before_the_link(self):
        # Conversa 16, 20:55: "Te passo o link… ou prefere olhar em outro momento?"
        self.assertTrue(any("outro momento" in i for i in check("Te passo o link, ou prefere olhar em outro momento?")))
        self.assertTrue(any("outro momento" in i for i in check("Fica à vontade pra me chamar quando puder.", U)))
        self.assertEqual(check("O caminho é por aqui https://instalador.talles.dev/antes. Consegue hoje, ou fica para outro dia?"), [])
        sent = ["O caminho é por aqui https://instalador.talles.dev/antes. Consegue fazer hoje?"]
        self.assertEqual(oferta.check(["Sem problema, fica para outro dia?"], I, [""], sent), [])
        linked = {**I, "lead": {"registros": {"link_enviado": "sim"}}}
        self.assertEqual(check("Sem problema, fica para outro dia?", linked), [])
        self.assertEqual(check("Faz sentido seguir agora, ou prefere outro momento?", R), [])
        self.assertEqual(check("Combinado. Fica à vontade para me chamar quando contratar a VPS."), [])
        self.assertEqual(check("Conseguiu contratar a VPS ontem, ou ficou pra outro dia?"), [])  # his own step's date, not a way out

    def test_link_record_follows_what_the_lead_receives(self):
        # Simulation 07/10 (quente-reacao): the reviser dropped price and link, but the draft's link_enviado = sim stayed.
        directives = [{"type": "registro", "campo": "preco_dado", "valor": "sim"}, {"type": "registro", "campo": "link_enviado", "valor": "sim"},
                      {"type": "registro", "campo": "proximo_passo", "valor": "comprar pelo link"}]
        dropped = {"decision": "reescrever", "parts": ["O que você faz hoje? Te digo como fica no seu caso."], "motivo": "C16"}
        with patch.object(app, "ask_llm", AsyncMock(return_value=dropped)):
            result = asyncio.run(app.run_review({"draft_parts": [self.PRICE + " " + oferta.PRICE_CTA], "directives": directives,
                                                 "lead_message": "[Reação recebida: ❤️ na mensagem X]", "context": I, "transcript": []}))
        self.assertIn("[[REGISTRO: proximo_passo = comprar pelo link]]", result["parts"][-1])
        self.assertNotIn("link_enviado", result["parts"][-1])
        self.assertNotIn("preco_dado", result["parts"][-1])
        # The link the code adds is recorded.
        with patch.object(app, "ask_llm", AsyncMock(return_value={"decision": "aprovar"})):
            result = asyncio.run(app.run_review({"draft_parts": [self.PRICE], "directives": [{"type": "registro", "campo": "oferta", "valor": "instalador"}],
                                                 "lead_message": "quanto custa?", "context": I, "transcript": []}))
        self.assertIn("[[REGISTRO: link_enviado = sim]]", result["parts"][-1])
        self.assertIn("[[REGISTRO: oferta = instalador]]", result["parts"][-1])
        # Nothing to fix: the rewrite goes as the reviewer wrote it.
        same = {"decision": "reescrever", "parts": ["Texto sem link. Faz sentido?"], "motivo": "x"}
        self.assertEqual(app.reconcile_link_record(same, [{"type": "registro", "campo": "dor", "valor": "x"}]), same)

    def test_the_link_host_is_not_a_deadline(self):
        # Simulation 07/10 (quente-pergunta-preco): blocked as "prazo errado" because of "amanhã … instalador.talles.dev".
        self.assertEqual(check("Combinado! O link fica aqui pra quando você abrir amanhã cedo: https://instalador.talles.dev/antes"), [])
        self.assertTrue(check("Amanhã já fica instalado."))

    def test_bare_ai_name_is_flagged_before_the_bridge_blocks_it(self):
        # Simulation 07/10 (frio-curioso): "Como você já assina o ChatGPT…" would be blocked and escalated by the bridge.
        self.assertTrue(any("IA solto" in i for i in check("Como você já assina o ChatGPT, não tem custo novo.")))
        self.assertTrue(any("IA solto" in i for i in check("Funciona com o Gemini também.", U)))
        for ok in ("O Codex é o plano pago do ChatGPT que você já paga.", "Se você tem o ChatGPT Plus, já tem o Codex.",
                   "Sem Codex, dá para levar a Conta do Gemini junto na compra."):
            self.assertEqual(check(ok), [], ok)
        self.assertIn("nunca o nome solto", app.prompt("revisor.md"))
        self.assertIn('nunca "o ChatGPT" sozinho', SOUL)

    def test_capacity_escalation_is_not_replaced_by_the_anchor(self):
        # Simulation 07/10 (marina): the reviser swapped "Deixa eu confirmar a agenda" for the R$ 48.000 anchor.
        self.assertIn("X2b.", app.prompt("revisor.md"))
        self.assertIn("nunca troque a escalação por âncora", app.prompt("revisor.md"))

    def test_cold_curiosity_is_not_a_buy_signal(self):
        self.assertIn("NÃO é sinal de compra a curiosidade de quem chegou frio", SOUL)
        self.assertIn("Curiosidade de quem chegou frio", app.prompt("revisor.md"))

    def test_gemini_checkout_name_is_not_a_duration_promise(self):
        self.assertEqual(check('Na compra, a Conta do Gemini aparece como "1 Ano de Tokens", R$ 100, uma vez.'), [])
        self.assertTrue(check("A Conta do Gemini dura 1 ano."))


class ToConfirm(unittest.TestCase):
    def test_credentials_never_reach_the_models(self):
        text, found = oferta.redact_credentials("ip 203.0.113.7 senha: Segredo#1")
        self.assertTrue(found)
        self.assertNotIn("Segredo#1", text); self.assertNotIn("203.0.113.7", text)
        rows = app.compact_transcript([{"message_type": 0, "content": "a senha é Casa2026", "created_at": 1},
                                       {"message_type": 1, "content": "Apaga essa mensagem, por favor.", "created_at": 2}])
        self.assertEqual(rows[0]["texto"], "a senha é [credencial removida]")
        self.assertIn("[credencial removida]", SOUL)

    def test_refund_in_48h_is_in_oferta_atual(self):
        # OFERTA-ATUAL.md §3: "Para pedir: botão em /app/garantia, com reembolso em até 48 h (SPEC:443-445)". It stays.
        self.assertIn("reembolso em até 48 h", (ROOT / "OFERTA-ATUAL.md").read_text(encoding="utf-8"))
        self.assertIn("reembolso em até 48 h", OFERTAS["instalador"]["garantia"])

    def test_gemini_duration_is_never_promised(self):
        self.assertTrue(check("A Conta do Gemini é sua para sempre."))
        self.assertTrue(check("A Conta do Gemini vale por 12 meses.", U))
        self.assertIn("não promete por quanto tempo a conta dura", OFERTAS["instalador"]["bumps"][0]["nota"])
        self.assertIn("Não prometa por quanto tempo a Conta do", SOUL)

    def test_raiox_case_numbers_are_not_installer_proof(self):
        proof = "o Talles cuidou de um SaaS com 30 mil usuários e 18 mil agentes"
        self.assertTrue(check(proof))
        self.assertTrue(check(proof, U))
        self.assertEqual(check(proof, R), [])
        self.assertIn("os números do Raio-X NÃO entram", SOUL)

    def test_raiox_spiced_order_and_opening_agree(self):
        opening = "O que trava na sua operação quando você fica uma semana fora?"
        spiced = SOUL.split("═══ SPICED")[1].split("TRIAGEM")[0]
        self.assertIn("No Raio-X, a abertura testada já é a\npergunta de P", spiced)
        self.assertIn(opening, SOUL.split("P, DOR")[1].split("I, IMPACTO")[0])
        self.assertIn(opening, SOUL.split("═══ COMO SOA")[1])
        self.assertIn(opening, app.prompt("revisor.md"))
        self.assertIn("abertura (\"o que trava…\") → triagem", app.prompt("fup.md"))


class EntryStepForDisqualifiedRaiox(unittest.TestCase):
    """Decisão do Talles (06/10): o desqualificado do Raio-X pode ouvir a instalação de R$ 47."""
    PRICE = "A instalação é R$ 47, pagamento único. Por fora fica só o seu servidor, na faixa de R$ 120 a R$ 200 por mês."

    def test_qualified_raiox_lead_still_cannot_hear_installer_prices(self):
        self.assertTrue(oferta.check([self.PRICE], R, []))

    def test_disqualified_raiox_lead_can_hear_the_installation(self):
        ctx = {**R, "lead": {"registros": {"triagem": "desqualificado"}}}
        self.assertEqual(oferta.check([self.PRICE], ctx, []), [])

    def test_disqualified_raiox_lead_cannot_hear_upper_steps(self):
        ctx = {**R, "lead": {"registros": {"triagem": "desqualificado"}}}
        self.assertTrue(oferta.check(["O Atendimento no WhatsApp custa R$ 9.999."], ctx, []))


if __name__ == "__main__":
    unittest.main(verbosity=2)
