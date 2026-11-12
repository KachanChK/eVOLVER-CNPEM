# Ingestão de temperatura

`python -m evolver.ingestion` assina `evolver/dev/+/telemetry` no Mosquitto. Para cada
mensagem, valida a alocação do vial no horário de geração e grava a temperatura por
experimento no PostgreSQL. Também atende à consulta MQTT de vials ativos do simulador.
Registra no terminal `gravada`, `duplicada` ou o motivo da rejeição. Precisa de
`DATABASE_URL` e `MQTT_INGESTION_PASSWORD`. Aceita `MQTT_HOST` e `MQTT_PORT`.

Nesta prova inicial, o PUBACK confirma somente o transporte até o broker. O simulador
não recebe confirmação de gravação nem reenvia mensagens após falha da ingestão.
