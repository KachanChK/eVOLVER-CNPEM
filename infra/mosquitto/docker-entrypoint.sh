#!/bin/sh
# Gera o arquivo de senhas a partir do .env a cada início e entrega o processo ao
# entrypoint original da imagem. O arquivo fica só no contêiner, fora do Git.
set -eu

passwd_file=/mosquitto/auth/passwd

: "${MQTT_HEALTH_PASSWORD:?defina MQTT_HEALTH_PASSWORD no .env}"
: "${MQTT_INGESTION_PASSWORD:?defina MQTT_INGESTION_PASSWORD no .env}"
: "${MQTT_API_PASSWORD:?defina MQTT_API_PASSWORD no .env}"
: "${MQTT_SIMULATOR_PASSWORD:?defina MQTT_SIMULATOR_PASSWORD no .env}"

mkdir -p "$(dirname "$passwd_file")"
mosquitto_passwd -c -b "$passwd_file" evolver-health "$MQTT_HEALTH_PASSWORD"
mosquitto_passwd -b "$passwd_file" evolver-ingestion "$MQTT_INGESTION_PASSWORD"
mosquitto_passwd -b "$passwd_file" evolver-api "$MQTT_API_PASSWORD"
mosquitto_passwd -b "$passwd_file" evolver-sim-01 "$MQTT_SIMULATOR_PASSWORD"
chown mosquitto:mosquitto "$passwd_file"
chmod 0600 "$passwd_file"

exec /docker-entrypoint.sh "$@"
