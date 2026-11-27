# Ingestão das medições

`python -m evolver.ingestion` assina os tópicos MQTT v1 e do piloto. Para cada
mensagem v1 de OD, pH ou temperatura, valida os campos e associa o vial ao
experimento que o ocupava no intervalo `[started_at, ended_at)`. Publica
`persisted` ou `duplicate` em `telemetry/ack` somente após o commit síncrono.
Uma falha permanente correlacionável produz `telemetry/rejection` e aparece no
log com o UUID. Indisponibilidade e horário de geração futuro deixam a tentativa
sem desfecho para reenvio pelo simulador. Precisa de `DATABASE_URL` e
`MQTT_INGESTION_PASSWORD`. Aceita `MQTT_HOST`
e `MQTT_PORT`.

Para OD recente, a ingestão decide o estado do grupo simulado `[1, 2, 3]`
conforme os limites do experimento. Publica um comando não retido por ação do
grupo com `pump_id: 1` e persiste um único estado confirmado ou desconhecido a
partir do resultado do simulador. Consulte o [fluxo de controle do grupo](../../../../docs/arquitetura-atual.md#como-o-grupo-de-bombas-é-controlado).
A perda de conexão com MQTT ou com o banco exige reconciliação antes de novas
decisões automáticas. O processo tenta conectar de novo durante a execução.
A OD reenviada com `evolver-telemetry-mode=history` entra no histórico e fica
inelegível para o controle e para a retomada da automação.

Pare a ingestão antiga, aplique a migração com `alembic upgrade head` e verifique
a ingestão atualizada antes de iniciar o simulador com a fila de reenvio.
Confira os [procedimentos de operação e recuperação](../../../../operations/README.md#recuperação-de-telemetria).
