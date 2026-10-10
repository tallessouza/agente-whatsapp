"""Offer facts and deterministic checks for the reviewer.

The facts come from `ofertas.json` (hermes-sdr/, mounted in the bridge like
capacidade.json), which the bridge sends inside `context.ofertas`. Nothing
here judges tone: it only finds what a model must never let through (a price
that does not exist, an unknown link, a request for the server password, a
revenue promise, a discount, a contact promise, the competitor's words), for
either offer and also before the offer is known.

The forbidden list lives here and nowhere else: the reviewer and FUP prompts
get it through `{{PROIBIDOS}}`, and `python oferta.py soul <SOUL.md>` writes it
into the SOUL (a test fails when the SOUL drifts from it).
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

OFFERS = ("instalador", "raiox", "atendimento")
# The "atendimento" offer (prospecção ativa): no price and no link in the conversation;
# the next step is a 20-minute talk with the Talles, who makes the proposal.
NO_PRICE_OFFERS = ("atendimento",)
SPICED_FIELDS = {"S": "situacao", "P": "dor", "I": "impacto", "C": "evento_critico", "D": "decisao"}

# Structure of the competitor's pages may be used; his words, names and numbers never.
# (as the agent reads it, pattern on accent-folded lower-case text)
FORBIDDEN_WORDS = (
    ("Naia", r"\bnaia\b"),
    ("Squad", r"\bsquads?\b"),
    ("Avalanche", r"\bavalanche\b"),
    ("Denderson", r"\bdenderson\b"),
)
FORBIDDEN_PHRASES = (
    ("Bom dia, Naia", r"\bbom dia,? naia\b"),
    ("Pare de contratar", r"\bpare de contratar\b"),
    ("Comece a implantar", r"\bcomece a implantar\b"),
    ("no lugar do Chefe", r"\bno lugar do chefe\b"),
    ("R$ 100 mil em 30 dias", r"\b100 mil (?:em|nos proximos) 30 dias\b"),
)
# The competitor's testimonial names. A lead may be called Paulo: a name the
# lead used himself (his own, a partner's) is not the competitor's.
FORBIDDEN_PEOPLE = ("Rafael", "Juliana", "Davi", "Paulo", "Jonathan")
INSTALLER_HOSTS = {"instalador.talles.dev"}

NUMBER = r"(\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{1,2})?"
MONEY_RE = re.compile(r"r\$\s?" + NUMBER + r"(?:\s?(?:a|-|ou)\s?" + NUMBER + r")?(\s?(?:mil|milhao|milhoes)\b)?")
URL_RE = re.compile(r"(?:https?://|www\.)[^\s)>\]]+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|dev|br|io|net|app)(?:\.br)?(?:/[^\s)>\]]*)?", re.I)
NEGATION_RE = re.compile(r"\b(?:nao|nunca|nem|jamais|sem)\b")

SECRET = (r"(?:senha|token|ip|login|usuario|acesso|credencia\w*|chave ssh|chave privada"
          r"|dados?\s+d[oae]\s+(?:servidor|vps|acesso|bot|hostinger|login))")
SECRET_VERB = r"(?:passa|passe|passar|manda|mande|mandar|envia|envie|enviar|informa|informe|informar|digita|digite|digitar|cola|cole|colar|compartilha|compartilhe|compartilhar)"
SECRET_REQUEST_RE = re.compile(
    r"\b" + SECRET_VERB + r"\s+(?:\w+\s+){0,3}?(?:(?:a|o|as|os|sua|seu|suas|seus|essa|esse|um|uma)\s+)?" + SECRET + r"\b"
    r"|\bprecis\w*\s+(?:d[oa]s?|de)\s+" + SECRET + r"\b"
    r"|\bqual\s+(?:e\s+)?(?:a|o)\s+(?:sua\s+|seu\s+)?" + SECRET + r"\b"
    r"|\bprint\b[^.!?\n]{0,40}\b(?:acesso|senha|painel|login|servidor|vps|token)\b"
)
REVENUE_PROMISE_RE = re.compile(
    r"\b(?:vai|vao|garant\w*)\s+(?:\w+\s+){0,4}?(?:faturar|lucrar|vender mais|ganhar mais|aumentar\s+(?:o\s+|seu\s+|sua\s+|suas\s+|seus\s+|as\s+|os\s+)?(?:faturamento|vendas|lucro|receita))"
    r"|\b(?:aumenta|aumentam|aumentaria|turbina\w*|alavanca\w*|dobra\w*|triplica\w*|multiplica\w*)\s+(?:o\s+|seu\s+|sua\s+|suas\s+|seus\s+|as\s+|os\s+)?(?:faturamento|vendas|lucro|receita|ganhos)"
    r"|\bse paga\b|\bpaga sozinh[oa]\b|\bretorno garantido\b"
)
DISCOUNT_RE = re.compile(r"\b(?:te dou|dou|faco|faz|consigo|tem|ganha|libero|aplico)\s+(?:um\s+|uma\s+)?(?:desconto|cupom|abatimento)\b"
                         r"|\d+\s?%\s?(?:de\s+)?(?:desconto|off)\b|\bcondicao especial\b")
FAST_DEADLINE_RE = re.compile(
    r"\b(?:em|ate|dentro de)\s+(?:(?:1|um)\s+dia\b(?!\s+util)|(\d{1,2})\s?(?:h|hs|horas)\b(?!\s+por\s+dia))"
    r"|\bamanha\b[^.!?\n]{0,40}\b(?:pronto|pronta|instalad\w*|funcionando|rodando)\b"
    r"|\b(?:pronto|pronta|instalad\w*|funcionando|rodando)\b[^.!?\n]{0,25}\b(?:amanha|hoje mesmo)\b"
)
CONTACT_PROMISE_RE = re.compile(
    r"\bte (?:chamo|procuro|escrevo|cobro|retorno|mando (?:uma )?mensagem|dou um toque)\b"
    r"|\b(?:volto|vou voltar) a (?:te )?(?:chamar|procurar|escrever)\b|\bpasso aqui\b"
)
VIDEO_RE = re.compile(r"\b(?:tem|temos|ha|segue|te mando|mando|manda|olha|assiste|assista|veja|ve|gravei|gravado)\b[^.!?\n]{0,25}\bvideos?\b"
                      r"|\bvideos?\b[^.!?\n]{0,25}\b(?:mostra|mostram|ensina|ensinam|explica|explicam)\b")
GEMINI_DURATION_RE = re.compile(r"\bconta do gemini\b[^.!?\n]{0,60}\b(?:vitalicia|para sempre|pra sempre|nunca expira|nao expira|por tempo indeterminado|por \d+ (?:dias|meses|anos)|(?:um|1) ano\b(?! de tokens))")
# TSX-77/78 (07/10, conversa 16). The installation price never goes out without
# the /antes link and a next step; before the link, no way out is offered; the
# agent talks TO the lead, never about her ("direto pra empresa dela").
PURCHASE_LINK = "https://instalador.talles.dev/antes"
PRICE_CTA = f"O caminho é por aqui {PURCHASE_LINK}. Consegue fazer hoje?"
INSTALL_PRICE_RE = re.compile(r"\br\$ ?47\b,?\s*(?:pagamento )?unico\b"
                              r"|\b(?:instalacao|time de ia|time)\b[^.!?\n]{0,25}?\b(?:e|custa|sai|fica)\b(?:\s+(?:por|so|de))?\s+r\$ ?47\b")
OTHER_TIME_RE = re.compile(r"\boutr[oa] (?:momento|hora|horario)\b|\bquando (?:voce |vc )?(?:puder|quiser|tiver (?:um )?tempo)\b"
                           r"|\bmais (?:pra|para) frente\b|\b(?:olhar|ver|pensar|decidir|deixar)\b[^.!?\n]{0,20}\b(?:depois|mais tarde|com calma)\b")
# The bridge blocks (and escalates) a reply with an AI name said alone
# (bridge-src/sdr.py, LEAK_TERMS and OFFER_PHRASES): flag it here so the
# reviewer rewrites it as the offer phrase instead. Keep both lists in line.
AI_OFFER_PHRASES = ("conta do gemini", "oauth do gemini", "assinatura do gemini", "assinatura gemini one", "gemini one", "seu gemini",
                    "sua conta do gemini", "gemini advanced", "plano pago do chatgpt", "plano do chatgpt", "assinatura do chatgpt",
                    "conta do chatgpt", "conta gratis do chatgpt", "conta gratuita do chatgpt", "seu chatgpt", "chatgpt plus", "chatgpt pro")
BARE_AI_NAME_RE = re.compile(r"\b(?:chatgpt|gemini|openai|claude|anthropic)\b|\bgpt-")
THIRD_PERSON_RE = re.compile(r"\b(?:empresa|negocio|caso|servidor|vps|nome|conta|agenda|clientes|alunos|alunas|trabalho|metodo|telegram)\s+(?:dela|dele)\b"
                             r"|\b(?:do|da|pro|pra|para o|para a) lead\b")
WHATSAPP_SERVICE_RE = re.compile(r"\b(?:time|instalacao|agentes?|r\$ 47)\b[^.!?\n]{0,60}\b(?:atende|atendem|responde|respondem|atendendo|respondendo)\b[^.!?\n]{0,30}\b(?:seus clientes|os clientes|clientes|whatsapp|whats|zap)\b")
UPPER_STEP_RE = re.compile(r"\braio[\s-]?x\b|\bcopiar a minha operacao\b")
# The Raio-X proof (SOUL, OS NÚMEROS DO RAIO-X) is proof only in the Raio-X.
RAIOX_PROOF_RE = re.compile(r"\b(?:30 mil usuarios|18 mil agentes|9 milhoes de numeros|8 digitos|300 mil mensagens|101 entregas|375 tipos de tarefa|1\.125 execucoes|344 projetos|81\.131 anuncios|602 contas)\b")
COPIAR_SWAP_RE = re.compile(r"\bcopiar a minha operacao\b[^.!?\n]{0,80}\b(?:21 dias|3 a 5 fluxos|fluxos|sustentacao)\b"
                            r"|\b(?:21 dias|3 a 5 fluxos)\b[^.!?\n]{0,80}\bcopiar a minha operacao\b"
                            r"|\bimplantacao\b[^.!?\n]{0,80}\b(?:vm1|operacao do talles|copia a operacao|reproduz a operacao)\b")
# A value the lead said may be echoed only as what HE pays (the task-by-task
# comparison), never as a price of ours ("depois da nº 50 vai para R$ 97").
LEAD_COST_RE = re.compile(r"\b(?:voce|vc)\b[^.!?\n]{0,30}\b(?:paga|pagava|gasta|gastava|perde|perdia|investe)\b|\bte custa\b|\bcusta (?:pra|para) (?:voce|vc)\b")
OUR_PRICE_RE = re.compile(r"\b(?:instalacao|time de ia|preco|lote|anuncio|vai para|vai pra|sobe|passa a custar|sai por)\b|r\$ 47\b")


def fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()


def forbidden_list() -> str:
    """The one forbidden list, as the SOUL and the prompts show it."""
    words = ", ".join(display for display, _ in FORBIDDEN_WORDS)
    phrases = ", ".join(f'"{display}"' for display, _ in FORBIDDEN_PHRASES)
    people = ", ".join(FORBIDDEN_PEOPLE[:-1]) + " e " + FORBIDDEN_PEOPLE[-1]
    return f"{words}; as frases {phrases}; os nomes {people}"


SOUL_LINE_PREFIX = "   Proibido em qualquer contexto: "


def soul_line() -> str:
    return SOUL_LINE_PREFIX + forbidden_list() + "; e nome, frase ou número de concorrente."


def sync_soul(path: str | Path) -> bool:
    """Rewrite the forbidden line of the SOUL from this list. Returns True when it changed."""
    with open(path, encoding="utf-8", newline="") as file:
        text = file.read()
    eol = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(eol)
    start = next(i for i, line in enumerate(lines) if line.startswith(SOUL_LINE_PREFIX))
    end = start
    while not lines[end].rstrip().endswith("concorrente."):
        end += 1
    new = eol.join(lines[:start] + [soul_line()] + lines[end + 1:])
    if new != text:
        with open(path, "w", encoding="utf-8", newline="") as file:
            file.write(new)
    return new != text


def current_offer(context: dict[str, Any]) -> str | None:
    """The offer of the conversation as the bridge resolved it (record or campaign)."""
    offer = (context or {}).get("oferta") or ((context or {}).get("lead") or {}).get("oferta")
    return offer if offer in OFFERS else None


def purchased(context: dict[str, Any]) -> bool:
    """The lead said he bought the installation ([[REGISTRO: comprou = sim]])."""
    lead = (context or {}).get("lead") or {}
    value = (lead.get("registros") or {}).get("comprou") or lead.get("comprou")
    return fold(str(value or "")).strip() == "sim"


def disqualified(context: dict[str, Any]) -> bool:
    """The Raio-X triage said no ([[REGISTRO: triagem = desqualificado]])."""
    lead = (context or {}).get("lead") or {}
    value = (lead.get("registros") or {}).get("triagem") or lead.get("triagem")
    return fold(str(value or "")).strip() == "desqualificado"


def amounts(text: str) -> set[int]:
    """Every R$ value in the text, in reais ("R$ 1.300" -> 1300, "R$ 12 a 18 mil" -> 12000 and 18000)."""
    found = set()
    for first, second, unit in MONEY_RE.findall(fold(text)):
        unit = unit.strip()
        factor = 1_000_000 if unit.startswith("milh") else 1000 if unit == "mil" else 1
        for number in (first, second):
            if number:
                found.add(int(number.replace(".", "")) * factor)
    return found


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for item in value.values() for s in _strings(item)]
    if isinstance(value, list):
        return [s for item in value for s in _strings(item)]
    return []


def offer_amounts(ofertas: dict[str, Any], offer: str, upper_steps: bool = True) -> set[int]:
    """R$ values of an offer; without `upper_steps`, the Raio-X/Copiar prices the installer lead may not see yet."""
    data = (ofertas or {}).get(offer)
    if isinstance(data, dict) and not upper_steps:
        data = {key: value for key, value in data.items() if key != "degraus_acima"}
    return {value for text in _strings(data) for value in amounts(text)}


def facts(context: dict[str, Any]) -> list[str]:
    """Readable fact list for the reviewer, generated from ofertas.json."""
    offer = current_offer(context)
    data = ((context or {}).get("ofertas") or {}).get(offer or "")
    if not isinstance(data, dict):
        return []
    lines = []
    for key, value in data.items():
        if isinstance(value, (dict, list)):
            for text in _strings(value):
                lines.append(f"{key}: {text}")
        elif value not in (None, ""):
            lines.append(f"{key}: {value}")
    return lines


def _sentence(folded: str, pos: int) -> str:
    """The sentence around `pos`; a dot between digits ("R$ 1.300") does not end it."""
    ends = [m.end() for m in re.finditer(r"[!?\n]|\.(?!\d)", folded)]
    start = max([e for e in ends if e <= pos], default=0)
    end = min([e for e in ends if e > pos], default=len(folded))
    return folded[start:end]


def _negated(folded: str, pos: int) -> bool:
    """A negation earlier in the same clause: "não vou te prometer que você vai faturar"."""
    clause = re.split(r"[,;:!?\n]|\.(?!\d)", folded[:pos])[-1]
    return bool(NEGATION_RE.search(clause))


def _affirmed(regex: re.Pattern, folded: str) -> list[re.Match]:
    return [m for m in regex.finditer(folded) if not _negated(folded, m.start())]


def forbidden_hits(folded: str, lead_folded: str = "") -> list[str]:
    issues = [f"nome proibido: {fold(display)}" for display, pattern in FORBIDDEN_WORDS if re.search(pattern, folded)]
    issues += [f"frase proibida: {display}" for display, pattern in FORBIDDEN_PHRASES if re.search(pattern, folded)]
    issues += [f"nome proibido: {fold(name)}" for name in FORBIDDEN_PEOPLE
               if re.search(rf"\b{fold(name)}\b", folded) and not re.search(rf"\b{fold(name)}\b", lead_folded)]
    return issues


def _price_issues(folded: str, allowed: set[int], lead_values: set[int]) -> list[str]:
    issues: list[str] = []
    for match in MONEY_RE.finditer(folded):
        sentence = _sentence(folded, match.start())
        lead_cost = LEAD_COST_RE.search(sentence) and not OUR_PRICE_RE.search(sentence)
        for value in sorted(amounts(match.group(0)) - allowed):
            if value in lead_values and lead_cost:
                continue
            issue = f"valor que não existe na oferta: R$ {value:,}".replace(",", ".")
            if issue not in issues:
                issues.append(issue)
    return issues


PRODUCT_PRICE_RE = re.compile(r"\b(raio[\s-]?x|instalacao|implantacao|copiar a minha operacao|conta do gemini|atendimento no whatsapp)\b"
                              r"[^.!?\n]{0,25}?\b(?:e|custa|sai|fica|vale)\b(?:\s+(?:por|so|de|a|o))?\s+(r\$\s?[\d.,]+(?:\s?mil\b)?)")


def product_prices(ofertas: dict[str, Any]) -> dict[str, set[int]]:
    """Each product's own price, from ofertas.json: "o Raio-X é R$ 9.000" is wrong even if 9.000 exists elsewhere."""
    inst, raiox = (ofertas or {}).get("instalador") or {}, (ofertas or {}).get("raiox") or {}
    named = {item.get("nome", ""): item.get("preco") for key in ("bumps", "upsells", "degraus_acima") for item in inst.get(key) or [] if isinstance(item, dict)}
    sources = {"instalacao": inst.get("preco"), "raio-x": raiox.get("preco") or named.get("Raio-X da Operação"),
               "implantacao": (raiox.get("implantacao") or {}).get("preco"),
               "copiar a minha operacao": (raiox.get("copiar_a_minha_operacao") or {}).get("preco") or named.get("Copiar a minha operação"),
               "conta do gemini": named.get("Conta do Gemini"), "atendimento no whatsapp": named.get("Atendimento no WhatsApp")}
    return {name: amounts(price) for name, price in sources.items() if isinstance(price, str) and amounts(price)}


def _product_price_issues(folded: str, ofertas: dict[str, Any]) -> list[str]:
    prices, issues = product_prices(ofertas), []
    for product, money in PRODUCT_PRICE_RE.findall(folded):
        key = "raio-x" if product.startswith("raio") else product
        if key in prices and amounts(money) and not amounts(money) & prices[key]:
            issues.append(f"preço errado para {key}: {money.upper()}")
    return issues


def _asks_for_secret(folded: str) -> bool:
    """"você vai informar o IP no formulário" says where the data goes; it asks nothing here."""
    for match in _affirmed(SECRET_REQUEST_RE, folded):
        if folded[:match.start()].endswith("seguro "):
            continue  # the lead's question, "é seguro passar a senha?"
        sentence = _sentence(folded, match.start())
        if "formulario" not in sentence or re.search(r"\b(?:me|pra mim)\b", sentence):
            return True
    return False


def link_sent(context: dict[str, Any], sent_texts: list[str] | tuple = ()) -> bool:
    """The /antes link already reached the lead (record or an agent message)."""
    lead = (context or {}).get("lead") or {}
    record = (lead.get("registros") or {}).get("link_enviado") or lead.get("link_enviado")
    return fold(str(record or "")).strip() == "sim" or any("instalador.talles.dev/antes" in fold(t) for t in sent_texts or [])


def price_without_link(parts: list[str], context: dict[str, Any]) -> bool:
    """TSX-78: the installation price in a draft without the /antes link (before the purchase)."""
    if purchased(context) or current_offer(context) in NO_PRICE_OFFERS or (current_offer(context) == "raiox" and not disqualified(context)):
        return False
    folded = fold("\n".join(re.sub(r"\[\[.*?\]\]", "", part) for part in parts or []))
    return bool(_affirmed(INSTALL_PRICE_RE, folded)) and "instalador.talles.dev/antes" not in folded


def with_price_cta(parts: list[str], toque: bool = False) -> list[str]:
    """Add the link and the next-step question to a price turn (a new message, or the last one)."""
    parts = [str(part) for part in parts or []]
    if not parts:
        return [PRICE_CTA]
    if toque or len(parts) >= 3:
        last = parts[-1]
        directives = "".join(re.findall(r"\s*\[\[.*?\]\]", last, re.DOTALL))
        body = re.sub(r"\s*\[\[.*?\]\]", "", last, flags=re.DOTALL).rstrip()
        # A question that is not the next step gives way to the link's question.
        if body.endswith("?") and not toque:
            body = re.split(r"(?<=[.!])\s+(?=[^.!?]*\?$)", body)[0] if re.search(r"[.!]\s", body) else body
        return parts[:-1] + [f"{body} {PRICE_CTA}".strip() + directives]
    return parts + [PRICE_CTA]


def check(parts: list[str], context: dict[str, Any], lead_texts: list[str], sent_texts: list[str] | tuple = ()) -> list[str]:
    """Hard violations in a draft. Each item says what is wrong, in Portuguese.

    Most checks hold for any offer and before the offer is known; prices are
    checked against the offer of the conversation (both offers when unknown).
    `sent_texts` are the agent's messages the lead already received.
    """
    context = context or {}
    text = "\n".join(parts or [])
    folded = fold(text)
    offer = current_offer(context)
    bought = purchased(context)
    lead_folded = fold(" ".join(lead_texts or []) + " " + json.dumps(context.get("lead") or {}, ensure_ascii=False))
    issues = forbidden_hits(folded, lead_folded)
    for match in THIRD_PERSON_RE.finditer(folded):
        if match.group(0) not in lead_folded:
            issues.append(f"fala do lead em 3ª pessoa (\"{match.group(0)}\"): fale com ele, \"você\"/\"seu\"/\"sua\"")
            break
    if offer not in ("raiox", *NO_PRICE_OFFERS) and not bought and "instalador.talles.dev/antes" not in folded and not link_sent(context, sent_texts) \
            and _affirmed(OTHER_TIME_RE, folded):
        issues.append("oferece outro momento antes de o link /antes ter saído")
    allowed_ai = re.sub(r"\s+", " ", folded)
    for phrase in AI_OFFER_PHRASES:
        allowed_ai = allowed_ai.replace(phrase, " ")
    bare = BARE_AI_NAME_RE.search(allowed_ai)
    if bare:
        issues.append(f"nome de IA solto (\"{bare.group(0)}\"): diga \"o plano pago do ChatGPT\", \"o ChatGPT Plus\" ou \"a Conta do Gemini\"")

    ofertas = context.get("ofertas") or {}
    if offer == "raiox":
        allowed = offer_amounts(ofertas, "raiox")
        if disqualified(context):
            # Degrau de entrada (decisão do Talles, 06/10): o desqualificado do Raio-X pode ouvir a instalação.
            allowed |= offer_amounts(ofertas, "instalador", upper_steps=False)
    elif offer == "instalador":
        allowed = offer_amounts(ofertas, "instalador", upper_steps=bought)
    elif offer in NO_PRICE_OFFERS:
        allowed = set()
        if MONEY_RE.search(folded):
            issues.append("preço na conversa do Atendente de IA (não existe preço na conversa: o Talles apresenta a proposta na conversa de 20 min)")
    else:
        allowed = offer_amounts(ofertas, "instalador", upper_steps=False) | offer_amounts(ofertas, "raiox")
    if allowed:
        issues += _price_issues(folded, allowed, {v for t in lead_texts or [] for v in amounts(t)})
        issues += _product_price_issues(folded, ofertas)

    if offer in NO_PRICE_OFFERS and URL_RE.search(text):
        issues.append("link na conversa do Atendente de IA (o próximo passo é a conversa de 20 min com o Talles, não um link)")
    for url in URL_RE.findall(text):
        host = urlparse(url if "://" in url else "https://" + url).netloc.lower().removeprefix("www.")
        if host not in INSTALLER_HOSTS:
            issues.append(f"link fora da oferta: {url}")
    if _asks_for_secret(folded):
        issues.append("pede senha, token ou dados do servidor na conversa (só pelo formulário cifrado)")
    if _affirmed(REVENUE_PROMISE_RE, folded):
        issues.append("promessa de faturamento ou vendas")
    # Atendimento: no special condition either since 09/10 22h (price only in the call: 12k or 6k by the calendar).
    if _affirmed(DISCOUNT_RE, folded):
        issues.append("desconto ou cupom (não existe)")
    if _affirmed(CONTACT_PROMISE_RE, folded):
        issues.append("promete contato numa data (o agente não agenda contato; o próximo passo vai para o registro)")
    if _affirmed(GEMINI_DURATION_RE, folded):
        issues.append("promete por quanto tempo a Conta do Gemini dura")
    if COPIAR_SWAP_RE.search(folded):
        issues.append("troca a implantação do Raio-X pelo Copiar a minha operação (são dois produtos)")
    if offer not in ("raiox", *NO_PRICE_OFFERS):
        # The link's host ("instalador.talles.dev") is not "instalado amanhã".
        no_urls = URL_RE.sub(" ", folded)
        if any(int(m.group(1) or 0) < 48 for m in _affirmed(FAST_DEADLINE_RE, no_urls)):
            issues.append("prazo errado: a instalação é em até 48 h depois do formulário completo")
        if _affirmed(VIDEO_RE, folded):
            issues.append("diz que existe vídeo (hoje não há)")
        if RAIOX_PROOF_RE.search(folded):
            issues.append("número de case do Raio-X fora do Raio-X")
        if any(not re.search(r"atendimento no whatsapp|3\.000", _sentence(folded, m.start()))
               for m in _affirmed(WHATSAPP_SERVICE_RE, folded)):
            issues.append("instalação vendida como atendimento no WhatsApp (isso é o Atendimento no WhatsApp, R$ 3.000, separado)")
    if offer == "instalador" and not bought and UPPER_STEP_RE.search(folded):
        issues.append("Raio-X ou Copiar a minha operação antes da compra da instalação")
    return issues


# Credentials a lead pasted never go to a model or a log. The bridge does this
# before anything else (bridge-src/sdr.py, same rules); the brain repeats it on
# what it reads back from Chatwoot.
CREDENTIAL_MARK = "[credencial removida]"
_CREDENTIAL_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)", re.S),
    re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}"),                       # Telegram bot token
    re.compile(r"\b(?:sk|pk|ghp|gho|xox[bp])[-_][A-Za-z0-9_-]{16,}"),   # API keys
    re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),                          # IPv4
)
_LABELED_SECRET_RE = re.compile(
    r"(?i)\b(senha|password|passwd|pass|pwd|token|chave|api[ _-]?key|usu[aá]rio|user|login)"
    r"((?:\s+d[oae]\s+\w+)?(?:\s*[:=]\s*|\s+(?:é|e|eh)\s+|\s+))([^\s,;]+)"
)


def _looks_secret(value: str, separator: str) -> bool:
    if ":" in separator or "=" in separator:
        return True
    return bool(re.search(r"\d|[^\w]", value)) or (len(value) >= 6 and value != value.lower() and value != value.upper())


def redact_credentials(text: str) -> tuple[str, bool]:
    """Replace credentials in a lead message by CREDENTIAL_MARK. Returns (text, found)."""
    found = False
    result = text or ""
    for pattern in _CREDENTIAL_PATTERNS:
        result, count = pattern.subn(CREDENTIAL_MARK, result)
        found = found or bool(count)

    def labeled(match: re.Match) -> str:
        nonlocal found
        label, separator, value = match.groups()
        value = value.rstrip(".!?")
        if CREDENTIAL_MARK.startswith(value) or not _looks_secret(value, separator):
            return match.group(0)
        found = True
        return f"{label}{separator}{CREDENTIAL_MARK}" + match.group(3)[len(value):]

    result = _LABELED_SECRET_RE.sub(labeled, result)
    return result, found


def spiced_state(records: dict[str, str], offer: str | None) -> dict[str, Any]:
    """Which SPICED letters are on record and which are still missing."""
    done = {letter: records[field] for letter, field in SPICED_FIELDS.items() if records.get(field)}
    missing = [letter for letter in SPICED_FIELDS if letter not in done]
    if offer == "instalador":
        for field in ("tem_vps", "tem_codex"):
            if not records.get(field):
                missing.append(f"D:{field}")
    return {"oferta": offer, "etapa": records.get("etapa_spiced"), "registrado": done, "faltando": missing,
            "proximo_passo": records.get("proximo_passo"), "proximo_passo_em": records.get("proximo_passo_em"),
            "comprou": records.get("comprou"), "perfil_raiox": records.get("perfil_raiox")}


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "soul":
        print("SOUL atualizado" if sync_soul(sys.argv[2]) else "SOUL já estava em dia")
    else:
        print(forbidden_list())
