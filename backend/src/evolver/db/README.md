# Banco de dados

`models.py` contém os mappings SQLAlchemy do schema. As revisões Alembic em
`backend/migrations/` são a fonte de criação e evolução do banco; não use
`Base.metadata.create_all()` em produção ou nos ambientes do projeto.

`connection.py` monta a URL do banco a partir de `DATABASE_URL` ou das variáveis
`POSTGRES_*`, para Alembic, ingestão e scripts. `seed.py` cadastra o equipamento
simulado `evolver-sim-01` e seus vials até existir o cadastro de metadados (E3 · T10):
`uv run --env-file .env --package evolver-cnpem-backend python -m evolver.db.seed`.
Cada `--vial` novo ocupa o primeiro código livre (`P01`, `P02`, ...); códigos de
posições desabilitadas continuam reservados. Vials já cadastrados são mantidos, e
um vial habilitado em outro equipamento é informado como conflito (código de saída 1).

## Entidades

- `equipment` e `positions`: equipamento e posições/viais lógicos do piloto. Um vial
  fica associado a no máximo uma posição habilitada; desabilite o vínculo anterior
  para registrar sua transferência.
- `cultures` e `experiment_runs`: metadados biológicos opcionais e execuções. Um vial
  pode receber novos registros de cultura, que são associados à execução pelo
  `culture_id`.
- `processed_event_ids`: ledger PostgreSQL de idempotência, com chave global
  `event_id` e o primeiro recebimento. Campos ausentes em mensagens rejeitadas podem
  ficar nulos para que a quarentena preserve a chave de deduplicação.
- `measurements`: série temporal em hypertable, contendo `generated_at` e
  `received_at`, sequência, tipo, valor e referências aos metadados.
- `commands`: solicitação, autor, alvo, payload, prazo, estado e resultado simulado.
- `audit_events`: trilha append-only para alterações e ações correlacionadas.

Medições suportadas no contrato atual: `od`, `ph` e `temperature`. A unidade e a
calibração não são inferidas pelo schema do piloto.

## Leitura

Use `get_current_measurements(session, equipment_id=..., position_id=...,
measurement_type=...)` para o estado atual de cada fonte e tipo. A view faz uma busca
indexada por posição e tipo, seleciona o maior `generated_at` e usa `sequence` como
desempate. `received_at` não determina a atualidade, então uma mensagem antiga entregue
com atraso não faz a leitura atual regredir.

Use `get_measurement_history(session, ..., since=..., until=..., limit=...)` para
histórico ordenado pelo horário de produção. `since` é inclusivo e `until` é
exclusivo. Os dois horários persistidos permitem medir atraso sem reescrever a
ordem de produção.

## Persistência local

O Compose grava PostgreSQL + TimescaleDB no volume nomeado `postgres_data` (o nome
Docker completo leva o prefixo do projeto Compose). `docker compose down` preserva
esse volume. `docker compose down -v` o remove e apaga o banco. Persistência em volume
protege contra a recriação de containers, mas não substitui backup.

Consulte [migrações](../../../migrations/README.md) para criar schema, gravar eventos
em transação e rodar consultas. Consulte [operações](../../../../operations/README.md)
para os comandos de backup e restauração.
