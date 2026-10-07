# Topologia do agente de vendas no WhatsApp

> **Para que serve:** mostrar o que roda, onde, em qual rede e porta, quem fala com quem, onde mora cada estado e o que para quando um serviço cai.
> **Data:** 07/10/2026. Retrato de produção da VM1 (bridge `sdr-v13`, brain `sdr-brain:v3`, OpenReply `sdr-v2`, sessões `wa:v13:`).
> **Fontes:** o código deste repositório, `docs/_fatos-vm.md` (coletado em 07/10 às 05:20Z), `stacks/*.yml` e, como referência, `../MAPA-INTEGRACOES.md`. O que não deu para confirmar no código está marcado como **não verificado**.

Este documento não contém valor de segredo. As variáveis aparecem só pelo nome.

---

## 1. Visão geral

O caminho de um lead tem duas partes:

1. **Frente, no Instagram.** O OpenReply responde ao comentário com uma DM que leva um link rastreado. O clique abre o `wa.me` com o @ do lead já preenchido.
2. **Conversa, no WhatsApp.** O fluxo passa por Evolution Go, bridge e Chatwoot, onde ficam o espelho e o atendimento humano. Depois vêm o Hermes (o agente), o OmniRoute (os modelos) e o sdr-brain (revisor, supervisor, enriquecimento e follow-up).

O princípio, que está em `hermes-sdr/ARQUITETURA.md` e o código confirma:

- **O Hermes só conversa.** Ele não tem ferramenta de sistema: `hermes/volume-politica/config.yaml` deixa só `web`, `vision` e `clarify` e desliga `terminal`, `file`, `skills` etc.
- **A bridge executa.** Ela cuida de transporte, diretivas, guardrail e fila.
- **O sdr-brain julga fora da conversa.**

```mermaid
flowchart LR
    subgraph internet["Internet"]
        IG["Instagram / Meta Graph API"]
        WA["WhatsApp do lead"]
        OWNER["WhatsApp do Talles"]
        OP["Operador no navegador"]
    end

    subgraph host["Rede host da VM1"]
        TRAEFIK["traefik_traefik 80/443"]
    end

    subgraph orpub["openreply_public"]
        ORWEB["openreply_web :3000"]
    end

    subgraph orint["openreply_internal"]
        ORWORKER["openreply_worker"]
        ORCRON["openreply_cron"]
        ORPG[("openreply_postgres")]
        ORREDIS[("openreply_redis")]
    end

    subgraph ai["ai_stack (overlay)"]
        EVO["evogo_evolution :4000"]
        EVOPG[("evogo_postgres")]
        BRIDGE["integration_bridge :8080"]
        CWR["chatwoot_rails :3000"]
        CWS["chatwoot_sidekiq"]
        CWPG[("chatwoot_postgres")]
        CWREDIS[("chatwoot_redis")]
        HERMES["hermes_hermes :8642"]
        BRAIN["sdr_brain :8090"]
        OMNI["omniroute_omniroute :20128/:20129"]
        OMNIREDIS[("omniroute_redis")]
    end

    IG -->|"webhook de comentário e DM"| TRAEFIK
    TRAEFIK -->|"openreply.talles.dev"| ORWEB
    ORWEB --> ORREDIS
    ORREDIS --> ORWORKER
    ORWORKER -->|"DM com link /r/slug?t="| IG
    ORWEB --> ORPG
    ORWORKER --> ORPG
    ORCRON -->|"http://web:3000"| ORWEB
    ORWEB -->|"clique: 302 para wa.me com o @"| WA
    WA <-->|"sessão do número"| EVO
    EVO --> EVOPG
    EVO -->|"POST /evolution/webhook"| BRIDGE
    BRIDGE -->|"/send/text, /send/media, /message/presence"| EVO
    BRIDGE -->|"API de contatos, mensagens, labels"| CWR
    CWR --> CWPG
    CWR --> CWREDIS
    CWS --> CWREDIS
    CWS -->|"webhook do inbox, POST /chatwoot/webhook"| BRIDGE
    BRIDGE -->|"POST /v1/chat/completions"| HERMES
    HERMES -->|"agy/gemini-3.7-flash-high"| OMNI
    OMNI --> OMNIREDIS
    BRIDGE -->|"/review e /events/*"| BRAIN
    BRAIN -->|"/sdr/* (orientação, escalação, ficha, toques)"| BRIDGE
    BRAIN -->|"agy/gemini-3.7-flash-low"| OMNI
    BRAIN -->|"transcrição, atividades, atributos"| CWR
    BRAIN -->|"SELECT somente leitura"| ORPG
    BRAIN -->|"Business Discovery"| IG
    EVO -->|"alerta de escalação"| OWNER
    OP -->|"chatwoot.talles.dev"| TRAEFIK
    TRAEFIK --> CWR
```

O `sdr_brain` está em duas redes, `ai_stack` e `openreply_internal`, e é a única ponte entre o lado do WhatsApp e o banco do OpenReply (`stacks/sdr-stack.yml`, `docs/_fatos-vm.md`). O OpenReply não fala com a bridge. A ligação entre os dois lados é o texto pré-preenchido do `wa.me`, mais a leitura que o brain faz do banco do OpenReply.

---

## 2. Serviços

Os dados vêm de `docs/_fatos-vm.md`. A coluna "Papel" foi confirmada no código.

| Serviço (Swarm) | Imagem em produção | Redes | Porta publicada no host | Papel |
|---|---|---|---|---|
| `evogo_evolution` | `evoapicloud/evolution-go:latest` | ai_stack | 4000 | Transporte do WhatsApp, instância `whatsapp` (`EVOLUTION_INSTANCE` em `stacks/bridge-stack.yml`). Uma réplica só: duas disputariam a sessão (MAPA, item 5). |
| `evogo_postgres` | `postgres:16` | ai_stack | não | Banco da Evolution: autenticação e mensagens (`DATABASE_SAVE_MESSAGES: "true"` em `stacks/evogo-stack.yml`). |
| `integration_bridge` | `evolution-chatwoot-bridge:sdr-v13` | ai_stack | não (escuta 8080 só na overlay, `bridge-src/Dockerfile`) | FastAPI que liga Evolution, Chatwoot, Hermes e sdr-brain (`bridge-src/app.py`, `sdr.py`, `handover.py`). |
| `chatwoot_rails` | `chatwoot/chatwoot:v4.18.0` | ai_stack | 3001 para 3000 | Inbox humana, histórico, labels, atributos. Conta 1, inbox 1 (`CHATWOOT_INBOX_ID` padrão `"1"` em `app.py`). |
| `chatwoot_sidekiq` | `chatwoot/chatwoot:v4.18.0` | ai_stack | não | Jobs do Chatwoot. Que é ele quem dispara o webhook do inbox para a bridge: **não verificado** (é o comportamento padrão do Chatwoot). |
| `chatwoot_postgres` / `chatwoot_redis` | `pgvector/pgvector:pg16` / `redis:7-alpine` | ai_stack | não | Banco e fila do Chatwoot. |
| `chatwoot_prepare` | `chatwoot/chatwoot:v4.18.0` | ai_stack | não | Roda `db:chatwoot_prepare` e sai. 0/1 é o estado normal. |
| `hermes_hermes` | `hermes-agent:latest` | ai_stack | **8642** | O agente. API compatível com OpenAI em `/v1/chat/completions` (`stacks/hermes-stack.yml`: `API_SERVER_ENABLED`, `API_SERVER_PORT`). |
| `hermes_teste_hermes` | `hermes-agent:latest` | ai_stack | não | Hermes de teste para simulação, com volume próprio (`agente-sdr/DEPLOY.md`, passo 1). |
| `sdr_brain` | `sdr-brain:v3` | ai_stack, openreply_internal | não | Revisor, supervisor, enriquecimento, `lead_steps` e follow-up (`sdr-brain/app.py`). Escuta 8090 (`sdr-brain/Dockerfile`). |
| `sdr_teste_brain` | `sdr-brain:v3` | ai_stack | não | Brain de teste. Sem acesso ao OpenReply. |
| `omniroute_omniroute` | `diegosouzapw/omniroute:latest` | ai_stack | 20128 (painel), 20129 (API) | Roteador de LLM, usado pelo Hermes e pelo brain. As contas Antigravity com OAuth estão descritas em `hermes-sdr/ARQUITETURA.md`, "LLM e cota" (não aparecem no código). |
| `omniroute_redis` | `redis:7-alpine` | ai_stack | não | Estado do OmniRoute. |
| `openreply_web` | `openreply:sdr-v2` | openreply_internal, openreply_public | 3000 | Painel, webhook da Meta e rota de clique `/r/[slug]` (`openreply/patches/0001`, `0002`). |
| `openreply_worker` | `openreply:sdr-v2` | openreply_internal | não | Processa comentários e DMs da fila e envia a DM com o link (`lib/queue/dm-worker.ts` no patch 0001). |
| `openreply_cron` | `openreply:sdr-v2` | openreply_internal | não | `scripts/cron.sh` chama o web em `CRON_BASE_URL=http://web:3000` (`stacks/openreply-stack.yml`). |
| `openreply_migrate` | `openreply:sdr-v2` | openreply_internal | não | Migrações Prisma. Roda e sai (0/1). |
| `openreply_postgres` / `openreply_redis` | `postgres:16` / `redis:7-alpine` (appendonly) | openreply_internal | não | Banco e fila (BullMQ) do OpenReply. |
| `traefik_traefik` | `traefik:v3` | host | 80/443 no IP público | Borda HTTPS (`stacks/traefik-stack.yml`, rotas em `stacks/traefik-dynamic.yml`). |
| `vaultwarden_vaultwarden` | `vaultwarden/server:latest` | vaultwarden_default | 8088 para 80 | Cofre. Fora do fluxo do agente. |

**Cuidado com os arquivos de stack do repositório.** Eles são o ponto de partida, não o retrato exato de produção:

- `stacks/bridge-stack.yml` traz a imagem `:latest`, não monta `/sdr`, `/hermes-data` nem o cache do STT e não tem nenhuma variável `SDR_*` nem `HERMES_*` além de URL, chave e modelo. Em produção a bridge monta os quatro volumes listados em `_fatos-vm.md`.
- `stacks/hermes-stack.yml` não monta `hermes_policy`, que em produção está montado somente leitura em `/opt/hermes-policy`.
- `stacks/openreply-stack.yml` usa `openreply:5760181`, mas em produção a imagem é `sdr-v2`.
- As variáveis de ambiente completas dos serviços em produção não estão no repositório: **não verificado** (veja a seção 7).

---

## 3. Redes Docker

| Rede | Tipo | Quem está nela | Para quê |
|---|---|---|---|
| `ai_stack` | overlay externa (`external: true` em todas as stacks) | Evolution, bridge, Chatwoot, Hermes (prod e teste), sdr-brain (prod e teste), OmniRoute | Todo o tráfego interno do agente. Os nomes resolvem pelo nome completo do serviço (`chatwoot_rails`, `omniroute_omniroute`, `integration_bridge`, `sdr_brain`). `hermes-sdr/ARQUITETURA.md` avisa que os nomes curtos resolvem para mais de uma stack. A exceção que funciona em produção é o webhook da Evolution, que usa `http://bridge:8080` (`stacks/evogo-stack.yml`). |
| `openreply_internal` | externa, `name: openreply_internal` | os seis serviços do OpenReply e o `sdr_brain` | Banco, fila e cron do OpenReply. O brain lê o Postgres por `OPENREPLY_DSN`, com o papel somente leitura `sdr_brain_ro`. O nome do papel e as permissões (SELECT em `DmLog`, `Automation`, `WebhookEvent`, `LinkClick`) vêm de `hermes-sdr/ARQUITETURA.md`. O `GRANT` não está no repositório: **não verificado**. |
| `openreply_public` | externa, `name: openreply_public` | `openreply_web` | Rede "pública" do web. Na prática, o tráfego externo chega pela porta 3000 publicada no host, via Traefik. |
| `host` | rede host do Docker | `traefik_traefik` | O Traefik escuta 80 e 443 no IP público e encaminha para `127.0.0.1:<porta>` dos serviços (`stacks/traefik-dynamic.yml`). |
| `vaultwarden_default` | da stack do Vaultwarden | `vaultwarden_vaultwarden` | Fora do fluxo. |

Portas publicadas em modo host (3000, 3001, 4000, 8642, 20128, 20129, 8088) abrem em todas as interfaces da VM. Só o Traefik se prende ao IP público (`--entrypoints.*.address`). Se elas ficam inacessíveis de fora depende do firewall da VM: **não verificado**. Atenção ao Hermes (8642) e ao OmniRoute (20129): os dois servem API e não têm domínio no Traefik.

---

## 4. Domínios públicos

Rotas em `stacks/traefik-dynamic.yml`, todas no entrypoint `websecure` com certificado Let's Encrypt (`traefik_certificates`):

| Domínio | Destino | Quem usa |
|---|---|---|
| `openreply.talles.dev` | `127.0.0.1:3000`, `openreply_web` | Webhook da Meta (`/api/webhook`), link rastreado `/r/<slug>?t=...` e painel. É `NEXTAUTH_URL`, base dos links (`buildTrackedUrl` em `lib/tracking/message.ts`). |
| `chatwoot.talles.dev` | `127.0.0.1:3001`, `chatwoot_rails` | Painel do operador. Também é o link do alerta de escalação (`CHATWOOT_PUBLIC_URL` em `sdr.py`, `escalation_alert`). |
| `evolution.talles.dev` | `127.0.0.1:4000`, `evogo_evolution` | Painel da Evolution. A raiz dá 404, o que é normal (MAPA, seção 3). |
| `omni.talles.dev` | `127.0.0.1:20128`, painel do OmniRoute | Operação da cota e das contas. |
| `manager.talles.dev` | `https://127.0.0.1:9443`, Portainer | Operação do Swarm. |
| `vault.talles.dev` | Vaultwarden | Não aparece em `traefik-dynamic.yml`. A rota vem de outro lugar (provavelmente labels do Swarm): **não verificado**. |

O WhatsApp do agente é o número `554825000259`, destino do `wa.me` (`hermes-sdr/ARQUITETURA.md`, "OpenReply: link por destinatário"). O Hermes, a bridge e o brain não têm domínio público.

---

## 5. Quem fala com quem

| De | Para | Endereço | Autenticação | Onde está no código |
|---|---|---|---|---|
| Meta | OpenReply web | `https://openreply.talles.dev/api/webhook` | assinatura com `FACEBOOK_APP_SECRET`, verificação com `WEBHOOK_VERIFY_TOKEN` | fora deste repositório (OpenReply base `5760181`). Detalhes no MAPA, item 1. |
| OpenReply worker | Meta Graph | API do Instagram (`META_GRAPH_API_VERSION: v25.0`) | token da conta IG, cifrado no banco com `ENCRYPTION_KEY` | `lib/queue/dm-worker.ts`, `lib/meta/client.ts` (`getUserUsername`), patch 0001 |
| Lead (navegador) | OpenReply web | `/r/<slug>?t=<base64url(IGSID)>.<hmac16>` | HMAC-SHA256 de `slug:IGSID` com `NEXTAUTH_SECRET`, cortado em 16 caracteres | `lib/tracking/recipient.ts` (`signRecipient`, `verifyRecipient`), `app/r/[slug]/route.ts` |
| Evolution | bridge | `POST http://bridge:8080/evolution/webhook` | `Authorization: Bearer BRIDGE_WEBHOOK_TOKEN`, **só se a variável existir**. O `WEBHOOK_URL` da Evolution não manda cabeçalho, então provavelmente ela está vazia: **não verificado**. | `app.py`, `evolution_webhook` |
| bridge | Evolution | `{EVOLUTION_URL}/send/text`, `/send/media`, `/message/presence` e os fallbacks clássicos `/message/sendMedia/{instance}` e `/message/send<Kind>/{instance}` | cabeçalho `apikey: EVOLUTION_API_KEY` | `send_evolution`, `send_evolution_media`, `send_evolution_native`, `send_presence` |
| bridge | Chatwoot | `POST /public/api/v1/inboxes/{CHATWOOT_INBOX_IDENTIFIER}/contacts` e `/api/v1/accounts/{id}/conversations`, mensagens, labels, `custom_attributes` | `api_access_token` (`CHATWOOT_API_ACCESS_TOKEN` na API pública, `CHATWOOT_APP_TOKEN` na API de conta) | `ensure_conversation`, `add_chatwoot_message`, `sdr._chatwoot`, `handover.labels` |
| Chatwoot | bridge | `POST /chatwoot/webhook` (evento `message_created`, só `outgoing`) | o mesmo `BRIDGE_WEBHOOK_TOKEN` opcional | `chatwoot_webhook`. A URL configurada no inbox (`http://bridge:8080/chatwoot/webhook`) vem do MAPA, item 17. |
| bridge | Hermes | `POST {HERMES_URL}/chat/completions` (`http://hermes_hermes:8642/v1`) | `Authorization: Bearer HERMES_API_KEY` (= `API_SERVER_KEY` do Hermes), sessão no cabeçalho `X-Hermes-Session-Id` | `ask_hermes` |
| Hermes | OmniRoute | `http://omniroute_omniroute:20129/v1`, provider `custom` | `${OMNIROUTE_API_KEY}` no `config.yaml` | `hermes/volume-dados/config.yaml`, `model.base_url` |
| bridge | sdr-brain | `POST {SDR_BRAIN_URL}/review`, `/events/lead`, `/events/exchange`, `/events/record` | `Authorization: Bearer SDR_BRAIN_TOKEN` | `review_reply`, `brain_event` |
| sdr-brain | bridge | `{BRIDGE_URL}/sdr/guidance`, `/sdr/escalate`, `/sdr/lead-profile`, `/sdr/followups`, `GET /sdr/conversations/{id}` | o mesmo Bearer `SDR_BRAIN_TOKEN` | `bridge_post`, `followup_once`. Na bridge, `_sdr_auth` responde 503 sem token e 401 com token errado. |
| sdr-brain | OmniRoute | `{SDR_BRAIN_LLM_URL}/chat/completions` | `SDR_BRAIN_LLM_KEY` | `ask_llm` |
| sdr-brain | Chatwoot | mensagens (transcrição), `message_type: activity`, atributos de conversa e de contato, definições de atributo | `CHATWOOT_API_TOKEN` | `chatwoot_messages`, `crm.activity`, `crm.set_conversation_attributes`, `crm.update_contact` |
| sdr-brain | Postgres do OpenReply | `OPENREPLY_DSN` (psycopg) | papel somente leitura | `enrichment.window_candidates`, `enrichment.openreply_history` |
| sdr-brain | Meta Graph | `https://graph.facebook.com/{META_GRAPH_VERSION}/{IG_BUSINESS_ID}?fields=business_discovery...` | `META_GRAPH_TOKEN` | `enrichment.business_discovery` |
| sdr-brain | Apify (opcional) | `run-sync-get-dataset-items` | `APIFY_TOKEN` (vazio desliga) | `enrichment.apify_profile` |
| bridge | WhatsApp do Talles | via Evolution, para `SDR_NOTIFY_NUMBER` | não se aplica | `escalate`, `owner_test_command` |

---

## 6. Volumes e onde mora cada estado

### 6.1 Volumes

| Volume | Montado em | O que guarda | Tem dado de lead? |
|---|---|---|---|
| `evolution_chatwoot_bridge` | bridge `/data` | `bridge.db` (SQLite em WAL) e `/data/media/` (mídias recebidas e de saída, nomeadas por `sha256(jid:id)`, `remember_media`, mais as `outbox-*` de envio pendente) | **Sim.** Telefone (JID), texto redigido, mídias brutas, registros, ficha do Instagram. As mídias não têm limpeza no código. |
| `hermes_chatwoot_data` | Hermes `/opt/data`. Também na bridge em `/hermes-data`, somente leitura. | `SOUL.md` (444, uid 10000), `config.yaml`, `backups/`, banco de sessões do Hermes. O nome e o caminho exato do banco (`state.db`, padrão do Hermes) **não foram verificados**. | **Sim.** O histórico completo de cada sessão `wa:v13:<jid>`. A bridge só lê esse volume para resolver `MEDIA:` (`extract_hermes_media`, `HERMES_MEDIA_ROOT`). |
| `hermes_policy` | Hermes `/opt/hermes-policy` (somente leitura) | política: toolsets e aprovações (`hermes/volume-politica/config.yaml`) | Não. |
| `hermes_teste_data` | Hermes de teste `/opt/data` | o mesmo, para simulação | Só conversas de teste. |
| bind `~/orca/projects/portainer-install/hermes-sdr` | bridge `/sdr` (somente leitura) | `ofertas.json`, `capacidade.json`, `midia/` + `descricoes.json`, SOUL de referência, `sim/` | Não. As personas de `sim/` são fictícias. Mudar `capacidade.json`, `ofertas.json` ou `midia/` vale no turno seguinte, sem redeploy (`hermes-sdr/README.md`). |
| `integration_bridge_stt_cache` | bridge `/root/.cache` | modelo do faster-whisper (`BRIDGE_STT_MODEL=small`) | Não. |
| `sdr_sdr_brain_data` | brain `/data` | `sdr-brain.db` | **Sim.** Mensagens do lead e do agente nos `events`, @ do Instagram, perfis, próximos passos. |
| `sdr_teste_brain_data` | brain de teste `/data` | o mesmo | Só testes. |
| `chatwoot_postgres` | Postgres do Chatwoot | contatos, conversas, mensagens, notas privadas, labels, atributos `sdr_*`, `spiced_*`, `ig_*` | **Sim.** É a cópia legível de tudo. |
| `chatwoot_storage` | rails e sidekiq `/app/storage` | anexos (ActiveStorage) | **Sim.** Áudios, imagens e documentos do lead. |
| `chatwoot_redis` | Redis do Chatwoot | filas do Sidekiq, cache | Transitório. Os payloads dos jobs podem ter texto: **não verificado**. |
| `evogo_postgres` | Postgres da Evolution | sessão/autenticação e mensagens salvas | **Sim.** Guarda o texto **original**, sem redação: a redação de credenciais acontece só na bridge. |
| `evogo_data`, `evogo_logs` | Evolution `/app/dbdata`, `/app/logs` | dados e logs da instância | Provavelmente. Conteúdo **não verificado**. |
| `omniroute_data`, `omniroute_redis` | OmniRoute | contas, chaves, roteamento. Se guarda prompts em log: **não verificado**. | Possível. |
| `openreply_postgres_data` | Postgres do OpenReply | `Automation`, `TrackedLink`, `DmLog` (nome e IGSID de quem comentou, texto do comentário), `LinkClick` (+ `recipientId`, `recipientName`, `ipHash`, `userAgent`), `WebhookEvent` | **Sim** (dados do Instagram). |
| `openreply_redis_data` | Redis do OpenReply (appendonly) | filas | Transitório. |
| `traefik_certificates` | Traefik `/letsencrypt` | `acme.json` (certificados e chaves TLS) | Não, mas é sensível. |
| `vaultwarden_data` | Vaultwarden | cofre | Não, mas guarda segredos. |

### 6.2 `bridge.db` (`/data/bridge.db`)

Todas as tabelas são criadas sob demanda em `app.db()`, `handover.connect()` e `sdr.connect()`.

| Tabela | Criada em | Chave | Guarda | Ciclo |
|---|---|---|---|---|
| `contacts` | `app.db` | `jid` | `source_id`, `conversation_id` (display id do Chatwoot), `internal_id` | `#teste` apaga a linha do dono para abrir conversa nova (`owner_test_command`). |
| `messages` | `app.db` | `external_id` (id da Evolution) | `chatwoot_id`, `created_at` | Deduplicação (`claim_message`). Linhas com mais de 24 h são apagadas a cada abertura do banco. |
| `event_history` | `app.db` | `external_id` | eventos de estado (recibo, reação, edição, revogação) com o **payload bruto** da Evolution (até 200 mil caracteres) | Sem limpeza. |
| `chatwoot_deliveries` | `app.db` | id da mensagem do Chatwoot | deduplicação do webhook do Chatwoot | Sem limpeza. |
| `media_history` | `app.db` | `external_id` | caminho do arquivo, mimetype, nome, jid | Sem limpeza. É lida por até `HERMES_MEDIA_HISTORY_SECONDS` (600 s) em `recent_local_media`. |
| `outbox` | `app.db` | `id` | envios à Evolution que falharam (`text`, `media`, `native:*`), `attempts`, `next_attempt`, `last_error` | `inflight` volta a `pending` no boot. Apagado ao enviar. Sem limite de tentativas. |
| `handovers` | `handover.connect` | `conversation` | `revision` (sobe a cada pausa), `pending_label` | Barreira local da pausa. |
| `handover_history` | `handover.connect` | `id` / `event` único | mensagens durante a pausa ou falha: papel `cliente`, `atendente_humano` ou `retomada_enviada` | `consumed=1` depois de um turno entregue (`handover.consumed`). |
| `bridge_outbound` | `handover.connect` | id gerado pela bridge | ids enviados pela API, para ignorar o eco da Evolution (`is_echo`) | Sem limpeza. |
| `sdr_records` | `sdr.connect` | sem chave, uma linha por registro | `[[REGISTRO]]` e registros automáticos (`oferta` da campanha, `mandou_credencial`, `perfil_raiox`) | Vale o último valor (`lead_state`). |
| `sdr_leads` | `sdr.connect` | `conversation` | `jid`, `origin` (JSON de `origin_from_text`), `first_seen` | Uma vez por conversa (`remember_lead`). |
| `sdr_guidance` | `sdr.connect` | `id` | orientações do supervisor | `consumed` preenchido depois de um turno entregue. |
| `sdr_profiles` | `sdr.connect` | `conversation` | a `ficha` do Instagram que o brain manda | Substituída a cada enriquecimento. |
| `sdr_followups` | `sdr.connect` | `id` | toques: `send_at`, `text`, `motivo`, `after_ts`, `stage`, `status` (`pending`, `sent`, `cancelled`), `reason`, `sent_at` | O despacho (30 s) decide. |
| `sdr_activity` | `sdr.connect` | `conversation` | `last_lead_ts`, `last_agent_ts` | Atualizada a cada mensagem do lead e a cada balão do agente. Toque não mexe. |
| `sdr_corrections` | `sdr.connect` | `id` | `draft` (o que o Hermes escreveu) e `sent` (o que saiu) | As 3 últimas vão no contexto (`CORRECTIONS_IN_CONTEXT`). |
| `sdr_owner_test` | `sdr.connect` | `jid` | `active`, `run`, `started` do modo teste do dono | `#teste` incrementa `run`, `#fim` desativa. |

### 6.3 `sdr-brain.db` (`/data/sdr-brain.db`)

| Tabela | Criada em | Guarda |
|---|---|---|
| `events` | `app.connection` | Todo evento recebido (`exchange`, `lead`, `record`) com o payload JSON. É de onde o supervisor tira os registros (`conversation_records`). |
| `tracked` | `app.connection` | Conversas acompanhadas pelo FUP (`jid`, `last_agent_ts`, `source_id`). Recarregada no boot (`load_tracked`). Some quando a bridge responde 404 (`forget_conversation`). |
| `sequences` | `app.connection` | Sequência de silêncio por conversa: `anchor` (o `last_agent_ts` que abriu), `ended_at`, `end_reason` (`completa`, `pausada`, `desfecho`). |
| `decisions` | `app.connection` | Uma linha por `(conversation_id, stage, anchor)`: `disparar`, `motivo`, `ts`. É o que impede decidir o mesmo estágio duas vezes. Uma tabela antiga pode virar `decisions_legacy`. |
| `lead_steps` | `app.connection` | Uma linha por conversa: `oferta`, `etapa_spiced`, `proximo_passo`, `proximo_passo_em`, `status` (`pendente`, `cobrado`, `encerrado`), `atualizado_em`. |
| `ig_matches` | `enrichment.ensure_tables` | Identidade do Instagram por conversa: `username`, `status`, `method`, `candidates`. |
| `ig_company` | `enrichment.ensure_tables` | @ da empresa por conversa. |
| `ig_profiles` | `enrichment.ensure_tables` | Cache do perfil por @ (`source` = `meta` ou `apify`), válido por 7 dias (`SDR_PROFILE_CACHE_SECONDS`). |

Na memória do processo, e perdidos num restart: `supervisor_running` (impede dois supervisores na mesma conversa), `step_announcements` e `last_step_line` (deduplicação da linha "📌 Próximo passo").

### 6.4 Os outros estados

- **Sessões do Hermes:** uma por `HERMES_SESSION_PREFIX + jid` (+ `:testeN` no modo teste, `sdr.session_suffix`), com o histórico da conversa e o SOUL congelado na criação (`hermes-sdr/README.md`). Mudar o prefixo abre sessões novas para todo mundo. O Hermes guarda o rascunho dele. O que o lead de fato recebeu vai em `mensagens_corrigidas` (`sdr.record_correction`). A compressão de contexto está ligada (`compression.enabled: true`, gatilho em 50% do limite do modelo, `config.yaml`).
- **Hermes, memória:** `memory_enabled: true` e `user_profile_enabled: true` no `config.yaml`. A política exige aprovação para escrever (`memory.write_approval: true`) e nega aprovações sem ninguém presente (`unattended_mode: deny`). Se alguma memória é escrita nas sessões da API: **não verificado**.
- **Chatwoot:** a visão do operador. Na conversa ficam as labels `hermes-pausado` (pausa, `HERMES_PAUSE_LABEL`) e `sdr-escalado` (`SDR_ESCALATION_LABEL`), os atributos `sdr_<campo>` (bridge, `sdr.record`) e `spiced_*` (brain, `crm.SPICED_ATTRIBUTES`). As mensagens podem ser públicas, notas privadas (escalação, bloqueio do guardrail) ou `activity` (linhas 🔎, ✏️, ⛔, 🧭, ⏱️, 📌 do brain). O contato recebe `whatsapp_jid`, `ig_*`, `social_profiles.instagram` e `description` (bio).
- **OpenReply:** `DmLog` (quem comentou ou mandou DM, palavra, status `SENT`, `dmSentAt`), `LinkClick` (clique por destinatário, migração `20260928010000_link_click_recipient`), `TrackedLink`, `Automation`.
- **Arquivos editados à mão (bind `/sdr`):** `capacidade.json`, que vira `desatualizado` depois de `SDR_CAPACITY_MAX_AGE_DAYS=7` dias, e `ofertas.json`, com preços, links e regras lidos a cada turno (`sdr.offers`).

---

## 7. Variáveis de ambiente por serviço (só nomes)

O "padrão" é o do código. O valor em produção só aparece quando uma fonte do repositório o confirma. Nenhum valor de segredo foi copiado.

### 7.1 bridge (`integration_bridge`)

| Variável | Controla | Padrão no código | Produção |
|---|---|---|---|
| `BRIDGE_DB` | caminho do SQLite | `/data/bridge.db` | `/data/bridge.db` (`stacks/bridge-stack.yml`) |
| `EVOLUTION_URL`, `EVOLUTION_API_KEY`, `EVOLUTION_INSTANCE` | endereço, chave e instância da Evolution | `http://evolution:4000`, vazio, vazio | `http://evogo_evolution:4000`, segredo, `whatsapp` |
| `EVOLUTION_SEND_PATH`, `EVOLUTION_SEND_MEDIA_PATH` | rotas de envio (aceitam `{instance}`) | `/send/text`, `/send/media` | não verificado |
| `EVOLUTION_MAX_MESSAGE_LENGTH` | corte de mensagem longa (`split_outbound_text`) | 4096 | não verificado |
| `BRIDGE_WEBHOOK_TOKEN` | Bearer exigido nos dois webhooks. Vazio aceita tudo. | vazio | não verificado |
| `CHATWOOT_URL`, `CHATWOOT_ACCOUNT_ID`, `CHATWOOT_INBOX_ID`, `CHATWOOT_INBOX_IDENTIFIER` | Chatwoot interno, conta, inbox numérica, identificador da API pública | `http://chatwoot_rails:3000`, vazio, `1`, vazio | conta 1, inbox 1 (MAPA) |
| `CHATWOOT_API_ACCESS_TOKEN`, `CHATWOOT_APP_TOKEN` | token da API pública do inbox e token da API de conta. Sem o segundo, nem conversa nem label funcionam. | vazio | segredo |
| `CHATWOOT_PUBLIC_URL` | link no alerta de escalação | `https://chatwoot.talles.dev` | não verificado |
| `HERMES_URL`, `HERMES_API_KEY`, `HERMES_MODEL` | Hermes. Sem chave, `ask_hermes` devolve vazio e ninguém responde. | `http://hermes:8642/v1`, vazio, `hermes-agent` | `http://hermes_hermes:8642/v1`, segredo, `hermes-agent` |
| `HERMES_SESSION_PREFIX` | prefixo da sessão. Subir troca o SOUL para todos. | `wa:v13:` | `wa:v13:` (MAPA, seção 5; DEPLOY, passo 5) |
| `HERMES_MAX_CONCURRENCY` | quantos turnos do Hermes ao mesmo tempo (semáforo `hermes_slots`) | 8 | 8 (MAPA, item 8) |
| `HERMES_429_RETRY_SECONDS` | por quanto tempo um 429 vira espera e nova tentativa | 180 | 180 (MAPA, item 8) |
| `HERMES_MESSAGE_DEBOUNCE_SECONDS` | janela de acúmulo das mensagens do lead antes do turno | 10 | 10 (MAPA, item 8) |
| `HERMES_MEDIA_MAX_BYTES` | maior imagem enviada ao Hermes e maior `MEDIA:` aceita | 5 MB | não verificado |
| `HERMES_MEDIA_ROOT`, `HERMES_MEDIA_PREFIX` | onde a bridge enxerga os arquivos do Hermes e qual prefixo ele usa | `/hermes-data`, `/opt/data` | montagem confirmada em `_fatos-vm.md` |
| `HERMES_MEDIA_HISTORY_SECONDS` | quanto tempo uma mídia recente pode ser reaproveitada quando o lead diz "essa foto" | 600 | não verificado |
| `HERMES_PAUSE_LABEL` | label de pausa | `hermes-pausado` | não verificado |
| `SDR_BRAIN_URL`, `SDR_BRAIN_TOKEN` | brain e Bearer das duas direções. **Sem `SDR_BRAIN_URL` não há revisão, eventos nem despacho de toques** (`process_followups_once` retorna na hora). | vazio | URL em produção não verificada. O revisor responde, segundo o MAPA, item 12. |
| `SDR_REVIEW_TIMEOUT` | quanto a bridge espera o `/review` | 12 s | 22 s (`agente-sdr/HERMES_OPS_LOG.md`, linha 1070) |
| `SDR_BUSINESS_START_HOUR`, `SDR_BUSINESS_END_HOUR` | janela de envio dos toques na bridge (hora local, fim exclusivo) | 9 e 20 | Conflito: o OPS_LOG de 28/09 registra 0 e 24; o MAPA de 07/10 cita 9h às 20h. **Não verificado.** |
| `SDR_TIMEZONE` | fuso das horas | `America/Sao_Paulo` | não verificado. O despacho de toques usa `America/Sao_Paulo` fixo no código. |
| `SDR_DIR`, `SDR_CAPACITY_FILE`, `SDR_OFFERS_FILE`, `SDR_MEDIA_DIR`, `SDR_MEDIA_MAX_BYTES` | arquivos confiáveis do bind `/sdr` | `/sdr/...`, 5 MB | `/sdr` (`_fatos-vm.md`) |
| `SDR_CAPACITY_MAX_AGE_DAYS` | idade máxima do `capacidade.json` | 7 | não verificado |
| `SDR_NOTIFY_NUMBER`, `SDR_OWNER_IDS` | número que recebe alertas e todos os ids do dono (número, JID sem o nono dígito, LID) | vazio | definido (valor fora deste documento) |
| `SDR_ESCALATION_LABEL` | label de escalação | `sdr-escalado` | não verificado |
| `SDR_MAX_MESSAGES_PER_TURN` | balões por turno | 3 | não verificado |
| `SDR_LEAK_TERMS`, `SDR_OFFER_PHRASES` | lista do guardrail e frases da oferta liberadas | ver `sdr.py` | não verificado (sem sobrescrita conhecida) |
| `SDR_CREDENTIAL_NOTICE`, `SDR_FALLBACK_REPLY` | aviso de credencial e resposta padrão do bloqueio | ver `sdr.py` | não verificado |
| `BRIDGE_GROUP_POLICY`, `BRIDGE_GROUP_ALLOW_FROM`, `BRIDGE_REQUIRE_MENTION`, `BRIDGE_MENTION_PATTERNS` | grupos: `disabled`, `open` ou `allowlist`. Menção obrigatória. | `disabled` (grupos ignorados) | não verificado |
| `BRIDGE_STT_ENABLED`, `BRIDGE_STT_MODEL`, `BRIDGE_STT_LANGUAGE` | transcrição local de áudio (faster-whisper, CPU, int8) | `true`, `small`, `pt` | não verificado |
| `BRIDGE_OCR_ENABLED`, `BRIDGE_OCR_LANGUAGE` | OCR de PDF escaneado (tesseract, até 10 páginas) | `true`, `por+eng` | não verificado |

### 7.2 sdr-brain (`sdr_brain`)

Fonte: `sdr-brain/app.py`, `enrichment.py`, `crm.py`, `stacks/sdr-stack.yml`, `sdr-brain/README.md`.

| Variável | Controla | Padrão no código | No `stack.yml` |
|---|---|---|---|
| `SDR_BRAIN_TOKEN` | Bearer das rotas (sem ele, 503) e das chamadas à bridge | vazio | obrigatório (`:?`) |
| `SDR_BRAIN_DB` | SQLite | `/data/sdr-brain.db` | o mesmo |
| `SDR_BRAIN_LLM_URL`, `SDR_BRAIN_LLM_KEY`, `SDR_BRAIN_MODEL` | OmniRoute, chave, modelo | OmniRoute, vazio, `agy/gemini-3.7-flash-low` | o mesmo, chave obrigatória |
| `SDR_REVIEW_LLM_TIMEOUT` | tempo da única tentativa do revisor | 18 s | não definido (fica 18) |
| `SDR_TRANSCRIPT_LIMIT` | mensagens do Chatwoot na transcrição | 40 | não definido |
| `BRIDGE_URL` | a bridge | `http://integration_bridge:8080` | o mesmo |
| `CHATWOOT_URL`, `CHATWOOT_ACCOUNT_ID`, `CHATWOOT_API_TOKEN` | transcrição, atividades e atributos | interno, vazio, vazio | conta `"1"`, token obrigatório |
| `SDR_BUSINESS_START_HOUR`, `SDR_BUSINESS_END_HOUR` | janela em que o laço de FUP roda | 9 e 20 | `0` e `24` por padrão do stack |
| `SDR_TIMEZONE` | fuso | `America/Sao_Paulo` | não definido |
| `SDR_QUIET_AFTER_REPLY_SECONDS` | silêncio exigido depois de o lead responder no meio da sequência | 1800 | não definido |
| `SDR_STEP_DUE_HOUR` | hora em que vence um `proximo_passo_em` sem hora | 10 | não definido |
| `SDR_STEP_ACTIVITY_DELAY` | espera para juntar `proximo_passo` e `proximo_passo_em` na linha 📌 | 3 s | não definido |
| `OPENREPLY_DSN` | Postgres do OpenReply, somente leitura (vazio desliga) | vazio | `${OPENREPLY_DSN:-}` |
| `META_GRAPH_TOKEN`, `IG_BUSINESS_ID`, `META_GRAPH_VERSION` | Business Discovery | vazio, vazio, `v20.0` | token obrigatório; o stack traz um id de conta padrão |
| `APIFY_TOKEN`, `APIFY_PROFILE_ACTOR` | fallback de perfil (vazio desliga) | vazio, `apify~instagram-profile-scraper` | `${APIFY_TOKEN:-}` |
| `SDR_MATCH_WINDOW_SECONDS` | janela de cliques e DMs antes da 1ª mensagem | 1800 | não definido |
| `SDR_PROFILE_CACHE_SECONDS` | cache de perfil | 7 dias | não definido |
| `SDR_BRAIN_IMAGE_TAG` | tag da imagem no deploy | `v3` | o mesmo |

`agente-sdr` e o MAPA (item 16) registram um cuidado: um `docker stack deploy` do `sdr` feito sem exportar os segredos apaga o `META_GRAPH_TOKEN` e o `OPENREPLY_DSN` do serviço.

### 7.3 Hermes (`hermes_hermes`)

- Ambiente (`stacks/hermes-stack.yml`): `HERMES_UID`, `HERMES_GID`, `API_SERVER_ENABLED`, `API_SERVER_HOST`, `API_SERVER_PORT` (8642), `API_SERVER_KEY`. O comando é `gateway run`.
- `config.yaml` (volume, `hermes/volume-dados/config.yaml`): `model.default: agy/gemini-3.7-flash-high`, `model.provider: custom`, `model.base_url: http://omniroute_omniroute:20129/v1`, `model.api_key: ${OMNIROUTE_API_KEY}`, `max_concurrent_sessions: null` (sem teto de sessões), `agent.max_turns: 500`, compressão ligada, STT ligado.
  - O limite de execuções simultâneas que gera o 429 (`max_concurrent_runs`, padrão 10, segundo o MAPA, seção 4) **não aparece no `config.yaml`**: **não verificado**.
- Política (`hermes/volume-politica/config.yaml`): `platform_toolsets.api_server: [web, vision, clarify]`. Desliga `terminal`, `file`, `process`, `patch`, `code_execution`, `delegation`, `cronjob`, `skills_hub` e `skills`. Exige aprovação para escrever skills e memória. As aprovações ficam no modo `smart`, e sem ninguém presente são negadas.
- `hermes/volume-dados/env.exemplo` é o exemplo genérico do Hermes. Só `API_SERVER_KEY` importa aqui.

### 7.4 Evolution, Chatwoot, OmniRoute, OpenReply

- **Evolution** (`stacks/evogo-stack.yml`): `SERVER_PORT`, `CLIENT_NAME`, `GLOBAL_API_KEY`, `POSTGRES_AUTH_DB`, `POSTGRES_USERS_DB`, `DATABASE_SAVE_MESSAGES`, `WADEBUG`, `LOGTYPE`, `CONNECT_ON_STARTUP`, `WEBHOOK_FILES` (mídia em base64 dentro do webhook), `WEBHOOK_URL`, `EVENT_IGNORE_GROUP`, `EVENT_IGNORE_STATUS`, `MINIO_ENABLED`.
- **Chatwoot** (`stacks/chatwoot-stack.yml`): `RAILS_ENV`, `NODE_ENV`, `INSTALLATION_ENV`, `SECRET_KEY_BASE`, `FRONTEND_URL`, `FORCE_SSL`, `ENABLE_ACCOUNT_SIGNUP` (`"true"` no arquivo: cadastro aberto, a revisar), `REDIS_URL`, `POSTGRES_*`.
- **OmniRoute** (`stacks/omniroute-stack.yml`): `DATA_DIR`, `PORT`, `DASHBOARD_PORT`, `API_PORT`, `API_HOST`, `REDIS_URL`. `REQUIRE_API_KEY=true` aparece em `ARQUITETURA.md`, não no stack: **não verificado**.
- **OpenReply** (`stacks/openreply-stack.yml`): `NEXTAUTH_URL`, `NEXTAUTH_SECRET` (também assina o `?t=` dos links), `CRON_SECRET`, `ENCRYPTION_KEY`, `DATABASE_URL`, `REDIS_URL`, `RESEND_API_KEY`, `EMAIL_FROM`, `ALLOWED_EMAILS`, `INSTAGRAM_APP_ID`, `INSTAGRAM_APP_SECRET`, `FACEBOOK_APP_SECRET`, `WEBHOOK_VERIFY_TOKEN`, `META_GRAPH_API_VERSION`, `CRON_BASE_URL` (só no cron).
- `stacks/secrets.env.exemplo`: nomes curtos usados no deploy (`CHAT_SECRET`, `CHAT_PG`, `CHAT_REDIS`, `OMNI_KEY`, `EVO_KEY`, `HERMES_KEY`, `BRIDGE_KEY`). A origem dos valores é o cofre.

---

## 8. Tabela de dependências: se X cai, o que para

| Cai | O que para | O que continua | O que se perde |
|---|---|---|---|
| **Evolution** | Nenhuma mensagem entra. A resposta em curso falha no 1º envio. | As respostas que falharam vão para a `outbox` e são reenviadas quando a Evolution volta (laço de 5 s, espera exponencial de até 900 s, sem limite de tentativas). | Toques: risco de **duplicação**. Cada passada de 30 s do despacho tenta de novo e, a cada falha, `send_evolution` põe mais uma cópia na `outbox`, porque o toque continua `pending` (`process_followups_once`). Risco lido no código, não reproduzido. O balão que falhou não é espelhado no Chatwoot. |
| **bridge** | Tudo: webhook da Evolution, resposta humana do Chatwoot, revisão, despacho de toques. | Chatwoot e brain de pé. O laço do FUP roda, mas a consulta `GET /sdr/conversations` falha e a conversa é pulada. | O que a Evolution entregar enquanto a bridge está fora depende de a Evolution repetir o webhook: **não verificado**. Um toque decidido no exato momento em que a bridge cai tem a decisão gravada e o envio perdido (`bridge_post` engole o erro). |
| **Chatwoot** (rails ou Postgres) | O webhook da Evolution dá erro 500 antes de enfileirar o turno: a mensagem não chega ao agente. O operador não vê nem responde. A pausa não pode ser lida. | Envio de balão até o ponto em que o espelho falha. | Mensagens do lead nesse intervalo, se a Evolution não repetir o webhook (**não verificado**). O brain fica sem transcrição e o revisor julga sem histórico. |
| **Chatwoot sidekiq** | Provavelmente a resposta humana (webhook do inbox para a bridge) não sai: **não verificado**. | O agente continua respondendo, porque a bridge fala com o rails direto. | — |
| **Hermes** | Nenhuma resposta. | Espelho no Chatwoot. A mensagem do lead fica em `handover_history` (papel `cliente`) e entra como histórico no próximo turno. | O turno: não há nova tentativa nem aviso ao lead ou ao operador. O FUP também não age, porque o lead falou por último. A conversa fica parada até o lead escrever de novo. |
| **OmniRoute** | O Hermes falha (o mesmo efeito da linha acima). | O revisor cai para "aprovar" com `review_unavailable`, mas as checagens automáticas de `oferta.py` continuam e bloqueiam violações. O enriquecimento não usa LLM e continua. | Supervisor: nenhuma orientação. FUP: o estágio vencido é gravado como "não disparar" (`review_unavailable`) e não é refeito. O toque do prazo vira `cobrado` sem envio. |
| **sdr-brain** | Revisão: o rascunho sai só com o guardrail de termos. Sem supervisor, sem enriquecimento, sem `lead_steps`, sem toques. | A conversa em si. | Os eventos enviados enquanto o brain está fora (uma tentativa de 5 s, `brain_event`). Os registros ficam na `bridge.db`, mas faltam nos `events` do brain, então o supervisor passa a ver menos que a bridge. |
| **OpenReply** (web, worker ou Postgres) | Comentário sem DM. Link `/r/...` fora do ar. | Quem já está no WhatsApp continua sendo atendido. | Identidade do lead: sem banco, o brain trata como sem candidatos (status `direto`) e o agente pede o @. |
| **Traefik** | Domínios públicos: Meta não entrega webhook ao OpenReply, link rastreado não abre, painel do Chatwoot fora. | Todo o tráfego interno da `ai_stack` (WhatsApp, Hermes, brain). | Comentários do período, dependendo da nova tentativa da Meta e do reconciliador de comentários (MAPA, item 1). |
| **Meta Graph** (Business Discovery) | Perfil do Instagram na ficha. | Todo o resto. | Só o rapport pelo perfil. |
| **Bind `/sdr`** (arquivos ausentes) | `capacidade` vira `desconhecido` e o agente não dá preço do Raio-X e escala. `ofertas` vira `{"status": "desconhecido"}`: o revisor perde os fatos e `oferta.check` perde os preços permitidos. | Conversa. | — |

---

## O que verificar quando der problema

1. **Os serviços estão de pé?** `sudo docker service ls`: tudo 1/1, exceto `chatwoot_prepare` e `openreply_migrate`, que ficam 0/1. Depois, a saúde interna: `GET integration_bridge:8080/health` (mostra `outbox_pending`) e `GET sdr_brain:8090/health`, rodando um contêiner na `ai_stack`.
2. **Qual imagem e qual prefixo estão no ar?** Confira se a bridge é `sdr-v13` com `HERMES_SESSION_PREFIX=wa:v13:` (`docker service inspect`). Um SOUL novo com o prefixo antigo não vale para as sessões existentes.
3. **As variáveis críticas da bridge estão definidas?** `SDR_BRAIN_URL` (sem ela, nada de revisão nem de toques), `HERMES_API_KEY` (sem ela, ninguém responde), `CHATWOOT_APP_TOKEN` (sem ela, nada de pausa nem de label) e a janela `SDR_BUSINESS_*`, cujo valor real está em conflito entre as fontes.
4. **A outbox está crescendo?** `outbox_pending` no `/health`. Se crescer, a Evolution está fora ou rejeitando, e é preciso olhar `last_error` na tabela `outbox`.
5. **O disco da bridge:** `/data/media` e as tabelas `event_history`, `bridge_outbound` e `media_history` não têm limpeza no código.
6. **As portas 8642 (Hermes) e 20129 (OmniRoute) estão fechadas para fora?** Teste de fora da VM. Elas estão publicadas no host sem domínio.
7. **Fontes antigas:** os stacks do repositório e o `hermes-sdr/ARQUITETURA.md` (28/09) estão desatualizados em imagens, montagens e no parâmetro do link (o código usa `?t=`, não `?u=`). Na dúvida, vale o `docker service inspect` e o código.
