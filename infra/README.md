# Infraestrutura local

Este diretório contém a infraestrutura local da E2-T03 e a configuração MQTT da E2-T05:

- `mosquitto/mosquitto.conf`: broker local para transporte MQTT;
- `mosquitto/acl`: permissões por tópico de cada cliente;
- `mosquitto/docker-entrypoint.sh`: gera o arquivo de senhas a partir do `.env`;
- `mosquitto/smoke-test.sh`: verificação de autenticação, ACLs e retenção;
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

A porta publicada fica vinculada a `127.0.0.1` e o broker recusa conexões anônimas.
Essa configuração é apenas para desenvolvimento local; TLS fica para uma implantação
remota (#12).

## Identidades e permissões

Cada processo usa o próprio usuário, com senha definida no `.env`. Ao iniciar, o
`mosquitto/docker-entrypoint.sh` gera o arquivo de senhas dentro do contêiner; ele
não é versionado. As permissões estão em `mosquitto/acl` e seguem os tópicos do
[contrato](../backend/src/evolver/contracts/README.md):

| Usuário | Publica | Assina |
| --- | --- | --- |
| `evolver-sim-01` | `evolver/v1/evolver-sim-01/telemetry`, `.../command-results` | `.../telemetry/ack`, `.../telemetry/rejection`, `.../commands` do próprio equipamento |
| `evolver-ingestion` | `evolver/v1/+/telemetry/ack`, `evolver/v1/+/telemetry/rejection` | `evolver/v1/+/telemetry`, `evolver/v1/+/command-results` |
| `evolver-api` | `evolver/v1/+/commands` | nada |
| `evolver-health` | `evolver/health` | nada |

O usuário do simulador é o `equipment_id`, para que um simulador não publique nem
leia tópicos de outro equipamento. Um novo equipamento exige um bloco em
`mosquitto/acl`, uma linha em `docker-entrypoint.sh` e uma senha no `.env`. Tudo o
que não está na ACL é negado.

Comandos nunca são retidos: o broker tem `retain_available false`. O prazo de
validade continua no campo `expires_at` do payload, verificado pelo simulador; o
broker não descarta comandos por prazo.

## Verificar o broker

Com o Compose no ar:

```bash
docker compose exec mosquitto sh /mosquitto/config/smoke-test.sh
```

O script usa `mosquitto_pub`/`mosquitto_sub` para conferir os cinco fluxos do
contrato, as permissões negadas, a recusa de cliente anônimo e de senha errada e que
uma mensagem retida não é entregue. Para testar queda e retorno, execute
`docker compose restart mosquitto`, espere o estado `healthy` e rode o script de novo.

Os clientes do piloto devem usar MQTT 5. O broker limita o QoS a 1 e desabilita
mensagens retidas, de acordo com os contratos atuais. O PUBACK do MQTT confirma
somente transporte; não confirma commit no PostgreSQL.

O script do banco habilita apenas a extensão TimescaleDB. Ele não cria tabelas,
hypertables, índices ou dados de aplicação; essas mudanças pertencem à task de
modelagem e migrações (#9).
