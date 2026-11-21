# Ingestão das medições

`python -m evolver.ingestion` assina os tópicos MQTT v1 e do piloto. Para cada
mensagem v1 de OD, pH ou temperatura, valida os campos e associa o vial ao
experimento que o ocupava no horário da medição. Registra `gravada`, `duplicada` ou o motivo
da rejeição. Precisa de `DATABASE_URL` e `MQTT_INGESTION_PASSWORD`; aceita `MQTT_HOST`
e `MQTT_PORT`.

Nesta prova inicial, o PUBACK confirma somente o transporte até o broker. O simulador
não recebe confirmação de gravação nem reenvia mensagens após falha da ingestão.
