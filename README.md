# Agente de vendas no WhatsApp · estrutura completa (retrato de produção)

Tudo o que faz o agente do Talles atender no WhatsApp: **Evolution Go** (número 554825000259) → **bridge** → **Chatwoot** → **Hermes** (com o SOUL e a configuração) → **OmniRoute** (Gemini) → **sdr-brain** (revisor, supervisor, follow-up, próximo passo), e na frente o **OpenReply** (comentário no Instagram → DM → WhatsApp com o @).

Retrato tirado da VM1 em **08/10/2026, ~03:45 (BRT)**, depois da sessão TSX-77, do que está rodando. Para revisão: não é o lugar de onde se faz deploy (ver "De onde vem cada coisa").

## Documentos

| Documento | O que tem |
|---|---|
| [docs/TOPOLOGIA.md](docs/TOPOLOGIA.md) | serviços, redes, volumes, portas, domínios, quem fala com quem, onde mora cada estado |
| [docs/CICLO-DE-VIDA.md](docs/CICLO-DE-VIDA.md) | o caminho de cada requisição (comentário, mensagem, revisão, follow-up, handover, falhas), com tempos e o que é gravado |
| [docs/ARVORES-DE-DECISAO.md](docs/ARVORES-DE-DECISAO.md) | oferta, SPICED, preço e link, escalar, revisor, guardrail, follow-up, credencial na conversa |
| [docs/_fatos-vm.md](docs/_fatos-vm.md) | levantamento bruto da VM (imagens, réplicas, redes, volumes, portas) |
| [docs/MAPA-INTEGRACOES.md](docs/MAPA-INTEGRACOES.md) | os 27 pontos de integração (inclui o site e a Kiwify), abertura do dia e limites |
| `hermes-sdr/ARQUITETURA.md`, `sdr-brain/README.md` | documentação que já existia junto do código |

## O que tem em cada pasta

| Pasta | O que é | De onde veio (VM1) |
|---|---|---|
| `stacks/` | os YAML do Docker Swarm de cada stack (bridge, chatwoot, evogo, hermes, omniroute, openreply, sdr, traefik) e `secrets.env.exemplo` (só os nomes) | `/opt/stacks/*.yml`, `/opt/openreply/deploy/openreply-stack.yml`, `~/orca/projects/portainer-install/{traefik-stack.yml,traefik-dynamic.yml,sdr-brain/stack.yml}` |
| `bridge-src/` | a bridge (FastAPI): webhook da Evolution e do Chatwoot, acúmulo de mensagens, **fila para o Hermes** (8 de cada vez, nova tentativa no 429), contexto confiável, diretivas, guardrail, follow-ups, handover; testes e fixtures | `~/orca/projects/portainer-install/bridge-src` (imagem `evolution-chatwoot-bridge:sdr-v13.1`) |
| `sdr-brain/` | o cérebro (FastAPI): `/review` (revisor), `/events/*` (supervisor, próximo passo), laço de follow-up, CRM no Chatwoot, enriquecimento do Instagram; prompts em `prompts/` | `~/orca/projects/portainer-install/sdr-brain` (imagem `sdr-brain:v3.2`) |
| `hermes-sdr/` | SOUL do agente, `ofertas.json` (preços e links que vão no contexto), `capacidade.json` (vagas do Raio-X), simulador e personas | `~/orca/projects/portainer-install/hermes-sdr` (montada em `/sdr` na bridge) |
| `hermes/volume-dados/` | o SOUL que o Hermes está usando, o `config.yaml` (modelo, provedor, ferramentas) e os nomes do `.env` | volume `hermes_chatwoot_data` (`/opt/data`) |
| `hermes/volume-politica/` | a política gerenciada do Hermes (ferramentas liberadas) | volume `hermes_policy` (`/opt/hermes-policy`, só leitura) |
| `openreply/` | as customizações que fizemos no OpenReply, como patches sobre o projeto original (`github.com/diwenne/openreply`), e o histórico | `/opt/openreply` (branch `sdr-tracking`) |

**Segredos:** nenhum valor real. Onde havia segredo agora tem `${NOME_DA_VARIAVEL}`. Os valores ficam no Bitwarden (org TSX, collection Recovery) e nos arquivos da VM listados abaixo. Os números de telefone e e-mails que aparecem nos testes e fixtures são de teste ou do próprio Talles.

## ⚠️ O que existe na VM1 e não pode ser apagado

A VM é a fonte de verdade. Este repo é uma cópia para revisão; apagar qualquer item abaixo derruba ou descaracteriza o agente.

**Arquivos e pastas**

| Caminho | Por que importa |
|---|---|
| `/opt/stacks/*.yml` e **`/opt/stacks/secrets.env`** | as stacks com os **segredos reais** (este repo só tem os nomes) |
| `/opt/openreply/` (git, branch `sdr-tracking`) e `/opt/openreply/deploy/openreply-stack.yml` (dono root) | o OpenReply com as nossas customizações (link rastreado com o @, atribuição de clique) e a stack com segredos |
| `~/orca/projects/portainer-install/` | **fonte do agente que está no ar** (bridge-src, sdr-brain, hermes-sdr). Tem mudanças **não commitadas** que são exatamente a produção; tem também `CREDENTIALS.md` e `creds/` (segredos, não copiados para cá) |
| `~/orca/projects/portainer-install/hermes-sdr/ofertas.json` e `capacidade.json` | os fatos de oferta lidos a cada turno (montados em `/sdr`) |
| `~/backups-agente/antes-v13-20261007-0655.tgz` | fonte do agente antes da troca de 07/10 (rollback) |
| `~/orca/projects/portainer-install/bridge-src/app.py.antes-fila.20261007-0647` | a bridge antes da fila (rollback) |
| `~/orca/projects/portainer-install/bridge-src/app.py.antes-humano.20261008-0317` | a bridge antes de a resposta humana contar como `last_agent_ts` (rollback da `sdr-v13.1`) |
| `~/orca/projects/portainer-install/hermes-sdr/SOUL.md.antes-tsx77.20261007` | o SOUL antes da TSX-77 (rollback) |
| `~/orca/projects/portainer-install/hermes-sdr/ofertas.json.antes-kvm8.20261008-0300` | os fatos da oferta antes do KVM 8 (rollback) |
| `~/orca/projects/portainer-install/hermes-sdr/ofertas.json.antes-prod-tsx77.20261008-0345` | os fatos da oferta antes da última troca da TSX-77 (rollback) |
| `~/orca/projects/portainer-install/sdr-brain/*.antes-tsx77.20261007` | o brain antes da TSX-77 (rollback) |
| `~/orca/projects/portainer-install/sdr-brain/*.antes-fup.20261008-0145` | o brain antes do recomeço do relógio do follow-up (rollback) |
| `/swapfile` (8 GB), a linha dele em `/etc/fstab` e `/etc/sysctl.d/99-swap.conf` | swap criado em 07/10 |
| `~/.hermes/` | o **outro** Hermes (do host, Telegram/Orca). Não é o do WhatsApp, mas roda na mesma VM |

**Volumes Docker (têm estado; apagar = perder dado)**

| Volume | O que guarda |
|---|---|
| `evogo_data`, `evogo_postgres` | a **sessão do WhatsApp** (apagar = reconectar por QR) e o banco da Evolution |
| `evolution_chatwoot_bridge` | `bridge.db`: contatos, mensagens, registros do agente (`sdr_records`), follow-ups, handovers |
| `sdr_sdr_brain_data` | `sdr-brain.db`: decisões, sequências de follow-up, `lead_steps` (próximo passo) |
| `hermes_chatwoot_data` | SOUL, `config.yaml`, `.env`, **sessões e memória** de cada conversa; `backups/SOUL.md.antes-v13.20261007-0657` |
| `hermes_policy` | a política gerenciada do Hermes |
| `chatwoot_postgres`, `chatwoot_storage`, `chatwoot_redis` | todo o Chatwoot (conversas, anexos, filas do sidekiq) |
| `openreply_postgres_data`, `openreply_redis_data` | campanhas, DMs, cliques, fila de DMs do OpenReply |
| `omniroute_data`, `omniroute_redis` | contas e chaves do OmniRoute (o acesso aos modelos) |
| `traefik_certificates` | certificados HTTPS |
| `vaultwarden_data` | o cofre (Bitwarden) |
| `integration_bridge_stt_cache` | cache do modelo de transcrição de áudio (recria sozinho, mas demora) |

**Imagens:** no ar, `evolution-chatwoot-bridge:sdr-v13.1` e `sdr-brain:v3.2`. Servem de rollback: `evolution-chatwoot-bridge:sdr-v12`, `:sdr-v12-fila`, `:sdr-v13`; `sdr-brain:v2`, `:v3`; `openreply:sdr-v2`.

**Pode apagar quando quiser** (criados para teste em 06–07/10): serviços `hermes_teste_hermes` e `sdr_teste_brain`, volumes `hermes_teste_data` e `sdr_teste_brain_data`, e os temporários `/tmp/simpkg`, `/tmp/sim1.sh`, `/tmp/simout*`.

## Versões no ar (08/10, ~03:45 BRT)

| Peça | Versão |
|---|---|
| bridge | `evolution-chatwoot-bridge:sdr-v13.1`, sessão `wa:v13:` |
| brain | `sdr-brain:v3.2` |
| Hermes | `hermes-agent:latest`, SOUL md5 `62203261`, modelo `agy/gemini-3.7-flash-high` |
| OpenReply | `openreply:sdr-v2`; a palavra "time" está na campanha `raiox` |

**Domínios:** `chatwoot.talles.dev`, `openreply.talles.dev`, `evolution.talles.dev`, `omni.talles.dev`, `manager.talles.dev` (Portainer), `vault.talles.dev`.

**Cópia de trabalho:** `C:\Users\talle\orca\agente-sdr` está igual à produção (commit `0de5284`, 13 arquivos conferidos por md5 contra a VM1). **"1 Ano de Tokens" está no ar** como o nome do bump de R$ 100 no checkout (`ofertas.json`, `nome_no_checkout`); o agente segue chamando de "Conta do Gemini" e pode dizer o nome do checkout. A troca do `348cdb3` (o agente dizer "1 Ano de Tokens" e tirar "gemini" do guardrail) não subiu e foi desfeita nesse alinhamento.

**O que a TSX-77 mudou** (detalhe em `docs/ARVORES-DE-DECISAO.md`): no Instalador, sinal de compra recebe exemplo do caso, preço e link na mesma resposta; VPS e Codex são valor junto do preço, não triagem; preço sempre com o link (o brain acrescenta se faltar); sem "outro momento" antes do link; 2ª pessoa; reação não é resposta; "plano pago do ChatGPT", nunca o nome solto; servidor de referência KVM 8 da Hostinger, R$ 120 a R$ 200 por mês. No follow-up, o relógio recomeça quando o lead responde e o agente responde de volta, e a resposta do Talles pelo Chatwoot conta como última mensagem do agente.

## De onde vem cada coisa (para mexer)

- Agente: editar e testar em `C:\Users\talle\orca\agente-sdr` (git, com histórico e testes), copiar para `~/orca/projects/portainer-install` na VM, gerar a imagem e trocar o serviço (passo a passo em `agente-sdr/DEPLOY.md`).
- SOUL: muda no volume `hermes_chatwoot_data` (`install -m 444 -o 10000 -g 10000`); vale para sessões novas; para todas, subir `HERMES_SESSION_PREFIX`.
- Preço ou link: `hermes-sdr/ofertas.json` na VM (sem reiniciar).
- **Nunca** dar `docker stack deploy` da stack `sdr` sem exportar os segredos (`SDR_BRAIN_TOKEN`, `SDR_BRAIN_LLM_KEY`, `CHATWOOT_API_TOKEN`, `META_GRAPH_TOKEN`, `OPENREPLY_DSN`): o deploy apaga o token da Meta.
- Evolution: uma réplica só (duas brigam pela sessão do WhatsApp).
