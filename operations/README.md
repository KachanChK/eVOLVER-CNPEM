# Operação do ambiente local

O Docker Desktop com Compose v2 é pré-requisito. Banco e MQTT possuem arquivos
Compose independentes. Os valores de `.env.example` são exclusivos para
desenvolvimento local.

## Serviço MQTT independente

Execute dentro de `mqtt/`:

```powershell
Copy-Item .env.example .env
docker compose config --quiet
docker compose up -d
docker compose ps
docker compose exec mosquitto sh /mosquitto/config/smoke-test.sh
```

O broker deve aparecer como `healthy`. Para inspecionar mensagens do simulador,
consulte o [roteiro de observação do MQTT](../docs/legacy/plano-mqtt-independente.md).

Para encerrar somente o MQTT, preservando seu volume:

```powershell
docker compose down
```

## Serviço de banco

Os comandos das seções seguintes devem ser executados na raiz do repositório, após
copiar `.env.example` para `.env`.

## Validar a configuração

```bash
docker compose config --quiet
```

Esse comando valida a interpolação e a estrutura do Compose sem iniciar serviços.

## Iniciar e observar

```bash
docker compose up -d
docker compose ps
docker compose logs --tail=100 timescaledb
```

Espere o serviço aparecer como `healthy` antes de continuar.

## Diagnóstico do TimescaleDB

Com os valores padrão de `.env.example`:

```bash
docker compose exec timescaledb pg_isready -U evolver -d evolver
docker compose exec timescaledb psql -U evolver -d evolver -tAc "SELECT extversion FROM pg_extension WHERE extname = 'timescaledb';"
```

Se usuário ou banco forem alterados em `.env`, substitua-os nesses comandos. A
segunda consulta deve retornar a versão instalada da extensão.

## Parar

```bash
docker compose stop
```

Para remover apenas os contêineres e a rede, preservando os volumes:

```bash
docker compose down
```

Não use `docker compose down -v` como rotina: a opção `-v` apaga os volumes locais
e seus dados. Logs adicionais podem ser consultados com `docker compose logs`.

## Migrações

Com PostgreSQL saudável, aplique o schema da aplicação a partir da pasta
`backend`:

```powershell
uv sync --group dev
uv run alembic upgrade head
```

Para configuração local padrão, Alembic usa os mesmos valores de `.env.example`.
Se o banco foi personalizado, exporte `DATABASE_URL` para a sessão antes de
executar Alembic. A extensão TimescaleDB é habilitada pelo script inicial somente
quando o volume de banco nasce; revisões da aplicação são aplicadas separadamente.

## Backup e restauração

O volume `postgres_data` persiste através de `docker compose down`, mas não cobre
falha ou perda do disco do host. Faça backup lógico periódico para uma pasta segura
fora do container. Exemplo no PowerShell, usando os valores padrão locais:

```powershell
New-Item -ItemType Directory -Force backups | Out-Null
docker compose exec timescaledb pg_dump -U evolver -d evolver -Fc -f /tmp/evolver.dump
docker compose cp timescaledb:/tmp/evolver.dump ./backups/evolver.dump
```

Armazene a cópia em outro disco ou destino protegido; o dump dentro do mesmo host
não substitui uma cópia externa. Para restaurar o dump completo em um banco de destino
saudável com a extensão TimescaleDB disponível, copie o arquivo para o container e
execute as funções de preparação da extensão antes e depois do `pg_restore`:

```powershell
docker compose cp ./backups/evolver.dump timescaledb:/tmp/evolver.dump
docker compose exec timescaledb psql -U evolver -d evolver -c "SELECT timescaledb_pre_restore();"
docker compose exec timescaledb pg_restore --clean --if-exists --no-owner --exit-on-error -U evolver -d evolver /tmp/evolver.dump
docker compose exec timescaledb psql -U evolver -d evolver -c "SELECT timescaledb_post_restore();"
```

O arquivo é um dump completo, com schema e dados. Em um banco vazio, deixe o `pg_restore`
recriar os objetos; não rode `alembic upgrade head` antes. Para recriar o schema com
Alembic e restaurar somente os dados, aplique primeiro `uv run alembic upgrade head`
e troque `pg_restore` por `pg_restore --data-only --no-owner --exit-on-error ...`.
Faça uma restauração de conferência em outro banco antes de depender do backup. Troque
usuário, banco e caminho em ambos os comandos quando `.env` não usar os padrões. Não
use `docker compose down -v` como método de restauração: ele remove o volume.

## Recuperação de telemetria

Em uma atualização, mantenha o mesmo arquivo da fila e as mesmas identidades
do equipamento e do produtor. Pare o simulador e a ingestão antiga. Aplique a
migração com `alembic upgrade head`, suba a ingestão atualizada e confira que ela
publica confirmações após gravar. Inicie o simulador atualizado em seguida, pois
o controle de OD depende da interpretação de `evolver-telemetry-mode` na ingestão.
Se a migração apontar UUIDs repetidos, confira os IDs diagnosticados nas três
séries antes de prosseguir.

Mantenha a fila SQLite em disco local. O arquivo padrão é
`telemetry.sqlite3` no diretório do estado das bombas. Com 12 vials, a coleta
gera 72 eventos por segundo. A cota padrão de 259.200 inclui as pendências e
os registros em quarentena. Reserve **160 MiB** para esse perfil, considerando
o SQLite, `-wal` e `-shm`. A soma dos picos medidos foi de 136,03 MiB.
Consulte a [medição da carga e a conciliação por ID](../docs/validacao-store-and-forward.md#capacidade-com-doze-vials).

### Inspecionar a fila

Na raiz do repositório, ajuste o caminho se estiver usando
`SIMULATOR_TELEMETRY_QUEUE_PATH` ou um diretório personalizado para o estado das bombas.

```powershell
$queue = Join-Path $env:USERPROFILE '.evolver-simulator/telemetry.sqlite3'
if (-not (Test-Path -LiteralPath $queue -PathType Leaf)) { throw 'Fila SQLite ausente' }
.\.venv\Scripts\python.exe -m sqlite3 $queue "SELECT count(*) FILTER (WHERE rejected_at IS NULL) AS pendentes, count(rejected_at) AS quarentena, min(generated_at) FILTER (WHERE rejected_at IS NULL) AS pendencia_mais_antiga FROM telemetry_queue"
.\.venv\Scripts\python.exe -m sqlite3 $queue "SELECT id, event_id, rejected_at, reason_code, detail FROM telemetry_queue WHERE rejected_at IS NOT NULL ORDER BY id"
```

### Exportar e remover quarentena

Pare o simulador para que a exportação e a remoção usem o mesmo conjunto de
registros. O exemplo cria um arquivo novo com os registros rejeitados,
incluindo o payload original. Bytes inválidos ficam em hexadecimal.

```powershell
@'
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

source = Path(sys.argv[1]).resolve(strict=True)
with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as database:
    database.row_factory = sqlite3.Row
    rows = database.execute(
        "SELECT * FROM telemetry_queue WHERE rejected_at IS NOT NULL ORDER BY id"
    )
    records = []
    for row in rows:
        record = dict(row)
        if isinstance(record["payload"], bytes):
            record["payload_hex"] = record.pop("payload").hex()
        records.append(record)
with Path(sys.argv[2]).open("x", encoding="utf-8") as export:
    json.dump(records, export, ensure_ascii=False, indent=2)
'@ | .\.venv\Scripts\python.exe - $queue quarentena-evolver.json
```

Confira o arquivo exportado e substitua `123` pelo `id` do registro a remover.
Repita somente para os registros que quer retirar da cota. Reinicie o simulador
com o mesmo arquivo da fila.

```powershell
.\.venv\Scripts\python.exe -m sqlite3 $queue "DELETE FROM telemetry_queue WHERE id = 123 AND rejected_at IS NOT NULL"
```

### Exercitar uma queda

Com um experimento ativo e as três séries recebendo dados, pare o Mosquitto por
mais de 15 s. Observe a pausa de atualizações no monitoramento e o aumento das
pendências no SQLite. Restaure o broker e compare os UUIDs e os horários de
geração no SQLite e no PostgreSQL. Faça ensaios separados parando a ingestão e o
TimescaleDB. Confira a tabela de leituras e os logs após cada recuperação.

```powershell
docker compose --env-file mqtt/.env -f mqtt/compose.yaml stop mosquitto
docker compose --env-file mqtt/.env -f mqtt/compose.yaml up -d --wait mosquitto
docker compose stop timescaledb
docker compose up -d --wait timescaledb
```

Durante a queda, escolha um UUID pendente da consulta abaixo. Após a
recuperação, verifique que ele saiu da fila e que a consulta central retornou
uma única linha com o mesmo `generated_at`.

```powershell
.\.venv\Scripts\python.exe -m sqlite3 $queue "SELECT event_id, generated_at, payload FROM telemetry_queue WHERE rejected_at IS NULL ORDER BY id LIMIT 10"
$eventId = 'UUID anotado durante a queda'
@'
WITH readings AS (
    SELECT event_id, generated_at, received_at, experiment_id, 'temperature' AS series
    FROM temperature_readings
    UNION ALL
    SELECT event_id, generated_at, received_at, experiment_id, 'ph' FROM ph_readings
    UNION ALL
    SELECT event_id, generated_at, received_at, experiment_id, 'od' FROM od_readings
)
SELECT r.*, e.allocation_id
FROM readings r JOIN experiments e ON e.id = r.experiment_id
WHERE r.event_id = :'event_id'::uuid
ORDER BY r.generated_at;
'@ | docker compose exec -T timescaledb psql -U evolver -d evolver -v ON_ERROR_STOP=1 -v "event_id=$eventId"
```

A [matriz de aceite](../docs/spec-store-and-forward.md#aceite) descreve os
cenários de reinício, perda de ACK, troca de alocação e capacidade.

## Aplicação

O simulador consulta os vials ativos via MQTT e publica OD, pH e temperatura simulados.
A ingestão grava os três tipos; a API e o frontend são processos locais.

Cada projeto Python tem seu próprio pacote no workspace `uv` da raiz. O comando do
simulador e a ingestão funcionam após iniciar o Compose independente em `mqtt/` e
o banco. Consulte as [instruções de uso](../README.md#iniciar-e-usar):

```bash
uv run --env-file backend/.env --package evolver-cnpem-backend python -m evolver.ingestion
uv run --package evolver-cnpem-backend uvicorn evolver.api.main:app --reload
uv run --env-file simulator/.env --package evolver-cnpem-simulator python -m evolver_simulator
```

```bash
cd frontend
npm ci
npm run dev
```

O futuro `compose.full.yaml` será preparado somente depois que existirem Dockerfiles
e pontos de entrada reais. O Mosquitto continuará com ciclo de vida independente em
`mqtt/`. Não há modo de pilha completa validado nesta etapa.
