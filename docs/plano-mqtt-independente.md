# MQTT independente e produtor de telemetria

## Objetivo

Executar o Mosquitto em `mqtt/`, independentemente do backend e do banco, e observar
telemetria do simulador. O produtor envia OD, pH e temperatura mockados como eventos
`TelemetryEvent` do contrato `1.0`. Os valores são apenas simulados, sem precisão científica.

```text
Simulador Python -> MQTT 5 / Mosquitto -> assinante de teste
```

O tópico é `evolver/v1/{equipment_id}/telemetry`, com QoS 1 e sem retenção. O PUBACK
confirma o transporte, não processamento nem gravação no banco. A ACL do broker ainda
aceita o tópico temporário `evolver/dev/...`: o produtor também envia nele cada
temperatura, no formato usado pela ingestão atual. OD e pH continuam apenas no
tópico versionado. A identidade padrão `evolver-sim-01` só tem acesso aos
próprios tópicos. Para outro equipamento, configure também credenciais e ACL no broker.

## Preparação

Instale Docker Desktop com Compose v2 e `uv`. Inicie o Docker Desktop e aguarde o
serviço ficar disponível. Na raiz do repositório, no PowerShell:

```powershell
Copy-Item mqtt/.env.example mqtt/.env
Copy-Item simulator/.env.example simulator/.env
uv sync --all-packages --group dev --frozen
```

A senha `MQTT_SIMULATOR_PASSWORD` deve ser igual em `mqtt/.env` e `simulator/.env`.
Os valores de exemplo são apenas para desenvolvimento local. Para salvar temperatura
na ingestão, ajuste `VIAL_ID` para o número do frasco cadastrado no banco.

## Iniciar o broker

Na raiz do repositório:

```powershell
docker compose --project-directory mqtt config --quiet
docker compose --project-directory mqtt up -d
docker compose --project-directory mqtt ps
docker compose --project-directory mqtt exec mosquitto sh /mosquitto/config/smoke-test.sh
```

Aguarde o serviço ficar `healthy`; o smoke test verifica autenticação, ACL e fluxos.

## Observar os eventos

Abra dois terminais na raiz. Inicie primeiro o assinante no terminal A:

```powershell
docker compose --project-directory mqtt exec mosquitto sh -c 'mosquitto_sub -V mqttv5 -h 127.0.0.1 -u evolver-ingestion -P "$MQTT_INGESTION_PASSWORD" -t "evolver/v1/+/telemetry" -q 1 -C 3 -v'
```

No terminal B, execute uma rodada finita:

```powershell
uv run --env-file simulator/.env --package evolver-cnpem-simulator python -m evolver_simulator --max-messages 3
```

O assinante recebe três eventos JSON: `od`, `ph` e `temperature`, nessa ordem. Cada
um inclui `schema_version`, `event_id`, `producer_id`, `equipment_id`, `vial_id`,
`measurement_type`, `value`, `generated_at` e `sequence`. Os logs do produtor
registram os eventos confirmados pelo broker. O assinante encerra após os três eventos.
A temperatura também é enviada ao tópico temporário usado pela ingestão; a ingestão
precisa estar ativa para salvá-la. Sem `--max-messages`, o produtor gera três
medições de cada tipo por frasco e encerra. As demais opções estão em
[simulator/README.md](../simulator/README.md).

Se o broker estiver desligado ou a autenticação falhar, o simulador informa a falha e
encerra com código diferente de zero. Para desligar o broker preservando seu volume:

```powershell
docker compose --project-directory mqtt down
```

Não use `-v` como rotina: ele apaga o volume persistente do broker. Fila SQLite,
ACK após gravação, comandos, TLS e frontend não fazem parte deste teste. Para
conferir a gravação, consulte o log da ingestão e `temperature_readings`.
