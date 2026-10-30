# Produtor externo de telemetria simulada

O projeto `evolver-cnpem-simulator` publica somente medições simuladas de OD no
broker MQTT do piloto. Ele é independente do backend: importa o contrato
compartilhado `evolver_contracts`, não acessa PostgreSQL e não importa
`evolver.db` ou `evolver.api`.

Os valores não representam calibração nem precisão científica. Cada mensagem é
validada como `TelemetryEvent` e publicada em
`evolver/v1/{equipment_id}/telemetry` com MQTT 5, QoS 1 e `retain=False`.

## Configuração

Copie `.env.example` para `.env` na raiz do repositório. As variáveis abaixo são
lidas do ambiente e, se existir, desse arquivo:

| Variável | Padrão | Regra |
| --- | --- | --- |
| `MQTT_HOST` | `127.0.0.1` | Endereço não vazio do broker. |
| `MQTT_PORT` | `1883` | Porta entre 1 e 65535. |
| `MQTT_PROTOCOL_VERSION` | `5` | Somente MQTT 5 é aceito. |
| `MQTT_SIMULATOR_PASSWORD` | obrigatória | Senha do usuário do equipamento. |
| `MQTT_KEEPALIVE_SECONDS` | `60` | Inteiro positivo. |
| `MQTT_CONNECT_TIMEOUT_SECONDS` | `10` | Espera positiva pelo CONNACK. |
| `MQTT_PUBLISH_TIMEOUT_SECONDS` | `10` | Espera positiva pelo PUBACK. |
| `SIMULATOR_EQUIPMENT_ID` | `evolver-sim-01` | Identificador e usuário MQTT. |
| `SIMULATOR_PRODUCER_ID` | `simulator-local-01` | Identificador do processo produtor. |
| `SIMULATOR_VIAL_IDS` | `vial-01,vial-02,vial-03` | De 1 a 16 IDs únicos separados por vírgula. |
| `SIMULATOR_INTERVAL_SECONDS` | `2.0` | Intervalo positivo entre mensagens. |
| `SIMULATOR_SEED` | `2026` | Semente inteira do ruído pseudoaleatório. |
| `SIMULATOR_OD_BASELINE` | `0.35` | Base não negativa da OD simulada. |
| `SIMULATOR_OD_VARIATION` | `0.08` | Amplitude não negativa da curva periódica. |
| `SIMULATOR_OD_NOISE` | `0.005` | Ruído uniforme entre 0 e 0.1. |
| `SIMULATOR_MAX_MESSAGES` | ausente | Inteiro positivo; limita a execução para testes. |
| `SIMULATOR_PAUSE_AFTER_MESSAGES` | ausente | Pausa uma vez depois de N publicações. |
| `SIMULATOR_PAUSE_SECONDS` | ausente | Duração positiva da pausa; configurada junto com a variável anterior. |
| `SIMULATOR_FAIL_AFTER_MESSAGES` | ausente | Encerra com falha simulada depois de N publicações. |

O valor padrão de `SIMULATOR_EQUIPMENT_ID` é também o usuário MQTT autorizado
pela ACL em `infra/mosquitto/acl`. Alterar o equipamento exige criar a identidade
e o bloco de ACL correspondentes; mudar somente a variável não concede acesso.

## Execução

Na raiz do repositório, instale o workspace e inicie o broker:

```bash
uv sync --all-packages --group dev --frozen
docker compose up -d mosquitto
```

Para publicar continuamente até receber `Ctrl+C`, `SIGINT` ou `SIGTERM`:

```bash
uv run --package evolver-cnpem-simulator python -m evolver_simulator
```

Para uma execução finita e segura, sem alterar `.env`:

```bash
uv run --package evolver-cnpem-simulator python -m evolver_simulator --max-messages 5
```

Para reproduzir uma pausa, configure as duas variáveis abaixo. A pausa substitui
uma vez o intervalo normal depois da terceira publicação; o limite precisa ser
maior que três para haver uma publicação posterior à retomada:

```env
SIMULATOR_PAUSE_AFTER_MESSAGES=3
SIMULATOR_PAUSE_SECONDS=10
SIMULATOR_MAX_MESSAGES=5
```

Para reproduzir um encerramento por falha após exatamente três publicações:

```env
SIMULATOR_FAIL_AFTER_MESSAGES=3
SIMULATOR_MAX_MESSAGES=5
```

Pausa e falha não podem ser habilitadas na mesma execução. A falha simulada
encerra com código `3`; configuração inválida usa `2` e falha MQTT usa `1`.

Os logs registram conexão, `event_id`, sequência, vial e tópico de cada publicação.
A confirmação de QoS 1 registrada pelo produtor é apenas o PUBACK do transporte;
não comprova persistência no banco nem substitui o ACK de aplicação futuro.

Para observar cinco eventos com a identidade de ingestão do ambiente Compose:

```bash
docker compose exec -T mosquitto sh -c 'mosquitto_sub -V mqttv5 -h 127.0.0.1 -p 1883 -t evolver/v1/+/telemetry -u evolver-ingestion -P "$MQTT_INGESTION_PASSWORD" -q 1 -C 5 -v'
```

Com a mesma semente e configuração, uma nova execução repete a sequência de vials
e valores. `event_id` e horário mudam em operação normal; testes podem injetar
relógio, UUIDs e gerador pseudoaleatório.

## Limites desta etapa

- Somente OD é produzida; pH e temperatura medida ficam para ampliação posterior.
- O reinício recomeça sequência e gerador. Não há fila SQLite, estado durável,
  reenvio, quarentena nem ACK de aplicação nesta tarefa.
- Não há leitura de comandos, setpoint, bombas, API, banco, SSE ou hardware real.
- Falha de conexão ou publicação encerra o processo; um supervisor pode iniciá-lo
  novamente. Os cenários configuráveis apenas simulam pausa ou encerramento e não
  alegam reproduzir uma indisponibilidade real do broker.
