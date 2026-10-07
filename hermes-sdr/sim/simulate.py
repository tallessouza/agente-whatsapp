import asyncio, json, os, sys, time, pathlib, httpx
import sdr, app
sdr.DB_PATH = pathlib.Path("/tmp/sim.db")
BRAIN = os.environ["SDR_BRAIN_URL"]; TOKEN = os.environ["SDR_BRAIN_TOKEN"]
LLM = "http://omniroute_omniroute:20129/v1"; KEY = os.environ["SIM_LLM_KEY"]
MODEL = os.environ.get("SIM_MODEL", "agy/gemini-3.7-flash-high")
MAX_TURNS = int(os.environ.get("SIM_TURNS", "16"))
PERSONA = open("/tmp/persona.md", encoding="utf-8").read()
FIRST = os.environ.get("SIM_FIRST", "E aí! Sou o @marina.escala e quero saber mais sobre o Raio-X")

async def persona_reply(transcript):
    messages = [{"role": "system", "content": PERSONA}]
    for row in transcript:
        messages.append({"role": "assistant" if row["autor"] == "lead" else "user", "content": row["texto"]})
    async with httpx.AsyncClient(timeout=90) as c:
        r = await c.post(f"{LLM}/chat/completions", headers={"Authorization": f"Bearer {KEY}"},
                         json={"model": MODEL, "messages": messages, "temperature": 0.8})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip().strip('"')

async def main():
    conv = 990500 + int(time.time()) % 1000
    session = f"test:sim:{int(time.time())}"
    sdr.remember_lead(conv, "sim", FIRST)
    if os.path.exists("/tmp/ficha.json"):
        sdr.set_profile(conv, json.load(open("/tmp/ficha.json", encoding="utf-8")))
    transcript, lead_msg = [], FIRST
    for turn in range(1, MAX_TURNS + 1):
        transcript.append({"autor": "lead", "texto": lead_msg})
        print(f"\n[{turn}] LEAD: {lead_msg}", flush=True)
        reply = await app.ask_hermes(lead_msg, session, None, None, sdr.trusted_context(conv, []))
        parts, directives = sdr.parse_reply(reply)
        draft = list(parts)
        if not parts:
            print("    (silêncio: nada enviado; fim da simulação)", flush=True)
            break
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                rv = (await c.post(f"{BRAIN}/review", headers={"Authorization": f"Bearer {TOKEN}"}, json={
                    "conversation_id": conv, "jid": "sim", "lead_message": lead_msg, "draft_parts": parts,
                    "directives": directives, "context": sdr.context_payload(conv), "transcript": transcript})).json()
        except Exception as e:
            rv = {"decision": f"erro {e!r}"}
        decision = rv.get("decision")
        if decision == "reescrever":
            print("    (revisor reescreveu: " + rv.get("motivo", "") + ")\n    rascunho: " + " / ".join(parts)[:400], flush=True)
            new_parts, nd = sdr.parse_reply("[[QUEBRA]]".join(map(str, rv.get("parts") or parts)))
            parts, directives = new_parts, (nd or directives)
        elif decision == "bloquear":
            print("    (revisor BLOQUEOU: " + rv.get("motivo", "") + ")\n    rascunho: " + " / ".join(parts)[:400], flush=True)
            parts, directives = [sdr.FALLBACK_REPLY], [{"type": "escalar", "motivo": rv.get("motivo", ""), "frase": lead_msg}]
        sdr.record_correction(conv, draft, parts, "review")
        leaks = sdr.leaked_terms(parts)
        if leaks:
            print(f"    (GUARDRAIL: {leaks})", flush=True)
        for p in parts:
            print(f"    AGENTE: {p}", flush=True)
            transcript.append({"autor": "agente", "texto": p})
        for d in directives:
            if d["type"] == "registro":
                with sdr.connect() as c:
                    c.execute("INSERT INTO sdr_records VALUES (?,?,?,?)", (conv, d["campo"], d["valor"], time.time()))
        shown = [f"{d['type']}:{d.get('campo') or d.get('motivo') or d.get('nome')}={d.get('valor','')}" for d in directives]
        if shown:
            print("    [diretivas] " + "; ".join(shown), flush=True)
        if any(d["type"] == "escalar" for d in directives):
            print("\n== escalou para o Talles; fim da simulação ==")
            break
        lead_msg = await persona_reply(transcript)
    json.dump(transcript, open("/tmp/sim_transcript.json", "w"), ensure_ascii=False, indent=1)

asyncio.run(main())
