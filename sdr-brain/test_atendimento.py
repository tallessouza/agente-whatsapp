"""Oferta "atendimento" (prospecção ativa): sem preço e sem link na conversa; nada das regras do Instalador."""
import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("SDR_BRAIN_TOKEN", "test")
os.environ.setdefault("SDR_BRAIN_DB", os.path.join(tempfile.gettempdir(), "sdr-brain-atendimento.db"))
import oferta  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OFERTAS = {k: v for k, v in json.loads((ROOT / "hermes-sdr" / "ofertas.json").read_text(encoding="utf-8")).items() if k in oferta.OFFERS}
A = {"oferta": "atendimento", "ofertas": OFERTAS}


class AtendimentoTests(unittest.TestCase):
    def test_offer_is_known_and_has_facts(self):
        self.assertIn("atendimento", oferta.OFFERS)
        self.assertEqual(oferta.current_offer(A), "atendimento")
        self.assertTrue(any("conversa de 20 minutos" in line for line in oferta.facts(A)))

    def test_any_price_or_link_is_flagged(self):
        issues = oferta.check(["Fica R$ 2.997 a implantação."], A, [])
        self.assertTrue(any("preço na conversa do Atendente" in i for i in issues))
        issues = oferta.check(["Dá uma olhada aqui https://instalador.talles.dev/oferta/whatsapp"], A, [])
        self.assertTrue(any("link na conversa do Atendente" in i for i in issues))

    def test_honest_reveal_and_call_pass(self):
        parts = ["Obrigado por responder! Sou o agente do Talles e preciso ser honesto: não tenho dúvida nenhuma, foi um teste de tempo de resposta. Vocês responderam em 2 horas.",
                 "Não é crítica: a essa hora ninguém tem obrigação de estar olhando o WhatsApp. É justamente isso que eu resolvo.",
                 "Numa semana normal, quantas mensagens chegam assim, depois do horário?"]
        self.assertEqual(oferta.check(parts, A, []), [])
        self.assertEqual(oferta.check(["Depende do volume de vocês, por isso o Talles monta a proposta numa conversa de 20 minutos. Fica melhor terça às 10h ou quarta às 15h?"], A, []), [])
        self.assertEqual(oferta.check(["E tem uma condição especial de implantação para os 5 primeiros negócios que fecharem."], A, []), [])
        # elsewhere, and with another number, it is still an invented discount
        self.assertTrue(oferta.check(["Tem uma condição especial pra você fechar hoje."], A, []))
        self.assertTrue(oferta.check(["Tem uma condição especial pra você."], {"oferta": "instalador", "ofertas": OFERTAS}, []))

    def test_installer_rules_do_not_apply(self):
        # "atende seus clientes no WhatsApp" is the product here.
        self.assertEqual(oferta.check(["O atendente responde seus clientes no WhatsApp a qualquer hora, sem você estar online."], A, []), [])
        self.assertFalse(oferta.price_without_link(["A instalação fica pronta rápido."], A))


if __name__ == "__main__":
    unittest.main()
