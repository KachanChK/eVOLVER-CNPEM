# Infraestrutura local

Este diretório contém somente a infraestrutura necessária para a E2-T03:

- `mosquitto/mosquitto.conf`: broker local para transporte MQTT;
- `db/init/001-enable-timescaledb.sql`: habilitação da extensão TimescaleDB em um
  banco novo.

As imagens estão fixadas em `compose.yaml`:

- `eclipse-mosquitto:2.0.22`;
- `timescale/timescaledb:2.31.0-pg17`.

As tags foram conferidas nas páginas oficiais do
[Eclipse Mosquitto](https://hub.docker.com/_/eclipse-mosquitto/tags) e do
[TimescaleDB](https://hub.docker.com/r/timescale/timescaledb/tags) no Docker Hub.
Atualizar uma imagem exige revisar compatibilidade, executar as verificações
operacionais e registrar a alteração junto ao projeto.

## Limites desta configuração

O broker aceita conexões anônimas porque a porta publicada fica vinculada a
`127.0.0.1`. Essa configuração é apenas para desenvolvimento local. Identidades,
senhas e ACLs por tópico pertencem à issue de configuração MQTT (#5).

Os clientes do piloto devem usar MQTT 5. O broker limita o QoS a 1 e desabilita
mensagens retidas, de acordo com os contratos atuais. O PUBACK do MQTT confirma
somente transporte; não confirma commit no PostgreSQL.

O script do banco habilita apenas a extensão TimescaleDB. Ele não cria tabelas,
hypertables, índices ou dados de aplicação; essas mudanças pertencem à task de
modelagem e migrações (#9).
