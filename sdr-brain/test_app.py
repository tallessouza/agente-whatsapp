import asyncio
from datetime import datetime
import json
from contextlib import closing
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ["SDR_BRAIN_TOKEN"] = "test"
os.environ["SDR_BRAIN_DB"] = os.path.join(tempfile.gettempdir(), "sdr-brain-acceptance.db")
try: os.unlink(os.environ["SDR_BRAIN_DB"])
except FileNotFoundError: pass
from fastapi.testclient import TestClient
import app


class FakeHTTP:
    def __init__(self, *args, **kwargs): self.posts = []
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def get(self, url, **kwargs):
        class R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return {"last_agent_ts": app.tracked.get(77, {}).get("last_agent_ts", 1), "last_lead_ts": 0, "lead": {"registros": {}}}
        return R()
    async def post(self, url, **kwargs):
        class R:
            def raise_for_status(self): pass
            def json(self): return {"choices": [{"message": {"content": '{"decision":"aprovar"}'}}]}
        return R()


class Acceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app.app)

    def headers(self): return {"Authorization": "Bearer test"}

    def test_health_without_auth_and_auth_503_401_all_protected(self):
        self.assertEqual(self.client.get("/health").status_code, 200)
        for route, body in [("/review", {"draft_parts": []}), ("/events/exchange", {"conversation_id": 1}), ("/events/lead", {"conversation_id": 1}), ("/events/record", {"conversation_id": 1, "campo": "x", "valor": "y"})]:
            self.assertEqual(self.client.post(route, json=body).status_code, 401)
        old = os.environ.pop("SDR_BRAIN_TOKEN")
        try:
            for route, body in [("/review", {}), ("/events/exchange", {"conversation_id": 1}), ("/events/lead", {"conversation_id": 1}), ("/events/record", {"conversation_id": 1})]:
                self.assertEqual(self.client.post(route, json=body).status_code, 503)
        finally: os.environ["SDR_BRAIN_TOKEN"] = old

    def test_review_decisions_fallback_directives_and_parts(self):
        with patch.object(app, "ask_llm", side_effect=[{"decision": "aprovar"}, {"decision": "reescrever", "parts": ["nova"]}, {"decision": "bloquear", "motivo": "sigilo"}, None, {"decision": "reescrever", "parts": ["a", "b", "c", "d"]}]):
            self.assertEqual(self.client.post("/review", headers=self.headers(), json={"draft_parts": ["oi [[REGISTRO: dor = x]]"]}).json()["decision"], "aprovar")
            rewritten = self.client.post("/review", headers=self.headers(), json={"draft_parts": ["oi [[REGISTRO: dor = x]]"]}).json()
            self.assertIn("[[REGISTRO: dor = x]]", rewritten["parts"][0])
            self.assertEqual(self.client.post("/review", headers=self.headers(), json={}).json()["decision"], "bloquear")
            self.assertEqual(self.client.post("/review", headers=self.headers(), content=b"{").json()["motivo"], "review_unavailable")
            self.assertEqual(self.client.post("/review", headers=self.headers(), json={}).json()["motivo"], "review_unavailable")


    def test_review_timeout_fallback(self):
        class TimeoutHTTP:
            def __init__(self, *args, **kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def post(self, *args, **kwargs): raise TimeoutError("timeout")
        with patch.object(app.httpx, "AsyncClient", TimeoutHTTP):
            result = self.client.post("/review", headers=self.headers(), json={}).json()
            self.assertEqual(result, {"decision": "aprovar", "motivo": "review_unavailable"})

    def test_supervisor_guidance_and_escalation(self):
        app.CHATWOOT_ACCOUNT_ID = "1"; app.CHATWOOT_API_TOKEN = "x"
        with patch.object(app, "chatwoot_messages", new=AsyncMock(return_value=[{"content": "quero pessoa"}])), patch.object(app, "ask_llm", new=AsyncMock(return_value={"guidance": "pergunte", "escalate": True, "motivo": "pedido", "frase": "quero pessoa"})), patch.object(app, "bridge_post", new=AsyncMock()) as post:
            asyncio.run(app.supervisor({"conversation_id": 9}))
            self.assertEqual(post.await_count, 2)
            self.assertEqual(post.await_args_list[0].args[0], "/sdr/guidance")
            self.assertEqual(post.await_args_list[1].args[0], "/sdr/escalate")

    def fake_psycopg(self, rows_by_query):
        """psycopg stand-in: returns rows by the first table-ish marker in the SQL."""
        executed = []

        class Cursor:
            def execute(self, query, args):
                self.query = query
                executed.append((query, args))
            def fetchall(self):
                for marker, rows in rows_by_query.items():
                    if marker in self.query:
                        return rows
                return []
            def __enter__(self): return self
            def __exit__(self, *args): pass

        class Conn:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def cursor(self): return Cursor()

        return type("Psycopg", (), {"connect": staticmethod(lambda dsn: Conn())}), executed

    def test_enrichment_from_prefilled_handle_uses_quoted_sql(self):
        history = [("raiox", "2026-09-27 10:00", "raiox", "179", "https://instagram.com/p/1", "raiox")]
        fake, executed = self.fake_psycopg({"a.name": history})
        with patch.dict("sys.modules", {"psycopg": fake}), patch.dict(os.environ, {"OPENREPLY_DSN": "postgres://x"}), \
                patch.object(app, "bridge_post", new=AsyncMock()) as post, patch.object(app, "chatwoot_contact_name", new=AsyncMock(return_value="")), \
                patch.object(app.enrichment, "profile_lookup", new=AsyncMock(return_value={"bio": "mentora de social media", "ultimos_posts": []})):
            asyncio.run(app.enrich({"conversation_id": 4, "origin": {"instagram": "@Acme"}, "ts": 1790600400}))
        ficha = post.await_args.args[1]["profile"]
        self.assertEqual(ficha["origem_instagram"], {"status": "confirmado", "metodo": "texto_do_link"})
        self.assertEqual(ficha["instagram"], "@acme")
        self.assertEqual(ficha["campanha_instagram"]["palavra"], "raiox")
        self.assertEqual(ficha["perfil"]["bio"], "mentora de social media")
        self.assertIn('"DmLog"', executed[0][0])

    def test_window_match_by_name_and_ambiguity(self):
        e = app.enrichment
        two = [{"handle": "marina.escala", "igsid": "1", "sent": 0}, {"handle": "joao_lojas", "igsid": "2", "sent": 0}]
        no = lambda h: False
        self.assertEqual(e.resolve_identity(prefilled_handle="", typed_handle="", display_name="Marina Duarte", candidates=two, in_campaign=no)["status"], "confirmado")
        self.assertEqual(e.resolve_identity(prefilled_handle="", typed_handle="", display_name="Carla", candidates=two, in_campaign=no)["status"], "ambiguo")
        self.assertEqual(e.resolve_identity(prefilled_handle="", typed_handle="", display_name="Carla", candidates=two[:1], in_campaign=no)["status"], "provavel")
        self.assertEqual(e.resolve_identity(prefilled_handle="", typed_handle="", display_name="Carla", candidates=[], in_campaign=no)["status"], "direto")
        typed = e.resolve_identity(prefilled_handle="", typed_handle="loja.x", display_name="", candidates=[], in_campaign=lambda h: h == "loja.x")
        self.assertEqual((typed["status"], typed["method"]), ("confirmado", "lead_informou"))
        self.assertEqual(e.resolve_identity(prefilled_handle="", typed_handle="outra", display_name="", candidates=[], in_campaign=no)["status"], "informado")
        self.assertEqual(e.normalize_handle("@there"), "")
        self.assertTrue(e.name_matches_handle("Marina Duarte", "marina.escala"))
        self.assertFalse(e.name_matches_handle("Ana", "marina.escala"))

    def test_click_beats_dm_window(self):
        e = app.enrichment
        no = lambda h: False
        cands = [{"handle": "marina.escala", "igsid": "1", "sent": 0, "source": "clique"},
                 {"handle": "joao_lojas", "igsid": "2", "sent": 0, "source": "dm"},
                 {"handle": "ana.x", "igsid": "3", "sent": 0, "source": "dm"}]
        r = e.resolve_identity(prefilled_handle="", typed_handle="", display_name="Carla", candidates=cands, in_campaign=no)
        self.assertEqual((r["username"], r["status"], r["method"]), ("marina.escala", "confirmado", "clique"))
        two_clicks = [dict(cands[0]), {"handle": "ana.x", "igsid": "3", "sent": 0, "source": "clique"}]
        self.assertEqual(e.resolve_identity(prefilled_handle="", typed_handle="", display_name="Carla", candidates=two_clicks, in_campaign=no)["status"], "ambiguo")
        r = e.resolve_identity(prefilled_handle="", typed_handle="", display_name="Ana Paula", candidates=two_clicks, in_campaign=no)
        self.assertEqual((r["username"], r["method"]), ("ana.x", "clique+nome"))

    def test_unconfirmed_identity_never_reaches_the_agent(self):
        window = [("marina.escala", "1", datetime(2026, 9, 28, 13, 0))]
        fake, _ = self.fake_psycopg({'"DmLog" d WHERE d.status': window})
        with patch.dict("sys.modules", {"psycopg": fake}), patch.dict(os.environ, {"OPENREPLY_DSN": "postgres://x"}), \
                patch.object(app, "bridge_post", new=AsyncMock()) as post, patch.object(app, "chatwoot_contact_name", new=AsyncMock(return_value="Carla")), \
                patch.object(app.enrichment, "profile_lookup", new=AsyncMock(return_value=None)):
            asyncio.run(app.enrich({"conversation_id": 5, "origin": None, "ts": 1790600400}))
        ficha = post.await_args.args[1]["profile"]
        self.assertEqual(ficha["origem_instagram"]["status"], "provavel")
        self.assertNotIn("instagram", ficha)
        self.assertNotIn("marina", json.dumps(ficha))

    def test_profile_sources_disabled_without_tokens(self):
        for var in ("META_GRAPH_TOKEN", "IG_BUSINESS_ID", "APIFY_TOKEN"):
            os.environ.pop(var, None)
        self.assertIsNone(asyncio.run(app.enrichment.business_discovery("empresa")))
        self.assertIsNone(asyncio.run(app.enrichment.apify_profile("empresa")))

    def run_followups(self, now, bridge_state):
        """Run one follow-up pass against a mocked bridge; return posted stages."""
        posted = []

        async def llm(_, **kwargs):
            return {"disparar": True, "texto": "Você falou que tudo para quando sai. Faz sentido olhar isso esta semana, ou o momento é outro?", "motivo": "dor"}

        async def post(path, payload):
            posted.append(payload["stage"])

        class Bridge(FakeHTTP):
            async def get(self, url, **kwargs):
                class R:
                    status_code = 200
                    def raise_for_status(self): pass
                    def json(self): return bridge_state
                return R()

        with patch.object(app, "ask_llm", new=llm), patch.object(app, "bridge_post", new=post), \
                patch.object(app, "chatwoot_messages", new=AsyncMock(return_value=[])), patch.object(app.httpx, "AsyncClient", Bridge):
            asyncio.run(app.followup_once(now=now))
        return posted

    def test_followup_decides_only_latest_stage_once_per_sequence(self):
        # 2026-09-28 10:00 Brasília (13:00 UTC)
        anchor = 1790600400.0
        app.tracked.clear()
        app.tracked[77] = {"jid": "j", "last_agent_ts": anchor}
        state = {"last_agent_ts": anchor, "last_lead_ts": anchor - 60, "lead": {"registros": {}}}
        self.assertEqual(self.run_followups(anchor + 200, state), [])
        self.assertEqual(self.run_followups(anchor + 400, state), ["5min"])
        self.assertEqual(self.run_followups(anchor + 500, state), [])  # same stage, once
        # downtime: at 2h10 only the latest reached checkpoint is decided
        self.assertEqual(self.run_followups(anchor + 7800, state), ["2h"])

    def test_touch_goes_through_the_reviewer(self):
        anchor = 1790600400.0
        state = {"last_agent_ts": anchor, "last_lead_ts": anchor - 60, "lead": {"registros": {}}, "context": {"capacidade": {"status": "ok"}}}
        for verdict, expected in (({"decision": "reescrever", "parts": ["Texto do revisor. Faz sentido, ou o momento é outro?"]}, "Texto do revisor. Faz sentido, ou o momento é outro?"),
                                  ({"decision": "bloquear", "motivo": "regra 1"}, None)):
            app.tracked.clear(); app.tracked[77] = {"jid": "j", "last_agent_ts": anchor}
            with closing(app.connection()) as conn:
                conn.execute("DELETE FROM decisions"); conn.execute("DELETE FROM sequences"); conn.commit()
            calls, sent = [], []

            async def llm(instruction, **kwargs):
                calls.append(instruction)
                if len(calls) == 1:
                    return {"disparar": True, "texto": "A gente corta seu gasto. Bora?", "motivo": "dor"}
                self.assertIn('"tipo": "toque"', instruction)
                self.assertIn('"capacidade"', instruction)
                return verdict

            async def post(path, payload): sent.append(payload["text"])

            class Bridge(FakeHTTP):
                async def get(self, url, **kwargs):
                    class R:
                        status_code = 200
                        def raise_for_status(self): pass
                        def json(self): return state
                    return R()

            with patch.object(app, "ask_llm", new=llm), patch.object(app, "bridge_post", new=post), \
                    patch.object(app, "chatwoot_messages", new=AsyncMock(return_value=[])), patch.object(app.httpx, "AsyncClient", Bridge):
                asyncio.run(app.followup_once(now=anchor + 400))
            self.assertEqual(sent, [expected] if expected else [])

    def test_contact_metrics_and_lean_agent_profile(self):
        perfil = {"seguidores": 900, "posts_total": 50, "bio": "make", "ultimos_posts": [
            {"legenda": "rotina de make", "tipo": "VIDEO", "link": "https://instagram.com/p/1", "curtidas": 10, "comentarios": 2},
            {"legenda": "coleção nova", "tipo": "IMAGE", "link": "https://instagram.com/p/2", "curtidas": 5, "comentarios": 1}]}
        attrs = app.crm.contact_attributes("carla", {"status": "confirmado", "method": "clique"}, perfil, "loja", None, {"campanha": "raiox", "palavra": "raiox"})
        self.assertEqual(attrs["ig_curtidas_recentes"], 15)
        self.assertEqual(attrs["ig_comentarios_recentes"], 3)
        self.assertEqual(attrs["ig_usuario"], "https://instagram.com/carla")
        self.assertIn("https://instagram.com/p/2", attrs["ig_ultimos_posts"])
        lean = app.enrichment.for_agent(perfil)
        self.assertEqual(lean["ultimos_posts"][0], {"legenda": "rotina de make", "tipo": "VIDEO"})

    def test_lead_reply_does_not_restart_the_clock(self):
        anchor = 1790600400.0
        app.tracked.clear()
        app.tracked[81] = {"jid": "j", "last_agent_ts": anchor}
        state = {"last_agent_ts": anchor, "last_lead_ts": anchor - 60, "lead": {"registros": {}}}
        self.assertEqual(self.run_followups(anchor + 400, state), ["5min"])
        # the lead answered at +20min and the agent replied at +21min
        state = {**state, "last_lead_ts": anchor + 1200, "last_agent_ts": anchor + 1260}
        # 30min checkpoint (anchor+30min) while they are still talking: skipped, not postponed
        self.assertEqual(self.run_followups(anchor + 1850, state), [])
        with closing(app.connection()) as conn:
            row = conn.execute("SELECT disparar, motivo FROM decisions WHERE conversation_id=81 AND stage='30min'").fetchone()
        self.assertEqual(row, (0, "conversa em andamento"))
        # no reset to 5min: the next touch is the 2h one, on the original clock
        self.assertEqual(self.run_followups(anchor + 3000, state), [])
        self.assertEqual(self.run_followups(anchor + 7300, state), ["2h"])

    def test_lead_spoke_last_waits_without_consuming_the_stage(self):
        anchor = 1790600400.0
        app.tracked.clear()
        app.tracked[82] = {"jid": "j", "last_agent_ts": anchor}
        state = {"last_agent_ts": anchor, "last_lead_ts": anchor - 60, "lead": {"registros": {}}}
        self.assertEqual(self.run_followups(anchor + 400, state), ["5min"])
        waiting = {**state, "last_lead_ts": anchor + 1700}  # agent still owes a reply
        self.assertEqual(self.run_followups(anchor + 1850, waiting), [])
        replied = {**state, "last_lead_ts": anchor + 1700, "last_agent_ts": anchor + 1720}
        # conversation still warm (quiet < 30 min) -> skipped
        self.assertEqual(self.run_followups(anchor + 1900, replied), [])

    def test_sequence_ends_and_new_silence_starts_a_new_one(self):
        anchor = 1790600400.0
        app.tracked.clear()
        app.tracked[83] = {"jid": "j", "last_agent_ts": anchor}
        state = {"last_agent_ts": anchor, "last_lead_ts": anchor - 60, "lead": {"registros": {}}}
        self.assertEqual(self.run_followups(anchor + 86500, state), ["d1"])  # last checkpoint
        self.assertEqual(app.sequence(83)[1] is not None, True)
        self.assertEqual(self.run_followups(anchor + 90000, state), [])  # ended, no new silence
        later = {**state, "last_lead_ts": anchor + 90000, "last_agent_ts": anchor + 90060}
        self.assertEqual(self.run_followups(anchor + 90060 + 400, later), ["5min"])

    def test_followup_skips_night_lead_last_paused_and_outcome(self):
        anchor = 1790600400.0
        night = 1790650800.0  # 2026-09-29 00:00 Brasília
        for cid, extra in ((84, {}), (85, {"last_lead_ts": anchor + 10}), (86, {"paused": True}), (87, {"lead": {"registros": {"desfecho": "perdido"}}})):
            app.tracked.clear()
            app.tracked[cid] = {"jid": "j", "last_agent_ts": anchor}
            state = {"last_agent_ts": anchor, "last_lead_ts": anchor - 60, "lead": {"registros": {}}, **extra}
            when = night if cid == 84 else anchor + 400
            self.assertEqual(self.run_followups(when, state), [], cid)

    def test_after_the_link_the_first_hours_are_kiwifys(self):
        # Decisão do Talles (06/10): depois do link, 5min/30min/2h ficam com o recuperador da Kiwify; d1 continua nosso.
        anchor = 1790600400.0
        app.tracked.clear()
        app.tracked[88] = {"jid": "j", "last_agent_ts": anchor}
        state = {"last_agent_ts": anchor, "last_lead_ts": anchor - 60, "lead": {"registros": {"link_enviado": "sim"}}}
        self.assertEqual(self.run_followups(anchor + 400, state), [])
        self.assertEqual(self.run_followups(anchor + 7800, state), [])
        self.assertEqual(self.run_followups(anchor + 86500, state), ["d1"])

    def test_compact_transcript(self):
        rows = app.compact_transcript([
            {"message_type": 1, "content": "Quantas pessoas dependem de você?", "created_at": 1790600500},
            {"message_type": 0, "content": "quando eu viajo o financeiro para", "created_at": 1790600400},
            {"message_type": 1, "content": "nota interna", "private": True, "created_at": 1790600600},
            {"message_type": 2, "content": "Conversation resolved", "created_at": 1790600700},
            {"message_type": 0, "content": "", "attachments": [{"file_type": "image"}], "created_at": 1790600800},
        ])
        self.assertEqual([r["autor"] for r in rows], ["lead", "agente", "lead"])
        self.assertEqual(rows[0]["texto"], "quando eu viajo o financeiro para")
        self.assertEqual(rows[-1]["texto"], "[anexo]")

    def test_parse_json_object_tolerates_fences_and_prose(self):
        self.assertEqual(app.parse_json_object('```json\n{"decision":"aprovar"}\n```'), {"decision": "aprovar"})
        self.assertEqual(app.parse_json_object('Claro! {"disparar": false, "texto": "", "motivo": "x"} ok'), {"disparar": False, "texto": "", "motivo": "x"})
        self.assertIsNone(app.parse_json_object(""))
        self.assertIsNone(app.parse_json_object("[1,2]"))

    def test_unknown_conversation_is_forgotten(self):
        app.tracked.clear()
        app.tracked[99] = {"jid": "j", "last_agent_ts": 1790600400.0}
        class Gone(FakeHTTP):
            async def get(self, url, **kwargs):
                class R:
                    status_code = 404
                    def raise_for_status(self): raise AssertionError("not reached")
                    def json(self): return {}
                return R()
        with patch.object(app.httpx, "AsyncClient", Gone):
            asyncio.run(app.followup_once(now=1790600400.0 + 400))
        self.assertNotIn(99, app.tracked)

    def test_d4_only_after_price(self):
        self.assertEqual(app.due_stage(4 * 86400 + 10, post_price=False), "d1")
        self.assertEqual(app.due_stage(4 * 86400 + 10, post_price=True), "d4")
        self.assertIsNone(app.due_stage(100, post_price=True))

OFERTAS = json.loads((Path(__file__).resolve().parent.parent / "hermes-sdr" / "ofertas.json").read_text(encoding="utf-8"))
INSTALADOR = {"oferta": "instalador", "ofertas": OFERTAS, "capacidade": {"status": "ok"}, "lead": {"oferta": "instalador"}}


class OfferRules(unittest.TestCase):
    def test_installer_facts_come_from_ofertas_json(self):
        facts = "\n".join(app.oferta.facts(INSTALADOR))
        self.assertIn("https://instalador.talles.dev/antes", facts)
        self.assertIn("R$ 47", facts)
        self.assertIn("Pronto em 48 h", facts)
        self.assertEqual(app.oferta.facts({"ofertas": OFERTAS}), [])  # unknown offer: no installer list

    def test_prices_links_secrets_and_promises(self):
        check = lambda text, lead=(): app.oferta.check([text], INSTALADOR, list(lead))
        self.assertEqual(check("A instalação é R$ 47, pagamento único. A VPS fica em uns R$ 119 por mês."), [])
        self.assertEqual(check("Compra por aqui: https://instalador.talles.dev/antes"), [])
        self.assertIn("valor que não existe na oferta: R$ 97", check("Hoje sai por R$ 97."))
        self.assertIn("valor que não existe na oferta: R$ 2.000", check("Uma pessoa custa R$ 2.000"))
        self.assertEqual(check("Você me disse que paga R$ 2.000 pra sua secretária.", ["pago uns R$ 2 mil pra ela"]), [])
        self.assertTrue(check("O checkout é pay.kiwify.com.br/ju44Xqc")[0].startswith("link fora da oferta"))
        self.assertTrue(any("senha" in i for i in check("Me passa a senha da VPS que eu já adianto.")))
        self.assertTrue(any("senha" in i for i in check("Qual é o seu IP?")))
        self.assertEqual(check("Não me mande a senha por aqui. Ela vai só no formulário cifrado, depois da compra."), [])
        self.assertIn("promessa de faturamento ou vendas", check("Com o time você vai faturar o dobro."))
        self.assertIn("desconto ou cupom (não existe)", check("Pra você eu consigo um desconto."))
        self.assertEqual(check("Não tem desconto, o preço é esse."), [])
        self.assertTrue(any("48 h" in i for i in check("Fica pronto em 24 horas.")))
        self.assertEqual(check("Ele responde 24 horas por dia."), [])

    def test_forbidden_names_in_both_offers_and_prices_only_in_installer(self):
        raiox = {"oferta": "raiox", "ofertas": OFERTAS}
        self.assertEqual(app.oferta.check(["O Raio-X é R$ 12.000; um dev pleno custa R$ 12 a 18 mil."], raiox, []), [])
        self.assertEqual(app.oferta.check(["É tipo a Naia, só que instalada."], raiox, []), ["nome proibido: naia"])
        self.assertIn("nome proibido: squad", app.oferta.check(["Monte o seu Squad"], INSTALADOR, []))

    def test_spiced_state_lists_missing_letters(self):
        state = app.oferta.spiced_state({"situacao": "clínica, 3 pessoas", "dor": "responder", "tem_vps": "sim"}, "instalador")
        self.assertEqual(state["registrado"], {"S": "clínica, 3 pessoas", "P": "responder"})
        self.assertEqual(state["faltando"], ["I", "C", "D", "D:tem_codex"])
        self.assertNotIn("D:tem_vps", app.oferta.spiced_state({}, "raiox")["faltando"])


class PromptsMatchTheOffer(unittest.TestCase):
    """The prompts quote the offer; ofertas.json is the source. They must not drift."""
    ROOT = Path(__file__).resolve().parent.parent

    def test_installer_section_of_the_soul_only_quotes_real_prices(self):
        soul = (self.ROOT / "hermes-sdr" / "SOUL.md").read_text(encoding="utf-8")
        installer = soul.split("═══ CAMINHO DO INSTALADOR ═══")[1].split("═══ CAMINHO DO RAIO-X ═══")[0]
        allowed = app.oferta.offer_amounts(OFERTAS, "instalador")
        self.assertEqual(app.oferta.amounts(installer) - allowed, set())
        self.assertIn(OFERTAS["instalador"]["link_compra"], installer)
        for forbidden in ("24 h", "desconto", "Naia"):
            self.assertNotIn(forbidden, installer)
        # The agent's own example lines pass the deterministic check: before the
        # purchase, everything up to DEPOIS DA COMPRA; after it, the whole path.
        before = installer.split("DEPOIS DA COMPRA")[0]
        self.assertEqual(app.oferta.check([before], INSTALADOR, []), [])
        bought = {**INSTALADOR, "lead": {"oferta": "instalador", "registros": {"comprou": "sim"}}}
        self.assertEqual(app.oferta.check([installer], bought, []), [])

    def test_prompts_carry_the_offer_rules(self):
        revisor = app.prompt("revisor.md")
        self.assertIn("valem só com `oferta` = raiox", revisor)
        self.assertIn("ROTEIRO LITERAL (só no Raio-X)", revisor)
        self.assertIn("verificacao_automatica", revisor)
        self.assertIn("proximo_passo", app.prompt("supervisor.md"))
        self.assertIn("`stage` = prazo", app.prompt("fup.md"))


class OfferReview(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app.app)
        self.headers = {"Authorization": "Bearer test"}

    def review(self, parts, verdict, lead_message="quanto custa?"):
        seen = []

        async def llm(instruction, **kwargs):
            seen.append(instruction)
            return verdict

        with patch.object(app, "ask_llm", new=llm), patch.object(app.crm, "activity", new=AsyncMock()):
            result = self.client.post("/review", headers=self.headers, json={
                "conversation_id": 501, "lead_message": lead_message, "draft_parts": parts, "directives": [],
                "context": INSTALADOR, "transcript": [{"autor": "lead", "texto": lead_message, "quando": ""}]}).json()
        return result, seen

    def test_reviewer_gets_the_generated_fact_list_and_the_offer(self):
        result, seen = self.review(["A instalação é R$ 47, pagamento único."], {"decision": "aprovar"})
        self.assertEqual(result["decision"], "aprovar")
        dados = json.loads(seen[0].split("\nDADOS:\n", 1)[1])
        self.assertEqual(dados["oferta"], "instalador")
        self.assertTrue(any("instalador.talles.dev/antes" in line for line in dados["fatos_oferta"]))
        self.assertEqual(dados["verificacao_automatica"], [])

    def test_hard_violation_is_blocked_even_if_the_model_approves_or_is_down(self):
        for verdict in ({"decision": "aprovar"}, None):
            result, _ = self.review(["Me passa a senha da VPS que eu adianto aqui."], verdict)
            self.assertEqual(result["decision"], "bloquear")
            self.assertIn("verificação automática", result["motivo"])
        result, _ = self.review(["Pra você sai por R$ 97."], {"decision": "aprovar"})
        self.assertIn("R$ 97", result["motivo"])

    def test_a_rewrite_that_fixes_the_violation_goes_through(self):
        fixed = {"decision": "reescrever", "parts": ["A senha vai só no formulário cifrado, depois da compra. Você já tem a VPS?"], "motivo": "pedido de senha"}
        result, _ = self.review(["Me passa a senha da VPS."], fixed)
        self.assertEqual(result["decision"], "reescrever")
        still_bad = {"decision": "reescrever", "parts": ["Me manda o token do bot aqui."], "motivo": "x"}
        self.assertEqual(self.review(["Me passa a senha da VPS."], still_bad)[0]["decision"], "bloquear")


class NextSteps(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app.app)
        self.headers = {"Authorization": "Bearer test"}
        app.last_step_line.clear()
        with closing(app.connection()) as conn:
            conn.execute("DELETE FROM lead_steps"); conn.execute("DELETE FROM decisions"); conn.execute("DELETE FROM sequences")
            conn.execute("DELETE FROM events WHERE kind='record'"); conn.commit()

    def post_records(self, cid, records, ts=1790600400.0):
        lines, attrs = [], []

        async def activity(conversation_id, text): lines.append(text)
        async def set_attrs(conversation_id, attributes): attrs.append(attributes)

        with patch.object(app, "STEP_ACTIVITY_DELAY", 0), patch.object(app.crm, "activity", new=activity), \
                patch.object(app.crm, "set_conversation_attributes", new=set_attrs):
            for campo, valor in records:
                self.assertEqual(self.client.post("/events/record", headers=self.headers, json={"conversation_id": cid, "campo": campo, "valor": valor, "ts": ts}).status_code, 202)

            async def drain():
                while app.step_announcements:
                    await asyncio.gather(*list(app.step_announcements.values()), return_exceptions=True)
            asyncio.run(drain())
        return lines, attrs

    def test_records_feed_lead_steps_attributes_and_one_activity_line(self):
        lines, attrs = self.post_records(601, [("oferta", "instalador"), ("etapa_spiced", "D"), ("tem_vps", "sim"),
                                               ("proximo_passo", "comprar pelo link"), ("proximo_passo_em", "2026-10-08")])
        step = app.lead_step(601)
        self.assertEqual({k: step[k] for k in ("oferta", "etapa_spiced", "proximo_passo", "proximo_passo_em", "status")},
                         {"oferta": "instalador", "etapa_spiced": "D", "proximo_passo": "comprar pelo link", "proximo_passo_em": "2026-10-08", "status": "pendente"})
        self.assertIn({"spiced_oferta": "instalador"}, attrs)
        self.assertIn({"spiced_tem_vps": "sim"}, attrs)
        self.assertIn("📌 Próximo passo: comprar pelo link até 08/10/2026", lines)
        self.assertTrue(all(line.startswith("📌") for line in lines))
        self.assertEqual(self.post_records(601, [("proximo_passo_em", "2026-10-08")])[0], [])  # same step: no new line

    def test_missing_prerequisite_becomes_a_next_step_for_the_next_day(self):
        self.post_records(602, [("oferta", "instalador"), ("tem_vps", "não")], ts=1790600400.0)  # 28/09 10:00
        step = app.lead_step(602)
        self.assertEqual((step["proximo_passo_em"], step["status"]), ("2026-09-29", "pendente"))
        self.assertIn("VPS", step["proximo_passo"])
        # A date the agent agreed with the lead wins and is not overwritten.
        self.post_records(603, [("proximo_passo", "contratar a VPS"), ("proximo_passo_em", "2026-10-02"), ("tem_codex", "não")])
        self.assertEqual(app.lead_step(603)["proximo_passo_em"], "2026-10-02")

    def test_outcome_closes_the_step_and_formats(self):
        self.post_records(604, [("proximo_passo", "x"), ("proximo_passo_em", "2026-10-08T15:30"), ("desfecho", "perdido")])
        self.assertEqual(app.lead_step(604)["status"], "encerrado")
        self.assertEqual(app.step_line({"proximo_passo": "ligar", "proximo_passo_em": "2026-10-08T15:30"}), "📌 Próximo passo: ligar até 08/10/2026 15:30")
        self.assertEqual(app.step_line({"proximo_passo": "ligar", "proximo_passo_em": "semana que vem"}), "📌 Próximo passo: ligar até semana que vem")
        self.assertIsNone(app.step_due_ts({"proximo_passo_em": "semana que vem"}))
        self.assertEqual(datetime.fromtimestamp(app.step_due_ts({"proximo_passo_em": "08/10/2026"}), app.BUSINESS_TZ).hour, app.STEP_DUE_HOUR)

    def run_pass(self, cid, now, state):
        posted, prompts = [], []

        async def llm(instruction, **kwargs):
            prompts.append(instruction)
            if '"tipo": "toque"' in instruction:
                return {"decision": "aprovar"}
            return {"disparar": True, "texto": "Conseguiu contratar a VPS ontem, ou ficou pra outro dia?", "motivo": "prazo"}

        async def post(path, payload): posted.append(payload)

        class Bridge(FakeHTTP):
            async def get(self, url, **kwargs):
                class R:
                    status_code = 200
                    def raise_for_status(self): pass
                    def json(self): return state
                return R()

        app.tracked.clear(); app.tracked[cid] = {"jid": "j", "last_agent_ts": state["last_agent_ts"]}
        with patch.object(app, "ask_llm", new=llm), patch.object(app, "bridge_post", new=post), patch.object(app.crm, "activity", new=AsyncMock()), \
                patch.object(app, "chatwoot_messages", new=AsyncMock(return_value=[])), patch.object(app.httpx, "AsyncClient", Bridge):
            asyncio.run(app.followup_once(now=now))
        return posted, prompts

    def test_due_next_step_triggers_one_touch_besides_silence(self):
        self.post_records(605, [("oferta", "instalador"), ("tem_vps", "não")], ts=1790600400.0)  # due 29/09 10:00
        due = app.step_due_ts(app.lead_step(605))
        agent = due - 3 * 3600  # the lead talked before; silence stages long gone or not reached
        state = {"last_agent_ts": agent, "last_lead_ts": agent - 60, "lead": {"registros": {"oferta": "instalador", "tem_vps": "não"}},
                 "context": {"oferta": "instalador", "ofertas": OFERTAS}}
        before = self.run_pass(605, due - 60, state)[0]  # the silence cadence runs as usual
        self.assertEqual([p["stage"] for p in before], ["2h"])
        with closing(app.connection()) as conn:
            conn.execute("DELETE FROM decisions"); conn.execute("DELETE FROM sequences"); conn.commit()
        posted, prompts = self.run_pass(605, due + 60, state)
        self.assertEqual([p["stage"] for p in posted], ["prazo"])
        context = json.loads(prompts[0].split("\nCONTEXTO:\n", 1)[1])
        self.assertEqual((context["stage"], context["oferta"], context["pre_requisitos"]["tem_vps"]), ("prazo", "instalador", "não"))
        self.assertEqual(app.lead_step(605)["status"], "cobrado")
        self.assertNotIn("prazo", [p["stage"] for p in self.run_pass(605, due + 120, state)[0]])  # once

    def test_due_step_waits_while_the_lead_owes_nothing_but_the_agent_does(self):
        self.post_records(606, [("proximo_passo", "mandar o link"), ("proximo_passo_em", "2026-09-29")], ts=1790600400.0)
        due = app.step_due_ts(app.lead_step(606))
        state = {"last_agent_ts": due - 600, "last_lead_ts": due - 300, "lead": {"registros": {}}}  # lead spoke last
        self.assertEqual(self.run_pass(606, due + 60, state)[0], [])
        self.assertEqual(app.lead_step(606)["status"], "pendente")

    def test_supervisor_sees_missing_spiced_letters(self):
        self.post_records(607, [("oferta", "instalador"), ("situacao", "salão com 4 pessoas")])
        seen = []

        async def llm(instruction, **kwargs):
            seen.append(instruction); return {"guidance": None, "escalate": False}

        with patch.object(app, "chatwoot_messages", new=AsyncMock(return_value=[])), patch.object(app, "ask_llm", new=llm):
            asyncio.run(app.supervisor({"conversation_id": 607}))
        spiced = json.loads(seen[0].split("\nCONTEXTO:\n", 1)[1])["spiced"]
        self.assertEqual(spiced["oferta"], "instalador")
        self.assertEqual(spiced["faltando"], ["P", "I", "C", "D", "D:tem_vps", "D:tem_codex"])


if __name__ == "__main__": unittest.main(verbosity=2)
