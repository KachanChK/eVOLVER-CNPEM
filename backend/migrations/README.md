# Migrações do banco

As migrações Alembic versionam o schema PostgreSQL + TimescaleDB. A revisão
`20261027_01` cria equipamentos, posições, culturas, execuções, IDs processados,
medições hypertable, comandos, auditoria e a view `latest_measurements`.

## Aplicar em um banco novo

1. Inicie o serviço local seguindo [operações](../../operations/README.md) e
   aguarde o healthcheck do TimescaleDB.
2. Na pasta `backend`, instale as dependências e aplique as migrações:

```powershell
uv sync --group dev --frozen
uv run alembic upgrade head
```

Alembic lê `DATABASE_URL`. Sem essa variável, usa os mesmos padrões locais do
Compose (`evolver` / `evolver-local-only`, `127.0.0.1:5432`). Para outra
configuração, defina `DATABASE_URL` como `postgresql+psycopg://...` antes do
comando. O script `infra/db/init/001-enable-timescaledb.sql` habilita a extensão
somente na criação inicial do volume; Alembic cria e atualiza o schema da aplicação.

## Escrita e idempotência

A ingestão grava `processed_event_ids` e `measurements` na mesma transação. Primeiro
insere `event_id` na tabela de IDs processados; se a chave já existir, reconhece a
reentrega como duplicata. Em seguida grava a medição com `generated_at` recebido do
produtor e `received_at` atribuído pela ingestão. Só publica ACK depois do commit.
Não derive `generated_at` de `received_at`.

`measurements` é hypertable particionada por `generated_at`. A tabela de IDs
processados é uma tabela PostgreSQL normal porque `event_id` precisa ser único
globalmente; TimescaleDB exige que constraints únicas de hypertables incluam a coluna
de particionamento. A unicidade lógica é garantida pelo ledger global e pela
transação. A FK composta entre ledger e hypertable também garante que `generated_at`
seja o mesmo nas duas linhas.

Eventos em quarentena também ocupam `event_id` no ledger para que uma reentrega seja
reconhecida. Nos registros que não puderam ser validados, equipamento, produtor e
horário de produção podem ficar nulos; eventos persistidos exigem esses três campos.

## Esquema e consultas

- `evolver.db.models`: mappings SQLAlchemy e metadados consumidos pelo Alembic.
- `evolver.db.queries.get_current_measurements`: lê a view `latest_measurements`,
  agrupada por equipamento, posição e tipo. Ela ordena por horário de produção,
  sequência e horário de recebimento; uma leitura atrasada permanece no histórico,
  mas não substitui a atual.
- `evolver.db.queries.get_measurement_history`: consulta por equipamento, posição,
  tipo e intervalo de `generated_at`, com limite de linhas.

A view consulta cada posição e tipo suportado com `LATERAL ... ORDER BY ... LIMIT 1`,
aproveitando o índice composto da hypertable. Assim, a leitura atual evita ordenar e
agrupar todos os chunks a cada chamada.

Exemplo de inserção de uma série simulada em uma sessão SQLAlchemy:

```python
import os
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from evolver.db.models import Equipment, Measurement, Position, ProcessedEvent

Session = sessionmaker(create_engine(os.environ["DATABASE_URL"]))
now = datetime.now(UTC)
position_id = uuid4()
event_id = uuid4()
with Session.begin() as session:
    session.add(Equipment(id="sim-01", created_at=now))
    session.add(Position(
        id=position_id, equipment_id="sim-01", position_code="A1",
        vial_id="vial-01", created_at=now,
    ))
    session.add(ProcessedEvent(
        event_id=event_id, equipment_id="sim-01", producer_id="sim-01",
        generated_at=now, received_at=now,
    ))
    session.add(Measurement(
        event_id=event_id, generated_at=now, received_at=now,
        equipment_id="sim-01", position_id=position_id, producer_id="sim-01",
        sequence=1, measurement_type="od", value=0.25, schema_version="1.0",
    ))
```

Configure a URL com `DATABASE_URL` em aplicações reais, sem gravar senha no código.
A sessão única torna o ledger e a medição atômicos.

## Versões e reversão

```powershell
uv run alembic current
uv run alembic history
uv run alembic downgrade -1
```

`downgrade -1` remove o schema desta revisão, incluindo os dados; faça backup antes.
Para subir de novo, execute `uv run alembic upgrade head`.

## Teste de integração

Os testes de banco precisam de um database descartável com TimescaleDB habilitado;
não aponte-os para o banco local `evolver`, pois o teste aplica a migration. Crie-o
no serviço Compose:

```powershell
docker compose exec timescaledb createdb -U evolver evolver_test
docker compose exec timescaledb psql -U evolver -d evolver_test -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"
```

Na pasta `backend`, configure a URL e rode o teste de integração:

```powershell
$env:EVOLVER_TEST_DATABASE_URL = "postgresql+psycopg://evolver:evolver-local-only@127.0.0.1:5432/evolver_test"
uv run pytest tests/db -m integration
```

Sem `EVOLVER_TEST_DATABASE_URL`, o teste é ignorado. Apague o database de teste quando
terminar, se não precisar dele:

```powershell
docker compose exec timescaledb dropdb -U evolver evolver_test
```
