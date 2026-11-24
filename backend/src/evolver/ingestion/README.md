# Ingestão das medições

`python -m evolver.ingestion` assina os tópicos MQTT v1 e do piloto. Para cada
mensagem v1 de OD, pH ou temperatura, valida os campos e associa o vial ao
experimento que o ocupava no horário da medição. Registra `gravada`, `duplicada` ou o motivo
da rejeição. Precisa de `DATABASE_URL` e `MQTT_INGESTION_PASSWORD`; aceita `MQTT_HOST`
e `MQTT_PORT`.

Para OD recente, a ingestão decide o estado do grupo simulado `[1, 2, 3]`
conforme os limites do experimento. Publica um comando não retido por ação do
grupo com `pump_id: 1` e persiste um único estado confirmado ou desconhecido a
partir do resultado do simulador. Consulte o [fluxo de controle do grupo](../../../../docs/arquitetura-atual.md#como-o-grupo-de-bombas-é-controlado).
A perda da sessão MQTT exige reconciliação com desligamento confirmado antes de
novas decisões automáticas.

Nesta prova inicial, o PUBACK confirma somente o transporte até o broker. O simulador
não recebe confirmação de gravação nem reenvia mensagens após falha da ingestão.
