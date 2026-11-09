# Ingestão de temperatura

`python -m evolver.ingestion` assina `evolver/dev/+/telemetry` no Mosquitto. Para cada
mensagem, valida os campos, confere se o vial pertence ao equipamento e grava a
temperatura no PostgreSQL. Registra no terminal `gravada`, `duplicada` ou o motivo
da rejeição. Precisa de `DATABASE_URL` e `MQTT_INGESTION_PASSWORD`; aceita `MQTT_HOST`
e `MQTT_PORT`.

Nesta prova inicial, o PUBACK confirma somente o transporte até o broker. O simulador
não recebe confirmação de gravação nem reenvia mensagens após falha da ingestão.
