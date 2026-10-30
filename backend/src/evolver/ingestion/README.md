# Ingestão

Processo Python que assina a telemetria MQTT, valida cada mensagem com os modelos de
`evolver_contracts`, grava no PostgreSQL + TimescaleDB e só depois do commit publica
a confirmação de aplicação (`telemetry/ack`) ou a rejeição (`telemetry/rejection`).
As regras de tópicos, QoS e confirmação estão no
[contrato MQTT](../../../../packages/contracts/src/evolver_contracts/README.md).

## Executar

Com Mosquitto e TimescaleDB saudáveis e as migrações aplicadas (veja
[operações](../../../../operations/README.md)), na raiz do repositório:

```powershell
uv run --env-file .env --package evolver-cnpem-backend python -m evolver.db.seed
uv run --env-file .env --package evolver-cnpem-backend python -m evolver.ingestion
```

O `seed` cadastra o equipamento `evolver-sim-01` e o vial `vial-01` até existir o
cadastro de metadados (E3 · T10). Ele pode ser repetido; use `--vial` para mais vials.
A ingestão lê `MQTT_HOST`, `MQTT_PORT`, `MQTT_INGESTION_PASSWORD` e o banco por
`DATABASE_URL` ou pelas variáveis `POSTGRES_*`, com os mesmos padrões do `.env.example`.

No Windows, o processo usa `SelectorEventLoop`, pois o `ProactorEventLoop` padrão não
oferece o `add_reader` exigido pelo `aiomqtt`. A execução foi verificada em Linux
(contêiner `uv` na rede do Compose); falta registrar a verificação no Windows nativo.

## Fluxo de uma mensagem

1. `received_at` é registrado na chegada. `generated_at` vem do produtor e nunca é
   derivado de `received_at`.
2. `validation.py` confere, sem banco: tópico `evolver/v1/{equipment_id}/telemetry`,
   JSON UTF-8, `event_id` UUID, `schema_version`, o modelo `TelemetryEvent` em modo
   estrito (número em texto não vira número), `equipment_id` do payload igual ao do
   tópico, valor finito e `generated_at` no máximo 5 minutos à frente do relógio
   (`INGESTION_MAX_CLOCK_SKEW_SECONDS`).
3. `persistence.py` abre uma transação, localiza a posição habilitada pelo par
   `(equipment_id, vial_id)` e reserva o `event_id` em `processed_event_ids` com
   `INSERT ... ON CONFLICT DO NOTHING`. Se reservou, grava a medição na mesma transação;
   se o ID já existia, responde com o desfecho da primeira entrega.
4. Depois do commit, `service.py` publica a resposta com QoS 1 no tópico de origem.

| Situação | Banco | Resposta |
| --- | --- | --- |
| Evento novo e válido | ledger `persisted` + medição | `ack` `persisted` |
| Reenvio de evento gravado (mesmo com conteúdo diferente) | nada muda | `ack` `duplicate` |
| Payload inválido com `event_id` legível | ledger `quarantined` + `audit_events` | `rejection` com motivo |
| Reenvio de evento em quarentena | nada muda | a mesma `rejection` |
| JSON ilegível, sem `event_id` UUID ou tópico fora do contrato | nada | nenhuma; só log de erro |
| Falha de banco ou erro inesperado | rollback | nenhuma; o produtor reenvia |

Motivos de rejeição usados:

- `schema_invalid`: payload fora do modelo, valor não finito, `generated_at` no futuro
  ou `experiment_run_id` que não pertence à posição do vial (o contrato v1 não tem
  motivo próprio para execução desconhecida);
- `unsupported_schema_version`: `schema_version` diferente de `1.0`;
- `invalid_origin`: `equipment_id` do payload diferente do tópico. O broker autentica
  o tópico, por isso a resposta sempre vai para o tópico de origem;
- `unknown_equipment` e `unknown_vial`: equipamento ou vial sem cadastro habilitado.

A quarentena fica em `audit_events` (`action = 'telemetry_quarantined'`,
`entity_id = event_id`), com motivo, detalhe e o payload recebido em texto, para
tratamento manual. Um vial cadastrado depois não libera o evento: o produtor deve
mover o item para sua própria quarentena, como define o contrato.

Dados atrasados são gravados com o `generated_at` original. A view
`latest_measurements` escolhe a leitura atual pelo horário de produção, então um
evento atrasado entra no histórico sem substituir a leitura mais recente.

## Sessão MQTT

O cliente usa o ID `evolver-ingestion` (`MQTT_INGESTION_CLIENT_ID`) com `clean_start`
desligado e sessão de 1 hora (`MQTT_INGESTION_SESSION_EXPIRY_SECONDS`): durante um
reinício curto da ingestão, o broker guarda a telemetria QoS 1 recebida. Rode uma
única ingestão por ID. Uma mensagem já entregue cuja gravação falhou não volta do
broker; quem garante o reenvio é a fila local do produtor (E3 · T06).

## Testes

```powershell
cd backend
uv run pytest
```

Sem variáveis extras, rodam só os testes unitários. Os de integração usam o banco
descartável descrito nas [migrações](../../../migrations/README.md) e o broker do
Compose:

```powershell
$env:EVOLVER_TEST_DATABASE_URL = "postgresql+psycopg://evolver:evolver-local-only@127.0.0.1:5432/evolver_test"
$env:EVOLVER_TEST_MQTT_HOST = "127.0.0.1"
$env:MQTT_INGESTION_PASSWORD = "ingestion-local-only"
$env:MQTT_SIMULATOR_PASSWORD = "simulator-local-only"
uv run pytest -m integration
```

Os testes MQTT publicam como `evolver-sim-01` (único usuário de simulador no ACL) e
cadastram um vial próprio por teste. Eles cobrem: OD atravessando broker e banco,
reenvio respondido como duplicata com um único registro, falha de commit sem
gravação nem confirmação, quarentena sem bloquear a mensagem seguinte e evento
atrasado sem regredir a leitura atual.
