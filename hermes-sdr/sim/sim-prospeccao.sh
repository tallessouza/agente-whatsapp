#!/usr/bin/env bash
# Simula a prospecção contra o Hermes de TESTE e o brain de TESTE (nada vai ao WhatsApp nem ao Chatwoot).
# Uso, na raiz do repo na VM1: bash hermes-sdr/sim/sim-prospeccao.sh [persona ...]
# Pré-requisito: SOUL a testar instalado no volume hermes_teste_data e sdr_teste_brain na imagem nova.
set -euo pipefail
cd "$(dirname "$0")/../.."
S=hermes-sdr/sim
OUT=$S/rodadas-prospeccao
mkdir -p "$OUT"
env_of() { sudo docker service inspect "$1" --format '{{json .Spec.TaskTemplate.ContainerSpec.Env}}' \
  | python3 -c "import json,sys;print([x.split('=',1)[1] for x in json.load(sys.stdin) if x.startswith('$2=')][0])"; }
HKEY=$(env_of hermes_teste_hermes API_SERVER_KEY)
BTOKEN=$(env_of sdr_teste_brain SDR_BRAIN_TOKEN)
LKEY=$(env_of sdr_teste_brain SDR_BRAIN_LLM_KEY)
B=$(sudo docker ps -q -f name=integration_bridge | head -1)
sudo docker exec "$B" mkdir -p /tmp/simsrc
for f in app.py sdr.py handover.py prospeccao.py; do sudo docker cp "bridge-src/$f" "$B:/tmp/simsrc/$f"; done
sudo docker cp "$S/simulate.py" "$B:/tmp/simsrc/simulate.py"
sudo docker cp hermes-sdr/ofertas.json "$B:/tmp/simsrc/ofertas.json"

run() {  # nome da persona, primeira mensagem, negócio (json), minutos até responder, turnos
  local name=$1 first=$2 negocio=$3 minutos=$4 turns=$5 out=$6
  awk -v n="=== $name ===" '$0==n{p=1;next} /^=== /{p=0} p' "$S/personas-prospeccao.md" > "/tmp/persona-$name.md"
  sudo docker cp "/tmp/persona-$name.md" "$B:/tmp/persona.md"
  sudo docker exec "$B" rm -f /tmp/sim.db
  echo "######## $out" | tee "$OUT/$out.txt"
  sudo docker exec -e SIM_HERMES_URL=http://hermes_teste_hermes:8642/v1 -e SIM_HERMES_KEY="$HKEY" \
    -e SDR_BRAIN_URL=http://sdr_teste_brain:8090 -e SDR_BRAIN_TOKEN="$BTOKEN" -e SIM_LLM_KEY="$LKEY" \
    -e SIM_TURNS="$turns" -e SIM_FIRST="$first" -e SIM_PROSPECT="{\"negocio\": $negocio, \"minutos\": $minutos}" \
    -e SDR_OFFERS_FILE=/tmp/simsrc/ofertas.json -e PYTHONPATH=/tmp/simsrc -w /tmp/simsrc "$B" python simulate.py 2>&1 \
    | grep -v -E 'Evolution webhook|HTTP Request' | tee -a "$OUT/$out.txt"
}

PERSONAS=${*:-"clinica recepcao preco optout automatica"}
for p in $PERSONAS; do
  case $p in
    clinica)    run clinica "Boa noite! Desculpe a demora, como posso ajudar?" '{"nome":"Clínica Sorriso Pleno","nicho":"clínica odontológica","cidade":"São José","uf":"SC","horario_resumo":"seg a sex 8h–18h","servicos":["implante","clareamento","ortodontia"],"site_leva_pro_whatsapp":true}' 125 10 clinica ;;
    recepcao)   run recepcao "Boa noite, sim! Em que posso ajudar?" '{"nome":"Imobiliária Porto Itajaí","nicho":"imobiliária","cidade":"Itajaí","uf":"SC","horario_resumo":"seg a sex 8h–18h, sáb 9h–12h"}' 8 8 recepcao ;;
    preco)      run preco "Oi, pode falar" '{"nome":"BC Rent a Car","nicho":"locadora de veículos","cidade":"Balneário Camboriú","uf":"SC","horario_resumo":"seg a sáb 8h–19h"}' 40 10 preco ;;
    optout)     run optout "Pois não?" '{"nome":"Contábil Criciúma","nicho":"escritório de contabilidade","cidade":"Criciúma","uf":"SC"}' 180 4 optout ;;
    automatica) run optout "Olá! Obrigado por entrar em contato com a Clínica Bem Estar. Nosso horário de atendimento é de segunda a sexta, das 8h às 18h. Digite 1 para agendamento, 2 para orçamento, 3 para falar com a recepção." '{"nome":"Clínica Bem Estar","nicho":"clínica de estética","cidade":"Palhoça","uf":"SC"}' 0 1 automatica ;;
  esac
done
