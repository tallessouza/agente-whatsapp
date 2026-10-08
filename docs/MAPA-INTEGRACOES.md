# Mapa de integrações · Time de IA Instalado + agente de vendas

Levantado em 07/10/2026 (madrugada), lendo o sistema no ar: serviços da VM1, variáveis (só nomes), rotas, webhooks do Chatwoot, site e Kiwify. Atualizado em 08/10/2026, ~03:45 (BRT), com o que a sessão TSX-77 pôs no ar (bridge `sdr-v13.1`, brain `sdr-brain:v3.2`, SOUL e `ofertas.json` novos; seções 5, 6 e 7). Serve para achar rápido onde quebrou durante a produção. Nenhum segredo aqui: credencial fica no Bitwarden (org TSX, collection Recovery) ou no ambiente do serviço.

**Onde mexer:** VM1 = `ssh ubuntu@100.83.163.117` (ou pelo Orca, worktree do portainer). Fonte do agente na VM: `~/orca/projects/portainer-install/` (bridge-src, sdr-brain, hermes-sdr). Cópia de trabalho com histórico: `C:\Users\talle\orca\agente-sdr`. App: `C:\Users\talle\orca\instalador` (GitHub tallessouza/instalador → Vercel).

---

## 1. Os dois caminhos de venda

```
CAMINHO A · Instagram → WhatsApp (agente)
 Reel/post ──comentário "raiox|agente|time..."──► Meta (webhook IG)
   └► OpenReply web (openreply.talles.dev/api/webhook) ─► fila Redis ─► openreply_worker
        └► DM no Instagram com link rastreado  https://openreply.talles.dev/r/<slug>?t=...
             └► redireciona para wa.me/554825000259?text="E aí! Sou o @{username} e quero saber mais sobre o Raio-X"
 WhatsApp do lead ─► número 554825000259 ─► Evolution Go (evogo_evolution)
   └► webhook POST http://bridge:8080/evolution/webhook  (integration_bridge, sdr-v13.1)
        ├► Chatwoot: espelha a conversa (inbox 1 "WhatsApp Evolution", canal API)
        ├► espera 10 s de silêncio (junta mensagens) ─► fila de 8 turnos ─► Hermes (hermes_hermes:8642, SOUL md5 62203261)
        │     └► modelo agy/gemini-3.7-flash-high via OmniRoute (omniroute_omniroute:20129)
        ├► revisor: POST sdr_brain:8090/review (gemini-3.7-flash-low via OmniRoute) ─► guardrail ─► até 3 balões
        ├► Evolution envia no WhatsApp; [[REGISTRO]] vira sdr_records (bridge.db) + atributo sdr_* no Chatwoot
        └► POST sdr_brain:8090/events/* ─► supervisor (orientação 🧭 e 📌 Próximo passo no Chatwoot), lead_steps
 FUP: laço do sdr_brain a cada 60 s ─► POST bridge /sdr/followups ─► envio (horário SDR_BUSINESS_START/END_HOUR, hoje 0–24; até 4/dia)
 Humano responde no Chatwoot ─► webhook do inbox ─► POST http://bridge:8080/chatwoot/webhook ─► Evolution (pausa o agente)

CAMINHO B · Site → Kiwify (compra)
 Anúncio/agente ─► instalador.talles.dev ─► /antes (VPS + Codex ou "1 Ano de Tokens"; cookie aceite_prerequisitos)
   └► checkout Kiwify ju44Xqc (instalação R$ 47 + bump "1 Ano de Tokens" R$ 100)
        └► webhook Kiwify ─► POST instalador.talles.dev/api/webhooks/kiwify (token) ─► Supabase kogjqzcefehfusxeocpy
             ├► webhooks_recebidos (cru) · pedidos · clientes · eventos
             └► obrigado ─► /oferta/gerenciamento ─► /oferta/whatsapp ou /oferta/monitoramento ─► /obrigado
 Cliente ─► /entrar (código de 6 dígitos por e-mail: Supabase Auth OTP) ─► /app (sala)
   └► /app/instalar (5 campos cifrados no navegador, WORKER_PUBLIC_KEY) ─► /admin/fila (Talles instala)
        └► passo 4: link de autorização (Codex ou tokens) + campo do código OAuth (some em 15 min) ─► "Pronto." no Telegram
 Reembolso/chargeback da instalação ─► webhook ─► middleware reescreve /app para /app/bloqueado
```

---

## 2. Pontos de integração, um por um

Legenda da coluna **Verificar**: comando a rodar na VM1 salvo indicação. `CW` = Chatwoot.

| # | De → Para | Como | Credencial | Verificar | Sintoma quando quebra | Primeira ação |
|---|---|---|---|---|---|---|
| 1 | Meta (Instagram) → OpenReply | webhook `POST openreply.talles.dev/api/webhook` (assinado com `FACEBOOK_APP_SECRET`, verificação `WEBHOOK_VERIFY_TOKEN`) + reconciliador de comentários por polling | env do `openreply_web`; token da conta IG no banco (cifrado com `ENCRYPTION_KEY`) | `curl -s https://openreply.talles.dev/api/health` → 200; painel → Logs | comentário com a palavra e nenhuma DM; nada novo em "DmLog" | `sudo docker service logs --since 30m openreply_web` e o status da conta no painel; token do IG vencido → cron `refresh-tokens` |
| 2 | OpenReply → regra da campanha | tabela `"Automation"` (campanha `raiox`, id `cmuk6x90600330jmbl91xrqdc`, ativa, `wholeWordMatch`) | — | `psql` no `openreply_postgres`: `select name,"isActive",keywords from "Automation";` | palavra não dispara; ou dispara para frase comum ("meu time é bom") | conferir keywords; **"time" casa a palavra inteira em qualquer frase** (07/10: raiox, raio-x, raio x, agente, a gente, time) |
| 3 | OpenReply worker → DM no Instagram | Graph API (`META_GRAPH_API_VERSION`), 1 resposta privada por comentário, por ordem de criação das campanhas | token da conta IG | `sudo docker service logs --since 30m openreply_worker \| grep -iE "error\|failed"` | DM não chega; erro de permissão/limite da Meta | logs do worker; limite da Meta por hora; reconectar a conta no painel |
| 4 | Link da DM → WhatsApp | `openreply.talles.dev/r/<slug>?t=<HMAC>` registra o clique (`LinkClick`) e redireciona para `wa.me/554825000259?text=…@{username}…Raio-X` | — | abrir o link de uma DM de teste | clique não abre o WhatsApp ou texto sem o @ | conferir o destino do `TrackedLink`; slug desconhecido cai na home pública |
| 5 | WhatsApp → Evolution Go | sessão do número 554825000259 (1 réplica só; **nunca escalar**: 2 réplicas brigam pela sessão) | `GLOBAL_API_KEY` (env) | `sudo docker service ps evogo_evolution`; painel `evolution.talles.dev` (raiz dá 404, é normal) | mensagens param de chegar em todas as conversas | ver se a instância está conectada; reconectar por QR só com o Talles |
| 6 | Evolution → bridge | `WEBHOOK_URL=http://bridge:8080/evolution/webhook`, `WEBHOOK_FILES=true` (mídia vem em base64 dentro do JSON) | `EVOLUTION_API_KEY` (env da bridge) | `sudo docker service logs --since 10m integration_bridge \| grep "event=MESSAGE"` | lead escreve e nada aparece no CW | logs da bridge; `curl http://integration_bridge:8080/health` (rede ai_stack) |
| 7 | bridge → Chatwoot | API do CW `http://chatwoot_rails:3000`, inbox 1 (canal API), contato por número | `CHATWOOT_API_ACCESS_TOKEN`, `CHATWOOT_APP_TOKEN` (env) | conversa aparece em chatwoot.talles.dev | mensagem do lead some (não aparece no CW) | logs da bridge (`Failed`); CW de pé: `curl -s -o /dev/null -w "%{http_code}" https://chatwoot.talles.dev/` |
| 8 | bridge → Hermes | `POST http://hermes_hermes:8642/v1/chat/completions`, sessão `wa:v13:<jid>`; **fila de 8** (`HERMES_MAX_CONCURRENCY`) e nova tentativa no 429 por até 180 s (`HERMES_429_RETRY_SECONDS`); espera 10 s de silêncio antes (`HERMES_MESSAGE_DEBOUNCE_SECONDS`) | `HERMES_API_KEY` (env da bridge) = `API_SERVER_KEY` do Hermes | logs da bridge: `Hermes at its concurrent-run cap (429)` = fila trabalhando; `Hermes/Evolution batch reply failed` = falhou | resposta demora (fila) ou não vem (falha) | se falhou: logs do `hermes_hermes`; a mensagem fica registrada para atendimento humano |
| 9 | Hermes → modelo | OmniRoute `http://omniroute_omniroute:20129/v1`, modelo `agy/gemini-3.7-flash-high` (config.yaml do volume `hermes_chatwoot_data`) | chave do OmniRoute no `config.yaml` | `sudo docker service logs --since 10m hermes_hermes \| grep -iE "error\|quota\|429"`; painel `omni.talles.dev` | agente lento, erro ou "fallback" | ver cota/conta no OmniRoute; o mesmo OmniRoute atende o brain |
| 10 | SOUL do agente | `/opt/data/SOUL.md` no volume `hermes_chatwoot_data` (444, uid 10000); congela por sessão | — | `sudo md5sum $(sudo docker volume inspect -f '{{.Mountpoint}}' hermes_chatwoot_data)/SOUL.md` = md5 do `hermes-sdr/SOUL.md` | agente fala oferta velha | SOUL novo só vale para sessão nova; para todas: subir `HERMES_SESSION_PREFIX` (hoje `wa:v13:`) |
| 11 | Fatos da oferta | `ofertas.json` em `~/orca/projects/portainer-install/hermes-sdr/` (montado em `/sdr` na bridge), vai no contexto confiável de cada turno | — | `sudo docker exec $(sudo docker ps -q -f name=integration_bridge) head /sdr/ofertas.json` | preço/nome errado no revisor ou no agente | editar o JSON (não precisa reiniciar); preço muda aqui, não no prompt |
| 12 | bridge → brain (revisor) | `POST http://sdr_brain:8090/review` (timeout `SDR_REVIEW_TIMEOUT`); decide aprovar, reescrever, bloquear | `SDR_BRAIN_TOKEN` (env dos dois) | notas "✏️ Resposta reescrita pelo revisor" no CW | resposta crua passa (revisor fora) ou bloqueios demais (vai para o Talles) | `curl http://sdr_brain:8090/health`; logs do `sdr_brain` |
| 13 | brain → modelo | OmniRoute, `agy/gemini-3.7-flash-low` (`SDR_BRAIN_MODEL`) | `SDR_BRAIN_LLM_KEY` | logs do `sdr_brain`: `LLM attempt … failed` | revisor/supervisor/FUP com erro | mesma cota do item 9 |
| 14 | brain → Chatwoot | atributos `sdr_*`, `spiced_*`, notas 🧭 e 📌 | `CHATWOOT_API_TOKEN` | nota "📌 Próximo passo" aparece | sem notas (não quebra a conversa) | logs do `sdr_brain` |
| 15 | brain → bridge (FUP) | laço a cada 60 s; `POST bridge /sdr/followups`; horário pelas SDR_BUSINESS_*_HOUR (hoje 0–24, ou seja, a qualquer hora); até 4 toques/dia; depois do link, 5min/30min/2h ficam com a Kiwify; o relógio recomeça quando o lead responde e o agente responde de volta (`v3.2`) | `SDR_BRAIN_TOKEN` | logs do `sdr_brain`; tabela `sdr_followups` na `bridge.db` | lead some e ninguém retoma; ou toques demais | conferir `link_enviado`, pausa e horário |
| 16 | brain → OpenReply / Meta | lê o banco do OpenReply (`OPENREPLY_DSN`) e o perfil do IG (`META_GRAPH_TOKEN`, `IG_BUSINESS_ID`) para enriquecer o lead | env do `sdr_brain` | atributos de perfil no CW | sem enriquecimento (não quebra) | **stack deploy do sdr sem exportar esses segredos apaga o token da Meta** |
| 17 | Chatwoot → bridge (humano) | webhook do inbox 1 → `http://bridge:8080/chatwoot/webhook` | — | responder pelo CW e ver chegar no WhatsApp | resposta do Talles não sai | logs da bridge; o agente pausa quando o humano fala (`hermes-pausado`); desde a `sdr-v13.1` a resposta humana também conta como a última mensagem do agente para o follow-up |
| 18 | Site → Kiwify | botões do `/antes` e de `/oferta/*` (links e preços vêm do catálogo no banco, editável no admin, W7) | — | `curl -s https://instalador.talles.dev/antes \| grep -o "pay.kiwify.com.br/[A-Za-z0-9]*"` → `ju44Xqc`, `ZxtChtR` | link quebrado/produto bloqueado na Kiwify | conferir o produto na Kiwify (a "Conta do Gemini" foi bloqueada e virou "1 Ano de Tokens") |
| 19 | Kiwify → app (webhook) | `POST https://instalador.talles.dev/api/webhooks/kiwify` (webhook id `d51a31b2…`), eventos order_approved, order_refunded, chargeback, subscription_* | `Kiwify · instalador · KIWIFY_WEBHOOK_TOKEN` (cofre e Vercel) | `/admin/webhooks` mostra o cru de cada chegada | compra feita e cliente sem acesso | `/admin/webhooks`: chegou? qual status? produto não mapeado e carrinho abandonado são ignorados de propósito |
| 20 | Kiwify → recuperador | agente da Kiwify chama carrinho abandonado, pagamento recusado e Pix não pago em até 30 min | painel Kiwify | painel Kiwify | lead recebe cobrança dupla | regra: as primeiras horas depois do link são da Kiwify; o nosso FUP só no d1/d4/data combinada |
| 21 | App → e-mail de acesso | `/entrar`: Supabase Auth OTP (código de 6 dígitos); o SMTP é o do Supabase (Resend) | painel Supabase + Resend | entrar com um e-mail de teste | cliente não recebe o código | painel do Supabase (Auth → logs) e do Resend; já falhou antes por token do Resend |
| 22 | App → banco | Supabase `kogjqzcefehfusxeocpy` (sa-east-1), RLS ligado; service role só no servidor | `SUPABASE_SERVICE_ROLE_KEY` (Vercel); gestão: `Heilz - Supabase` | admin abre | erro 500 no app | logs da Vercel; status do Supabase |
| 23 | Formulário cifrado | navegador cifra com `WORKER_PUBLIC_KEY`; só o admin decifra | chave privada fora do app | `/admin/fila` mostra o pedido | formulário não envia | e2e `jornada` no repo; logs da Vercel |
| 24 | Código do OAuth (W6) | cliente cola na sala → `codigos_oauth` → aviso por e-mail (Resend) aos `ADMIN_EMAILS` (Telegram opcional, ainda sem variáveis) | `RESEND_API_KEY` | `/admin/fila` mostra o código com o tempo que falta | código não chega / some antes | limpeza: pg_cron `limpar-codigos-oauth` a cada 5 min + cron diário da Vercel `/api/cron/limpar-codigos` (Hobby só aceita diário) |
| 25 | Bloqueio por reembolso | middleware reescreve `/app` → `/app/bloqueado` quando a instalação foi reembolsada ou teve chargeback | — | cliente reembolsado vê só "Falar com a gente" | cliente reembolsado ainda acessa | `/admin/webhooks` (evento chegou?) e `pedidos.status` |
| 26 | Pixel e conversões | site: pixel `1650027766733801` (+ `META_CAPI_TOKEN` no servidor); o app dispara `AntesDeComprar` e deixa `InitiateCheckout`/compra para o pixel da Kiwify | Vercel | Gerenciador de Eventos da Meta | anúncio otimiza sem compras | **conferir no painel da Kiwify se o pixel salvo é o `…6733801`** (a sessão 8277a4f1 viu `…5093120`) |
| 27 | DNS e borda | Cloudflare (talles.dev, DNS only) → Traefik na VM (`*.talles.dev` do agente) e Vercel (`instalador`) | `Cloudflare · talles.dev · CLOUDFLARE_API_TOKEN` | lista da seção 3 | domínio fora | Cloudflare e o Traefik (`traefik_traefik`) |

---

## 3. Abertura do dia (5 minutos, nesta ordem)

```bash
# 1. Borda pública (de qualquer máquina): tudo 200, exceto evolution (404 na raiz é normal) e omni (307)
for u in https://openreply.talles.dev/api/health https://chatwoot.talles.dev/ https://evolution.talles.dev/ \
         https://omni.talles.dev/ https://vault.talles.dev/alive https://instalador.talles.dev/ https://instalador.talles.dev/antes; do
  printf "%-45s %s\n" "$u" "$(curl -s -o /dev/null -m 15 -w '%{http_code} %{time_total}s' $u)"; done

# 2. Serviços da VM: tudo 1/1 (openreply_migrate e chatwoot_prepare 0/1 é normal: rodam e saem)
ssh ubuntu@100.83.163.117 'sudo docker service ls --format "{{.Name}} {{.Replicas}} {{.Image}}"'

# 3. Saúde interna e memória
ssh ubuntu@100.83.163.117 'for u in http://integration_bridge:8080/health http://sdr_brain:8090/health; do
  sudo docker run --rm --network ai_stack curlimages/curl -s -m 8 -o /dev/null -w "$u %{http_code}\n" $u; done;
  free -m | sed -n 2,3p; cat /proc/pressure/memory | head -1'

# 4. Erros da última hora
ssh ubuntu@100.83.163.117 'for s in integration_bridge sdr_brain hermes_hermes openreply_worker evogo_evolution; do
  printf "%-20s %s\n" $s "$(sudo docker service logs --since 1h $s 2>&1 | grep -ciE "error|exception|failed|traceback")"; done'

# 5. Teste de ponta a ponta: comentar "time" num post com outra conta → DM chega → abrir o link → mandar a mensagem → resposta em até ~30 s
# 6. /admin/webhooks no app: o último evento da Kiwify chegou e foi processado
```

---

## 4. Limites conhecidos (medidos em 07/10)

- **Hermes:** no máximo 10 turnos simultâneos (`max_concurrent_runs`, padrão). A bridge segura em 8 e põe o resto na fila; 429 vira espera, não perda. Turno típico: 6 a 11 s.
- **Tempo de resposta percebido:** até 10 s de acúmulo (contados do início do lote) + turno (~10 s) + revisor.
- **Capacidade de conversa:** ~60 a 80 pessoas conversando ao mesmo tempo em ritmo normal; picos de primeira mensagem acima de 8 entram em fila.
- **Memória da VM1:** 12 GB, ~5 GB livres depois de fechar as sessões do Claude; **swap de 8 GB** (swappiness 10, desde 07/10); nenhum container tem limite de memória.
- **Mídia grande no WhatsApp:** a Evolution manda a mídia em base64 dentro do webhook e a bridge lê tudo em memória. Um arquivo de 1 GB pode derrubar processos. Proteções possíveis (não aplicadas): limite de memória na Evolution e na bridge, corte por tamanho.
- **Evolution:** uma réplica só, sem escala automática (decisão de 07/10: acompanhar).
- **Modelos:** Hermes e brain no mesmo OmniRoute (`agy/gemini-3.7-flash-high` e `-low`); cota única.
- **Instalação:** 15 por dia, à mão (Mágico de Oz), até 48 h.
- **Upsell de 1 clique:** ainda não existe (W5); "Sim" abre um checkout novo.

---

## 5. Estado do agente em produção (08/10, ~03:45 BRT, depois da TSX-77)

- `integration_bridge` = `evolution-chatwoot-bridge:sdr-v13.1` (fila incluída; a resposta humana pelo Chatwoot atualiza `last_agent_ts`), prefixo `wa:v13:`.
- `sdr_brain` = `sdr-brain:v3.2` (preço do Instalador sempre com o link, 2ª pessoa, sem saída antes do link, nome de IA solto, relógio do FUP que recomeça). `hermes_hermes` com o SOUL md5 `62203261`.
- OpenReply = `openreply:sdr-v2` (devolve o @ do Instagram). A palavra "time" está na campanha `raiox`, então quem comenta TIME chega com o texto do Raio-X; o agente pergunta do Raio-X e muda para a instalação assim que a pessoa diz que quer o time (simulado em 07/10).
- **Oferta do Instalador no ar:** quem chega com sinal de compra recebe o exemplo do caso, o preço e o link na mesma resposta (no máximo uma pergunta antes); VPS e Codex entram como valor junto do preço, não como triagem; servidor de referência KVM 8 da Hostinger, R$ 120 a R$ 200 por mês (`ofertas.json` de 07/10 23:30).
- **"1 Ano de Tokens" no ar** como o nome do bump de R$ 100 no checkout. O agente continua chamando de "Conta do Gemini" e pode dizer o nome do checkout; "Gemini" sozinho continua barrado pelo guardrail.
- A cópia de trabalho `C:\Users\talle\orca\agente-sdr` está igual à produção (commit `0de5284`, 13 arquivos conferidos por md5).

## 6. Voltar atrás (backups)

Os backups da TSX-77 ficam na fonte da VM, `~/orca/projects/portainer-install/`.

| O quê | Como voltar |
|---|---|
| Bridge | `sudo docker service update --image evolution-chatwoot-bridge:sdr-v13 integration_bridge` (a anterior, sem o `touch_activity` do humano; o prefixo pode ficar). Mais atrás: `sdr-v12` com `--env-add HERMES_SESSION_PREFIX=wa:v14:` (prefixo sempre sobe, nunca volta). Fonte: `bridge-src/app.py.antes-humano.20261008-0317` |
| Brain | `sudo docker service update --image sdr-brain:v3 sdr_brain` (antes da TSX-77); mais atrás, `sdr-brain:v2`. Fonte: `sdr-brain/*.antes-tsx77.20261007` (antes da TSX-77) e `sdr-brain/*.antes-fup.20261008-0145` (antes do recomeço do relógio do FUP) |
| SOUL | o anterior está em `hermes-sdr/SOUL.md.antes-tsx77.20261007` na fonte; o de antes da v13 em `$P/backups/SOUL.md.antes-v13.20261007-0657` no volume `hermes_chatwoot_data`. Volta com `install -m 444 -o 10000 -g 10000` no volume e `--force hermes_hermes` (vale para sessões novas) |
| Fatos da oferta | `hermes-sdr/ofertas.json.antes-kvm8.20261008-0300` (antes do KVM 8) ou `hermes-sdr/ofertas.json.antes-prod-tsx77.20261008-0345` (antes da última troca); copiar por cima de `ofertas.json`, sem reiniciar |
| Fonte do agente na VM | `~/backups-agente/antes-v13-20261007-0655.tgz`; `bridge-src/app.py.antes-fila.20261007-0647` |
| Swap | `sudo swapoff /swapfile`, tirar a linha do `/etc/fstab` |

## 7. Pendências que podem aparecer amanhã

1. **Pixel salvo na Kiwify** (item 26): confirmar `…6733801`.
2. **Cupom de teste `GRAVAFUNIL7Q3K` (89%)**: confirmar no painel que o "Habilitar cupons" da instalação está desligado (a tentativa de 07/10 deu 403 ao salvar).
3. **Toque com link acrescentado** (lido no código, não reproduzido): quando o revisor reescreve um toque com o link, o brain põe `[[REGISTRO: link_enviado = sim]]` no texto, e o despacho de toques da bridge não tira diretivas. Conferir em `sdr_followups.text` se algum toque saiu com `[[` (detalhe em `docs/ARVORES-DE-DECISAO.md`, seção 7).
4. **Hermes e brain de teste** (`hermes_teste_hermes`, `sdr_teste_brain`) ainda ligados (~350 MB): derrubar quando não precisar mais.
5. **Vídeos** da home e da /antes: "vídeo em breve" até o Talles gravar.
6. **Telegram de alerta** do app (código do OAuth): sem variáveis; hoje o aviso é só por e-mail.
