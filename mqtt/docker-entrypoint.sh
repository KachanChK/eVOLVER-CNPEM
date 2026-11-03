#!/bin/sh
# Gera credenciais locais dentro do contêiner e inicia o Mosquitto.
set -eu

passwd_file=/mosquitto/auth/passwd
acl_file=/mosquitto/auth/acl

: "${MQTT_HEALTH_PASSWORD:?defina MQTT_HEALTH_PASSWORD no .env}"
: "${MQTT_INGESTION_PASSWORD:?defina MQTT_INGESTION_PASSWORD no .env}"
: "${MQTT_API_PASSWORD:?defina MQTT_API_PASSWORD no .env}"
: "${MQTT_SIMULATOR_PASSWORD:?defina MQTT_SIMULATOR_PASSWORD no .env}"

mkdir -p "$(dirname "$passwd_file")"
rm -f "$passwd_file"
mosquitto_passwd -c -b "$passwd_file" evolver-health "$MQTT_HEALTH_PASSWORD"
mosquitto_passwd -b "$passwd_file" evolver-ingestion "$MQTT_INGESTION_PASSWORD"
mosquitto_passwd -b "$passwd_file" evolver-api "$MQTT_API_PASSWORD"
mosquitto_passwd -b "$passwd_file" evolver-sim-01 "$MQTT_SIMULATOR_PASSWORD"
cp /mosquitto/config/acl "$acl_file"
chown mosquitto:mosquitto "$passwd_file" "$acl_file"
chmod 0600 "$passwd_file" "$acl_file"

exec /docker-entrypoint.sh "$@"
