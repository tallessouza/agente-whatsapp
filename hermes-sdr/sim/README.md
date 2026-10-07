# Simulador de lead

Conversa um lead simulado (outro modelo, com persona) contra o pipeline real:
Hermes + contexto de sistema + divisão de mensagens + revisor do sdr-brain +
guardrail + correção de memória. Nada vai ao WhatsApp nem ao Chatwoot.

```bash
S=hermes-sdr/sim
B=$(sudo docker ps -q -f name=integration_bridge | head -1)
sudo docker exec $B mkdir -p /tmp/simsrc
for f in app.py sdr.py handover.py; do sudo docker cp bridge-src/$f $B:/tmp/simsrc/$f; done
sudo docker cp $S/simulate.py $B:/tmp/simsrc/simulate.py
sudo docker cp $S/persona-marina.md $B:/tmp/persona.md
# SIM_LLM_KEY: a API key "sdr-brain" do OmniRoute (CREDENTIALS.md)
sudo docker exec -e SIM_LLM_KEY=... -e SIM_TURNS=18 -e PYTHONPATH=/tmp/simsrc -w /tmp/simsrc $B python simulate.py
```

O Hermes usa o `SOUL.md` instalado no volume: instale a versão a testar antes.
Sessões `test:sim:<ts>` não afetam leads reais.
