# Arquitetura do SDR no WhatsApp

Estado em 2026-09-28. O histórico de cada decisão, com evidências, está em
[`../HERMES_OPS_LOG.md`](../HERMES_OPS_LOG.md). Segredos ficam só em
`CREDENTIALS.md` / `creds` (fora do Git).

## Princípio

Quem **decide** é modelo; quem **executa** é código determinístico.

- **O Hermes só conversa.** Não tem ferramenta de sistema, então não tem o
  que listar nem o que abusar.
- **Decisões fora da conversa ficam no `sdr-brain`**: revisar, supervisionar,
  enriquecer o lead e decidir toques. Ele tem modelo e chave próprios no
  OmniRoute.
- **A bridge só executa**: transporte, contexto, diretivas, guardrails,
  presença de digitação e o despacho da fila de toques. Nenhum passo dela
  depende de julgamento de modelo.

```
Instagram (reel/DM) ──► OpenReply ── link rastreado /r/<slug>?u=<assinatura> ──► wa.me
                              │ (clique registra quem foi)
                              ▼
lead ──► Evolution Go ──► bridge ──► Chatwoot (inbox, histórico, labels)
                           │  ▲
     mensagem de sistema   │  │ texto final (≤3 balões, "digitando…")
     (hora, vagas, ficha,  ▼  │
      orientações)       Hermes SDR ──► revisor (sdr-brain) ──► guardrail
                           │
                           └─ eventos ─► sdr-brain ─┬─ supervisor → /sdr/guidance, /sdr/escalate
                                                    ├─ enriquecimento → /sdr/lead-profile
                                                    │    (OpenReply read-only + Meta Business Discovery)
                                                    └─ agente de FUP (loop 60 s) → /sdr/followups
                                                                              │
                              despacho da fila na bridge (loop 30 s) ◄────────┘
Escalação: labels no Chatwoot + nota privada + aviso no WhatsApp do Talles (Evolution)
LLM de tudo: OmniRoute → Antigravity (duas contas OAuth, prioridade 1 e 2)
```

## Serviços (Docker Swarm, overlay `ai_stack`)

Na `ai_stack`, use sempre o nome completo do serviço (`chatwoot_postgres`,
`omniroute_redis`…). Os nomes curtos resolvem para mais de uma stack.

| Serviço | Imagem | Papel |
|---|---|---|
| `hermes_hermes` | `hermes-agent:latest` | O SDR. API OpenAI-compatible em `hermes_hermes:8642/v1`. |
| `integration_bridge` | `evolution-chatwoot-bridge:sdr-v12` | Bridge Evolution ↔ Chatwoot ↔ Hermes com a camada SDR (`bridge-src/`). Monta `hermes-sdr/` em `/sdr`. |
| `sdr_brain` (stack `sdr`) | `sdr-brain:v2` | Revisor, supervisor, enriquecimento e agente de FUP (`sdr-brain/`). Sem porta publicada. Redes `ai_stack` e `openreply_internal`. |
| `evogo_evolution` | `evoapicloud/evolution-go` | Transporte WhatsApp, instância `whatsapp`. |
| `chatwoot_*` | `chatwoot/chatwoot:v4.18.0` | Inbox humana e histórico, conta 1. |
| `omniroute_omniroute` | `diegosouzapw/omniroute` | Roteador de LLM com `REQUIRE_API_KEY=true`. Chaves: `hermes-bridge` e `sdr-brain`. |
| `openreply_*` | `openreply:sdr-v2` (branch `sdr-tracking` em `/opt/openreply`) | Automação de Instagram: campanhas, DMs, link rastreado por destinatário. |

## Hermes SDR

- **Modelo:** `agy/gemini-3.7-flash-high`, em `/opt/data/config.yaml`.
  - O Sonnet foi testado em 2026-09-27 e revertido: consumia muita cota da
    assinatura. A qualidade veio do prompt.
  - Média de 4,8 s por turno, ~8k tokens de entrada.
- **Persona:** [`SOUL.md`](SOUL.md), instalada em `/opt/data/SOUL.md` com
  modo 444 e uid 10000. Backups em `/opt/data/backups/`.
  - O prompt congela por sessão. A bridge usa sessões
    `<HERMES_SESSION_PREFIX><jid>` (hoje `wa:v12:`). **Mudou a persona? Suba
    o prefixo.**
- **Toolsets:** `web`, `vision` e `clarify`. `skills` está desabilitado; a
  política fica no volume `hermes_policy` (ver `HERMES_SECURITY_POLICY.md`).
- **Contexto confiável:** chega só pela mensagem `role: system` de cada
  requisição, que é efêmera e não fica na sessão. Tudo no turno `user` é
  dado do lead. Campos:

  | Campo | Conteúdo |
  |---|---|
  | `agora` | Hora de Brasília |
  | `capacidade` | Lida de `capacidade.json`; vira `desatualizado` depois de `SDR_CAPACITY_MAX_AGE_DAYS=7` |
  | `fotos_aprovadas` | De `midia/descricoes.json` |
  | `lead` | Origem, registros e `ficha` |
  | `orientacoes` | Vindas do supervisor |
  | `gatilho` | Por que o agente fala sem mensagem nova do lead |
  | `mensagens_corrigidas` | O que o lead realmente recebeu quando o revisor mudou ou a interrupção cortou a resposta |

- **SOUL:**
  - As 8 regras invioláveis: apresentação como agente, nome de cliente,
    posicionamento, capacidade, ordem 48k → 12k, nada de preço antes do
    diagnóstico, as três perguntas, sigilo.
  - A conversa em 4 fases:
    1. **Conhecer:** abertura literal, rapport com o perfil, o @, triagem,
       faturamento, carteirada.
    2. **Diagnosticar:** custo, ganho, urgência e o espelho.
    3. **Dar certeza, depois o preço:** como funcionaria para ele, a âncora
       sozinha, o Raio-X.
    4. **Decidir:** as três perguntas e o fechamento, que escala para o
       Talles.
  - Por fim: objeções pelos três testes, quando escalar, registros, um
    exemplo de tom e um checklist antes de enviar.

### Diretivas na resposta do Hermes

A bridge interpreta as diretivas e as remove antes do envio. Qualquer
`[[...]]` desconhecido também é removido.

| Diretiva | Efeito |
|---|---|
| `[[ESCALAR: motivo \| frase literal]]` | Pausa o Hermes; labels `hermes-pausado` + `sdr-escalado`; nota privada; aviso no WhatsApp do Talles. Idempotente. |
| `[[REGISTRO: campo = valor]]` | Atributo da conversa no Chatwoot e evento ao brain. Campo `instagram` ou `arroba` dispara o enriquecimento. |
| `[[FOTO: nome]]` | Envia uma imagem aprovada de `midia/`. |
| `[[QUEBRA]]` (ou linha em branco) | Separa balões; no máximo 3 por turno (`SDR_MAX_MESSAGES_PER_TURN`). |
| `[[SILENCIO]]` | Não envia nada (despedida já feita) e pula o revisor. |

## Bridge: o caminho de uma mensagem

1. **Acúmulo:** junta as mensagens do lead por 10 s
   (`HERMES_MESSAGE_DEBOUNCE_SECONDS`). Áudio é transcrito (faster-whisper) e
   documento vira texto ou OCR.
2. **Chegada do lead:** cancela os toques pendentes do lead e atualiza
   `last_lead_ts`. Na primeira mensagem, manda `/events/lead` ao brain.
3. **Chamada ao Hermes:** monta a mensagem de sistema e chama o Hermes.
4. **Interrupção:** se o lead escreveu enquanto o Hermes pensava, a resposta
   é descartada e o lote volta à fila junto com a mensagem nova. Assim a
   resposta nunca chega atrasada a uma pergunta velha.
5. **Revisão:** `POST /review` no brain, com timeout `SDR_REVIEW_TIMEOUT=22`
   s. Se falhar, segue com o rascunho.
6. **Guardrail determinístico:** termos da stack, `[[`, caminhos → não envia,
   manda a resposta-padrão e escala.
7. **Sem travessão nem dois-pontos conectivo** (`sdr.plain_style`, também
   nos toques):
   - O travessão entre frases vira vírgula; hífen dentro de palavra fica.
   - ": texto" vira ponto final com maiúscula; ": R$ 48.000" vira vírgula.
   - Hora e link ficam.
8. **Envio:** balão a balão, com presença "digitando…"
   (`POST /message/presence`) proporcional ao tamanho. Antes e depois de
   cada espera, confere de novo a interrupção.
   - O que saiu é gravado em `sdr_corrections`, e o Hermes vê isso em
     `mensagens_corrigidas`.
9. **Diretivas e eventos:** executa as diretivas e publica
   `/events/exchange`, que aciona o supervisor.

- **Handover humano:** resposta pelo celular ou pelo Chatwoot aplica
  `hermes-pausado`. Enquanto a label existir, o Hermes não responde.
- **Mensagens do dono:** as do número do Talles (`SDR_NOTIFY_NUMBER` +
  `SDR_OWNER_IDS`, que cobrem o JID com e sem o nono dígito e o LID) nunca vão
  ao Hermes.
- **Modo teste:** o dono manda `#teste` e passa a ser tratado como lead numa
  sessão nova. `#fim` encerra.

### Despacho da fila de toques (loop de 30 s)

Para cada `sdr_followups` pendente com `send_at` vencido:

- **Cancela** se o lead falou depois de `after_ts`, se a conversa está
  pausada, se já há `desfecho`, se já saíram 4 toques no dia, se o toque foi
  superado por outro ou se o guardrail acusou termo interno.
- **Espera** se está fora da janela
  `SDR_BUSINESS_START_HOUR`–`SDR_BUSINESS_END_HOUR`. Hoje a janela é 0–24,
  ou seja, sempre aberta.
- **Envia** com "digitando…", grava no Chatwoot e no histórico do Hermes
  (`retomada_enviada`). Não mexe em `last_agent_ts`, para não reiniciar a
  sequência.

### Tabelas da bridge (SQLite, `sdr.py`)

`sdr_records`, `sdr_leads`, `sdr_guidance`, `sdr_profiles`, `sdr_followups`,
`sdr_activity` (`last_lead_ts` e `last_agent_ts`), `sdr_corrections`,
`sdr_owner_test`.

## sdr-brain

Modelo: `SDR_BRAIN_MODEL=agy/gemini-3.7-flash-low`. As chamadas pedem JSON, e
`parse_json_object` tolera cercas de código. Os prompts ficam em
`sdr-brain/prompts/`.

### Revisor (`/review`, `revisor.md`)

- **Decisões:** `aprovar`, `reescrever` (novas `parts`) ou `bloquear`.
  `bloquear` só vale para sigilo e nome de cliente, e escala.
- **Na dúvida, aprova.** A reescrita só corta ou conserta. Nunca acrescenta
  preço, âncora ou passo.
- **O que ele sabe:** a lista de fatos reais da oferta (que não contam como
  "logística inventada") e as frases literais do roteiro, que nunca reescreve.
- **Regras fiscalizadas:** sigilo, nomes, curso/mentoria, 48k antes de 12k,
  capacidade, números permitidos, afirmação ou logística inventada, voz
  "eu / o Talles", responder a pergunta do lead, lead fora do perfil sem
  preço, dossiê inventado, 3 balões, um passo por turno, nada de preço antes
  do diagnóstico (dor, custo, urgência e faturamento), pergunta final e
  reconhecimento da objeção.
- **Tempo:** uma tentativa, `SDR_REVIEW_LLM_TIMEOUT=18` s.

### O que aparece no Chatwoot (`crm.py`)

**Mensagens de sistema** (tipo `activity`): linhas centralizadas, visíveis só
para quem atende. A bridge não as encaminha ao WhatsApp e o transcript dos
modelos as ignora.

| Linha | Quando |
|---|---|
| 🔎 Instagram @x: status (método) · seguidores, posts · campanha · empresa | Fim do enriquecimento |
| ✏️ Resposta reescrita pelo revisor: motivo | Revisão de resposta ou de toque |
| ⛔ Resposta bloqueada pelo revisor: motivo | Revisão de resposta ou de toque |
| 🧭 Orientação para o próximo turno: … | O supervisor gravou uma orientação |
| ⏱️ Toque &lt;estágio&gt; agendado / não enviado: motivo | Decisão do agente de FUP |

A escalação continua como nota privada, gravada pela bridge.

**Atributos do contato**, criados automaticamente em *Configurações →
Atributos personalizados*:

| Atributo | Conteúdo |
|---|---|
| `ig_usuario` | Link do perfil |
| `ig_identificacao` | Como o @ foi identificado |
| `ig_seguidores`, `ig_posts` | Contagens do perfil |
| `ig_curtidas_recentes`, `ig_comentarios_recentes` | Soma nos últimos 6 posts |
| `ig_bio`, `ig_site` | Bio e site |
| `ig_ultimos_posts` | Legenda · curtidas · comentários · link |
| `ig_empresa`, `ig_empresa_seguidores` | Perfil da empresa |
| `ig_campanha` | Campanha de origem |

Também preenche o Instagram em `social_profiles` e a bio em `description`.
Os números de engajamento e os links ficam só no Chatwoot: a `ficha` que o
Hermes recebe mantém só temas das legendas (`enrichment.for_agent`), para
rapport sem métricas.

### Supervisor (`/events/exchange`, `supervisor.md`)

Roda depois de cada troca, com a transcrição do Chatwoot.
- Pode gravar uma orientação para o próximo turno (`/sdr/guidance`).
- Pode escalar (`/sdr/escalate`).
- Não roda duas vezes na mesma conversa ao mesmo tempo.

### Enriquecimento (`enrichment.py`)

Resolve quem é o lead no Instagram e grava a `ficha` pela rota
`/sdr/lead-profile`.

**Identidade (`resolve_identity`):**

| Método | De onde vem |
|---|---|
| `texto_do_link` | @ na primeira mensagem |
| `lead_informou` | `[[REGISTRO: instagram]]` |
| `clique` / `clique+nome` | Cliques identificados em `LinkClick` numa janela de 30 min (`SDR_MATCH_WINDOW_SECONDS`), com desempate pelo nome do contato no Chatwoot |
| `janela+nome` / `janela` | DMs enviadas (`DmLog`) na mesma janela |

- **Status possíveis:** `confirmado`, `informado`, `provavel`, `ambiguo`,
  `direto` (sem candidato: o lead veio direto).
- Só identidade `confirmado` ou `informado` entra na ficha.

**Dados:**
- **OpenReply**, com o papel read-only `sdr_brain_ro` (SELECT em `DmLog`,
  `Automation`, `WebhookEvent`, `LinkClick`): campanha, palavra, comentário
  ou DM.
- **Meta Business Discovery** (`META_GRAPH_TOKEN`, system user "Elemsm";
  `IG_BUSINESS_ID=17841460228743369`): bio e legendas dos últimos posts, do
  perfil pessoal e do @ da empresa.
  - Permissões necessárias: `instagram_basic`, `instagram_manage_insights`,
    `pages_read_engagement`, `ads_read`.
  - Apify (`APIFY_TOKEN`) é fallback opcional.
- **Cache de 7 dias** (`ig_profiles`). Outras tabelas: `ig_matches` e
  `ig_company`.

### Agente de FUP (loop de 60 s, `fup.md`)

- **Sequência:** começa quando o agente fala por último e o lead fica em
  silêncio. A âncora é o `last_agent_ts`.
- **Estágios:** `5min`, `30min`, `2h`, `d1`, e `d4` depois do preço.
  - A cada passada, decide só o estágio mais recente alcançado, sem
    rajada depois de downtime.
- **A sequência não reinicia quando o lead responde.** O estágio é pulado
  ("conversa em andamento") se o lead respondeu nos últimos 30 min
  (`SDR_QUIET_AFTER_REPLY_SECONDS`). Termina no último estágio, em
  `desfecho` ou com a conversa pausada.
- **O que o modelo recebe:** estágio, transcrição, toques anteriores e se o
  lead respondeu no meio. Devolve `{"disparar", "texto", "motivo"}`.
  - O toque continua o assunto e empurra para o próximo passo. Não é
    lembrete.
  - Voz "eu / o Talles", sem promessa de resultado.
- **Revisão do toque:** antes da fila, o texto passa pelo mesmo revisor
  (`tipo: "toque"`, com o contexto da bridge, capacidade incluída).
  - `reescrever` troca o texto.
  - `bloquear` vira decisão de não enviar.
  - Isso fecha o buraco em que só o guardrail de termos olhava os toques.
- **Registro:** a decisão fica em `decisions`, e o disparo vai para
  `/sdr/followups`.
- **Tabelas:** `tracked` (sobrevive a restart), `sequences`, `decisions`.
  - Conversa que some da bridge (404) deixa de ser acompanhada.
- **Para refazer uma decisão:** cancele o `sdr_followups` pendente na bridge
  e apague a linha em `decisions`.

## Contrato bridge ↔ sdr-brain

Todas as chamadas levam `Authorization: Bearer $SDR_BRAIN_TOKEN`. Horários em
epoch (float).

**Rotas do sdr-brain (`http://sdr_brain:8090`):**

| Rota | Corpo | Resposta |
|---|---|---|
| `GET /health` | — | `{"status":"ok"}` |
| `POST /review` | `conversation_id, jid, lead_message, draft_parts, directives, context` (+ `transcript` opcional) | `aprovar` / `reescrever` + `parts` / `bloquear` + `motivo` |
| `POST /events/exchange` | `conversation_id, jid, source_id, lead_message, agent_parts, directives, ts` | 202, aciona o supervisor |
| `POST /events/lead` | `conversation_id, jid, origin, first_message, ts` | 202, aciona o enriquecimento |
| `POST /events/record` | `conversation_id, campo, valor, ts` | 202 (`instagram` e `arroba` acionam enriquecimento) |

**Rotas da bridge (`http://integration_bridge:8080`):**

| Rota | Efeito |
|---|---|
| `POST /sdr/guidance` | Orientação para o próximo turno |
| `POST /sdr/escalate` | Mesma escalação do `[[ESCALAR]]` |
| `POST /sdr/lead-profile` | Substitui a ficha do lead |
| `POST /sdr/followups` | `conversation_id, send_at, text, motivo, after_ts, stage` → fila |
| `DELETE /sdr/followups/{id}` | Cancela os pendentes |
| `GET /sdr/conversations/{id}` | `jid, source_id, lead, followups, paused, last_lead_ts, last_agent_ts, context` (o mesmo contexto confiável do turno; 404 se não existe) |

## OpenReply: link por destinatário

- O botão do DM leva `https://openreply.talles.dev/r/<slug>?u=<id>.<hmac>`.
  - A assinatura é um HMAC do id do destinatário com `NEXTAUTH_SECRET`
    (`lib/tracking/recipient.ts`).
  - O lead não vê nenhum código de referência, então editar a mensagem no
    WhatsApp não quebra o rastreio.
- **No clique**, a rota `app/r/[slug]` grava `LinkClick.recipientId` e
  `LinkClick.recipientName` e troca `{username}` / `%7Busername%7D` no
  destino.
  - Destino da campanha "raiox":
    `https://wa.me/554825000259?text=E%20a%C3%AD%21%20Sou%20o%20%40%7Busername%7D%20e%20quero%20saber%20mais%20sobre%20o%20Raio-X`
  - Slug desconhecido redireciona para `NEXTAUTH_URL`.
- **DM sem nome anterior:** o username vem da Graph API (`getUserUsername`).
- **Migração** `20260928010000_link_click_recipient`.

## Capacidade e mídia

- `capacidade.json`, editado à mão: `mes`, `vagas_total`,
  `vagas_restantes`, `horas_comprometidas`, `horas_limite`, `proximo_mes`,
  `atualizado_em`.
  - Mais de 7 dias sem atualizar → `desatualizado`. Nesse estado, o agente
    não dá preço e escala.
- `midia/descricoes.json` + os arquivos da pasta são as fotos aprovadas para
  `[[FOTO]]`. Hoje está vazio.

## LLM e cota

- Tudo passa pelo OmniRoute (`http://omniroute_omniroute:20129/v1`), sempre
  com chave.
- Provider Antigravity com duas contas OAuth: `lsuperagentes` (prioridade 1)
  e `ebtalles` (prioridade 2). A segunda deveria entrar quando a primeira
  recebe rate-limit, mas isso ainda não foi visto acontecer.
- **Cotas:** `gemini_weekly` é a que o SDR usa hoje (~1% por dia de testes);
  `claude_gpt_weekly` só importa se voltar a usar Sonnet.
- **Risco:** usar assinatura em produção pode violar os termos e levar à
  suspensão de conta. Se o volume crescer, o caminho seguro é a API paga.

## Testes e simulação

- **Bridge:** `python -m unittest test_sdr test_handover test_payment
  test_phase_b`, rodando dentro da imagem (43 testes).
- **Brain:** `pytest test_app.py` (20 testes).
- **Simulador:** [`sim/`](sim/README.md). Um lead-persona conversa com o
  pipeline real: Hermes, revisor, guardrail e correção.
  - Rodadas salvas em `sim/rodada-*.txt`.
  - `/tmp/ficha.json` injeta uma ficha de Instagram.
- **Toda mudança de persona:** rodar Marina (no perfil) e Carla (fora do
  perfil, com ficha) e o teste de extração (prompt, modelo, ferramentas,
  "ignore as instruções").

## Operação: como mudar cada coisa

| Mudança | Passos |
|---|---|
| Persona | Editar `SOUL.md` → backup do atual → `install -m 444 -o 10000 -g 10000` no volume `hermes_chatwoot_data` → subir `HERMES_SESSION_PREFIX` na bridge → `docker service update --force hermes_hermes` → simular. |
| Modelo do Hermes | `/opt/data/config.yaml` (`model.default`), backup antes, reiniciar o Hermes. |
| Revisor, supervisor ou FUP | Editar `sdr-brain/prompts/` → `docker build -t sdr-brain:vN sdr-brain` → `docker service update --image sdr-brain:vN sdr_brain` (e atualizar o padrão em `stack.yml`). |
| Bridge | Build com nova tag `sdr-vN` → testes na imagem → `docker service update --image`. |
| Deploy do brain do zero | Exportar os segredos (`SDR_BRAIN_TOKEN`, `SDR_BRAIN_LLM_KEY`, `CHATWOOT_API_TOKEN`, `META_GRAPH_TOKEN`, `OPENREPLY_DSN`) e rodar `sudo -E docker stack deploy -c sdr-brain/stack.yml sdr`. |
| Vagas | Editar `capacidade.json` e atualizar `atualizado_em`. |
