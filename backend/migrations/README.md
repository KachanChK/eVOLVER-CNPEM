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
transação, mesmo quando duas linhas teriam o mesmo `event_id`.

## Esquema e consultas

- `evolver.db.models`: mappings SQLAlchemy e metadados consumidos pelo Alembic.
- `evolver.db.queries.get_current_measurements`: lê a view `latest_measurements`,
  agrupada por equipamento, posição e tipo. Ela ordena por horário de produção,
  sequência e horário de recebimento; uma leitura atrasada permanece no histórico,
  mas não substitui a atual.
- `evolver.db.queries.get_measurement_history`: consulta por equipamento, posição,
  tipo e intervalo de `generated_at`, com limite de linhas.

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
