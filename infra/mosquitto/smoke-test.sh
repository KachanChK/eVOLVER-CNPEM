#!/bin/sh
# Verifica autenticação, ACLs e retenção do broker com os clientes de teste do Mosquitto.
# Uso, com o Compose no ar:
#   docker compose exec mosquitto sh /mosquitto/config/smoke-test.sh
set -u

host=127.0.0.1
eq=evolver-sim-01
other=evolver-sim-02
sim_pw=$MQTT_SIMULATOR_PASSWORD
ing_pw=$MQTT_INGESTION_PASSWORD
api_pw=$MQTT_API_PASSWORD
failures=0

# usuário senha tópico: imprime a primeira mensagem recebida em até 3 s.
sub() {
  mosquitto_sub -V mqttv5 -h "$host" -u "$1" -P "$2" -t "$3" -q 1 -C 1 -W 3 2>/dev/null
}

# usuário senha tópico mensagem [opções extras do mosquitto_pub]
pub() {
  user=$1 pw=$2 topic=$3 msg=$4
  shift 4
  mosquitto_pub -V mqttv5 -h "$host" -u "$user" -P "$pw" -t "$topic" -m "$msg" -q 1 "$@" \
    2>/dev/null
}

# Assina como ($1, $2) em $3, publica $7 como ($4, $5) em $6 e imprime o que chegou.
exchange() {
  out=$(mktemp)
  sub "$1" "$2" "$3" >"$out" &
  pid=$!
  sleep 1
  pub "$4" "$5" "$6" "$7" || true
  wait "$pid" || true
  cat "$out"
  rm -f "$out"
}

# descrição esperado obtido
check() {
  if [ "$2" = "$3" ]; then
    echo "ok    - $1"
  else
    echo "FALHA - $1 (esperado '$2', obtido '$3')"
    failures=$((failures + 1))
  fi
}

echo "Fluxos previstos no contrato"
check "simulador -> ingestão: telemetry" "t1" \
  "$(exchange evolver-ingestion "$ing_pw" "evolver/v1/+/telemetry" \
    "$eq" "$sim_pw" "evolver/v1/$eq/telemetry" t1)"
check "ingestão -> simulador: telemetry/ack" "a1" \
  "$(exchange "$eq" "$sim_pw" "evolver/v1/$eq/telemetry/ack" \
    evolver-ingestion "$ing_pw" "evolver/v1/$eq/telemetry/ack" a1)"
check "ingestão -> simulador: telemetry/rejection" "j1" \
  "$(exchange "$eq" "$sim_pw" "evolver/v1/$eq/telemetry/rejection" \
    evolver-ingestion "$ing_pw" "evolver/v1/$eq/telemetry/rejection" j1)"
check "API -> simulador: commands" "c1" \
  "$(exchange "$eq" "$sim_pw" "evolver/v1/$eq/commands" \
    evolver-api "$api_pw" "evolver/v1/$eq/commands" c1)"
check "simulador -> ingestão: command-results" "r1" \
  "$(exchange evolver-ingestion "$ing_pw" "evolver/v1/+/command-results" \
    "$eq" "$sim_pw" "evolver/v1/$eq/command-results" r1)"

echo "Permissões negadas"
check "simulador não publica telemetria de outro equipamento" "" \
  "$(exchange evolver-ingestion "$ing_pw" "evolver/v1/+/telemetry" \
    "$eq" "$sim_pw" "evolver/v1/$other/telemetry" x)"
check "simulador não lê ACK de outro equipamento" "" \
  "$(exchange "$eq" "$sim_pw" "evolver/v1/$other/telemetry/ack" \
    evolver-ingestion "$ing_pw" "evolver/v1/$other/telemetry/ack" x)"
check "simulador não publica comandos" "" \
  "$(exchange "$eq" "$sim_pw" "evolver/v1/$eq/commands" \
    "$eq" "$sim_pw" "evolver/v1/$eq/commands" x)"
check "ingestão não publica comandos" "" \
  "$(exchange "$eq" "$sim_pw" "evolver/v1/$eq/commands" \
    evolver-ingestion "$ing_pw" "evolver/v1/$eq/commands" x)"

if mosquitto_pub -V mqttv5 -h "$host" -t evolver/health -m x -q 1 2>/dev/null; then
  anonymous=aceito
else
  anonymous=recusado
fi
check "cliente anônimo" "recusado" "$anonymous"

if pub "$eq" wrong-password "evolver/v1/$eq/telemetry" x; then
  wrong_pw=aceito
else
  wrong_pw=recusado
fi
check "senha errada" "recusado" "$wrong_pw"

echo "Retenção"
pub "$eq" "$sim_pw" "evolver/v1/$eq/telemetry" retained -r || true
check "mensagem retida não é entregue a quem assina depois" "" \
  "$(sub evolver-ingestion "$ing_pw" "evolver/v1/$eq/telemetry" || true)"

if [ "$failures" -eq 0 ]; then
  echo "Todas as verificações passaram."
else
  echo "$failures verificação(ões) falharam."
  exit 1
fi
