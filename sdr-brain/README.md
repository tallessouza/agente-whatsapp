# sdr-brain

Serviço FastAPI do SDR (Python 3.13, porta 8090). Estado SQLite fica em `/data` e é persistido entre reinícios.

| Variável | Uso | Padrão |
|---|---|---|
| `SDR_BRAIN_TOKEN` | Bearer token obrigatório nas rotas protegidas | sem padrão (503) |
| `SDR_BRAIN_DB` | arquivo SQLite | `/data/sdr-brain.db` |
| `SDR_BRAIN_LLM_URL`, `SDR_BRAIN_LLM_KEY`, `SDR_BRAIN_MODEL` | endpoint, chave e modelo OpenAI-compatible | OmniRoute / `agy/gemini-3.7-flash-low` |
| `BRIDGE_URL` | URL da bridge | `http://integration_bridge:8080` |
| `CHATWOOT_URL`, `CHATWOOT_ACCOUNT_ID`, `CHATWOOT_API_TOKEN` | transcript | `http://chatwoot_rails:3000` |
| `OPENREPLY_DSN` | Postgres somente leitura | vazio (desabilitado) |
| `META_GRAPH_TOKEN`, `IG_BUSINESS_ID` | Business Discovery opcional | vazio (desabilitado) |
| `SDR_STEP_DUE_HOUR` | hora local em que vence um próximo passo datado sem hora (`proximo_passo_em = AAAA-MM-DD`) | `10` |
| `SDR_STEP_ACTIVITY_DELAY` | segundos de espera para juntar `proximo_passo` e `proximo_passo_em` numa linha "📌 Próximo passo" no Chatwoot | `3` |

Os fatos das ofertas não ficam aqui: chegam em `context.ofertas`, que a bridge lê de `hermes-sdr/ofertas.json`. `oferta.py` gera a lista de fatos para o revisor e faz a verificação automática, nas duas ofertas e sem oferta (preço inexistente ou errado para o produto, link fora da oferta, pedido de senha ou dado do servidor, promessa de faturamento, desconto, promessa de contato, prazo abaixo de 48 h, vídeo, números de case do Raio-X fora do Raio-X, Raio-X antes da compra, instalação vendida como atendimento no WhatsApp, troca dos dois produtos de R$ 48.000, nomes e frases proibidos, fala do lead em 3ª pessoa, "outro momento" antes de o link `/antes` sair, nome de IA solto); o que sobrar depois do modelo vira `bloquear`. Um valor que o lead disse só passa como o custo DELE ("você paga R$ 2.000"), nunca como preço nosso. `check` recebe também as mensagens que o agente já mandou, para saber se o link já saiu.

Preço da instalação sem o link (`price_without_link`) não bloqueia: depois da decisão do modelo, `app.enforce_price_cta` acrescenta "O caminho é por aqui https://instalador.talles.dev/antes. Consegue fazer hoje?" (`oferta.with_price_cta`), mesmo com o modelo fora, e `app.reconcile_link_record` acerta o registro `link_enviado` numa reescrita (TSX-78).

O follow-up (`followup_once`) recomeça a sequência quando o lead responde e o agente responde de volta (decisão de 07/10): a âncora vira a última mensagem do agente e 5min, 30min e 2h valem de novo.

A lista de proibidos existe só em `oferta.py`: o revisor e o FUP a recebem por `{{PROIBIDOS}}`, e o SOUL é atualizado com `python oferta.py soul ../hermes-sdr/SOUL.md` (um teste falha se o SOUL divergir).

Rotas: `GET /health` (sem autenticação), `POST /review`, `POST /events/exchange`, `POST /events/lead` e `POST /events/record` (Bearer obrigatório).

Para executar: `pip install -r requirements.txt && SDR_BRAIN_TOKEN=dev uvicorn app:app --port 8090`. Para testar: `python -m unittest -v` ou `sudo docker build -t sdr-brain:dev sdr-brain && sudo docker run --rm sdr-brain:dev python -m unittest -v`.
