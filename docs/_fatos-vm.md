# Fatos da VM1 coletados em 2026-10-07T05:20Z (sem valores de segredo)

Atualizado em 08/10/2026, ~03:45 (BRT), depois da sessão TSX-77: só as imagens de `integration_bridge` (`sdr-v13` → `sdr-v13.1`) e `sdr_brain` (`v3` → `v3.2`). O resto não foi coletado de novo.

| serviço | imagem | réplicas | redes | volumes/montagens | portas publicadas |
|---|---|---|---|---|---|
| chatwoot_postgres | pgvector/pgvector:pg16 | 1/1 | ai_stack | chatwoot_postgres→/var/lib/postgresql/data  |  |
| chatwoot_prepare | chatwoot/chatwoot:v4.18.0 | 0/1 | ai_stack | chatwoot_storage→/app/storage  |  |
| chatwoot_rails | chatwoot/chatwoot:v4.18.0 | 1/1 | ai_stack | chatwoot_storage→/app/storage  | 3001→3000/host  |
| chatwoot_redis | redis:7-alpine | 1/1 | ai_stack | chatwoot_redis→/data  |  |
| chatwoot_sidekiq | chatwoot/chatwoot:v4.18.0 | 1/1 | ai_stack | chatwoot_storage→/app/storage  |  |
| evogo_evolution | evoapicloud/evolution-go:latest | 1/1 | ai_stack | evogo_data→/app/dbdata evogo_logs→/app/logs  | 4000→4000/host  |
| evogo_postgres | postgres:16 | 1/1 | ai_stack | evogo_postgres→/var/lib/postgresql/data  |  |
| hermes_hermes | hermes-agent:latest | 1/1 | ai_stack | hermes_chatwoot_data→/opt/data hermes_policy→/opt/hermes-policy(ro)  | 8642→8642/host  |
| hermes_teste_hermes | hermes-agent:latest | 1/1 | ai_stack | hermes_teste_data→/opt/data hermes_policy→/opt/hermes-policy(ro)  |  |
| integration_bridge | evolution-chatwoot-bridge:sdr-v13.1 | 1/1 | ai_stack | /home/ubuntu/orca/projects/portainer-install/hermes-sdr→/sdr(ro) evolution_chatwoot_bridge→/data hermes_chatwoot_data→/hermes-data(ro) integration_bridge_stt_cache→/root/.cache  |  |
| omniroute_omniroute | diegosouzapw/omniroute:latest | 1/1 | ai_stack | omniroute_data→/app/data  | 20128→20128/host 20129→20129/host  |
| omniroute_redis | redis:7-alpine | 1/1 | ai_stack | omniroute_redis→/data  |  |
| openreply_cron | openreply:sdr-v2 | 1/1 | openreply_internal |  |  |
| openreply_migrate | openreply:sdr-v2 | 0/1 | openreply_internal |  |  |
| openreply_postgres | postgres:16 | 1/1 | openreply_internal | openreply_postgres_data→/var/lib/postgresql/data  |  |
| openreply_redis | redis:7-alpine | 1/1 | openreply_internal | openreply_redis_data→/data  |  |
| openreply_web | openreply:sdr-v2 | 1/1 | openreply_internal openreply_public |  | 3000→3000/host  |
| openreply_worker | openreply:sdr-v2 | 1/1 | openreply_internal |  |  |
| sdr_brain | sdr-brain:v3.2 | 1/1 | ai_stack openreply_internal | sdr_sdr_brain_data→/data  |  |
| sdr_teste_brain | sdr-brain:v3.2 | 1/1 | ai_stack | sdr_teste_brain_data→/data  |  |
| traefik_traefik | traefik:v3 | 1/1 | host | /var/run/docker.sock→/var/run/docker.sock(ro) traefik_certificates→/letsencrypt  |  |
| vaultwarden_vaultwarden | vaultwarden/server:latest | 1/1 | vaultwarden_default | vaultwarden_data→/data  | 8088→80/host  |

Domínios (Traefik):

Swap: /swapfile 8G  RAM: 11 GB
