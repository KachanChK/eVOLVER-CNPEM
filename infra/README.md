# Infraestrutura local

Este diretório contém a infraestrutura local da E2-T03. O serviço MQTT independente
e suas instruções estão em [`../mqtt/`](../mqtt/README.md).

- `db/init/001-enable-timescaledb.sql`: habilitação da extensão TimescaleDB em um
  banco novo. O schema da aplicação é aplicado separadamente com Alembic; consulte
  `backend/migrations/README.md`.

As imagens estão fixadas nos respectivos arquivos Compose:

- `eclipse-mosquitto:2.0.22` em `mqtt/compose.yaml`;
- `timescale/timescaledb:2.31.0-pg17` em `compose.yaml`.

As tags foram conferidas nas páginas oficiais do
[Eclipse Mosquitto](https://hub.docker.com/_/eclipse-mosquitto/tags) e do
[TimescaleDB](https://hub.docker.com/r/timescale/timescaledb/tags) no Docker Hub.
Atualizar uma imagem exige revisar compatibilidade, executar as verificações
operacionais e registrar a alteração junto ao projeto.

O script inicial habilita somente a extensão TimescaleDB. Migrations Alembic criam
o schema da aplicação depois que o serviço está saudável.
