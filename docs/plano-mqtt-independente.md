# MQTT independente e produtor de telemetria

O Mosquitto roda em `mqtt/`, separado do banco e dos processos Python. O simulador
consulta a ingestão pelos tópicos `evolver/dev/evolver-sim-01/active-vials/request`
e `.../response`, depois publica OD, pH e temperatura no tópico
`evolver/v1/evolver-sim-01/telemetry`. Usa MQTT 5, QoS 1 e mensagens não retidas.
O PUBACK confirma entrega ao broker, não a gravação no banco.

Prepare os arquivos `.env`, as dependências e os serviços conforme o
[README principal](../README.md). A ingestão, o banco e o broker precisam estar
em execução, e pelo menos um experimento deve estar ativo para observar eventos.

Na raiz do repositório, execute uma rodada:

```powershell
.\scripts\simular.ps1
```

São dez rodadas a cada 0,5 segundo. Cada vial ativo recebe uma medição de OD, pH
e temperatura por rodada. Para testar somente os três primeiros eventos:

```powershell
uv run --env-file simulator/.env --package evolver-cnpem-simulator python -m evolver_simulator --max-messages 3
```

Para observar as mensagens no broker, assine o tópico versionado antes de iniciar
o simulador:

```powershell
docker compose --env-file mqtt/.env -f mqtt/compose.yaml exec mosquitto sh -c 'mosquitto_sub -V mqttv5 -h 127.0.0.1 -u evolver-ingestion -P "$MQTT_INGESTION_PASSWORD" -t "evolver/v1/+/telemetry" -q 1 -v'
```

O log da ingestão e as tabelas de leituras confirmam o salvamento. O
[guia do simulador](../simulator/README.md) descreve as opções de teste.
