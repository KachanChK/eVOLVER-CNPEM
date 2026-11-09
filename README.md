# eVOLVER CNPEM

Esta versão permite testar o caminho de uma leitura de temperatura:

```text
Simulador Python → Mosquitto (MQTT) → ingestão Python → PostgreSQL + TimescaleDB
```

Cada execução do simulador envia **37 °C** para um frasco (`vial`). O Mosquitto e o
banco rodam no Docker Desktop. A ingestão e o simulador rodam em terminais no Windows.
Ainda não há interface web funcional.

## 1. Preparar o projeto

Você precisa de **Docker Desktop em execução**, **PowerShell** e **uv**. Abra o
PowerShell na pasta que contém este README. Todos os comandos abaixo partem dessa
pasta, a raiz do repositório.

Crie os arquivos de configuração local. Os comandos preservam arquivos que você já
tenha criado:

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
if (!(Test-Path mqtt/.env)) { Copy-Item mqtt/.env.example mqtt/.env }
if (!(Test-Path backend/.env)) { Copy-Item backend/.env.example backend/.env }
if (!(Test-Path simulator/.env)) { Copy-Item simulator/.env.example simulator/.env }
uv sync --all-packages --group dev --frozen
```

Os exemplos usam `127.0.0.1`, PostgreSQL na porta `5432` e MQTT na `1883`. Se você
mudou senhas ou portas nos seus arquivos `.env`, mantenha os valores correspondentes
em `backend/.env` e `simulator/.env`.

## 2. Iniciar o banco e o MQTT

```powershell
docker compose up -d --wait
docker compose --env-file mqtt/.env -f mqtt/compose.yaml up -d --wait
```

Espere os dois comandos terminarem com os serviços saudáveis (`healthy`). Eles criam
dois projetos separados no Docker Desktop: `evolver-cnpem` e `evolver-mqtt`.

## 3. Criar as tabelas

```powershell
uv run --env-file backend/.env --package evolver-cnpem-backend alembic -c backend/alembic.ini upgrade head
```

Isso cria `vials` e `temperature_readings`. Se executar novamente em um banco já
atualizado, o Alembic não recria as tabelas nem apaga as leituras. **Se aparecer um
erro dizendo que uma tabela antiga contém dados, pare aqui:** a migração se recusa a
apagá-los. Consulte [migrações do banco](backend/migrations/README.md).

## 4. Cadastrar um frasco de teste

Veja primeiro se já existe um frasco para o simulador:

```powershell
docker compose exec timescaledb psql -U evolver -d evolver -c "SELECT vial_id, equipment_id, label FROM vials;"
```

Se não houver um frasco com `equipment_id` igual a `evolver-sim-01`, cadastre um:

```powershell
docker compose exec timescaledb psql -U evolver -d evolver -c "INSERT INTO vials (equipment_id, label, created_at) VALUES ('evolver-sim-01', 'Frasco de teste', now()) RETURNING vial_id;"
```

Anote o `vial_id` existente ou retornado pelo cadastro. Abra `simulator/.env` e defina
`VIAL_ID` com esse número. Em um banco novo, ele normalmente será `1`.

## 5. Receber e enviar a temperatura

Abra um **primeiro PowerShell** na raiz do repositório e inicie a ingestão:

```powershell
uv run --env-file backend/.env --package evolver-cnpem-backend python -m evolver.ingestion
```

Deixe esse terminal aberto. Ele deve mostrar `Ingestão MQTT pronta para temperaturas.`

Abra um **segundo PowerShell**, também na raiz, e execute o simulador:

```powershell
uv run --env-file simulator/.env --package evolver-cnpem-simulator python -m evolver_simulator
```

O simulador deve mostrar `PUBACK recebido`; o primeiro terminal deve mostrar
`Temperatura gravada`. Execute o simulador novamente para gerar outra leitura. Cada
execução envia uma mensagem e encerra. O PUBACK confirma a entrega ao Mosquitto;
confirme a gravação no terminal da ingestão ou no banco.

## 6. Visualizar o banco no DBeaver

No DBeaver, selecione **Nova conexão → PostgreSQL** e preencha:

| Campo | Valor dos arquivos de exemplo |
| --- | --- |
| Host | `127.0.0.1` |
| Porta | `5432` |
| Banco de dados | `evolver` |
| Usuário | `evolver` |
| Senha | `evolver-local-only` |

Clique em **Testar conexão** e depois em **Concluir**. Se o DBeaver pedir o driver
PostgreSQL, permita a instalação. O TimescaleDB é uma extensão do PostgreSQL e usa
essa mesma conexão.

No navegador do DBeaver, abra **evolver → Schemas → public → Tables**. Clique em
`temperature_readings` e escolha **Visualizar dados**. A coluna `vial_id` liga cada
leitura à tabela `vials`. Você também pode executar esta consulta em um editor SQL:

```sql
SELECT v.vial_id, v.label, t.temperature_celsius,
       t.generated_at, t.received_at
FROM temperature_readings AS t
JOIN vials AS v USING (vial_id)
ORDER BY t.generated_at DESC
LIMIT 20;
```

Se estiver usando valores diferentes nos arquivos `.env`, use no DBeaver a porta,
o banco, o usuário e a senha correspondentes. Depois de enviar outra leitura,
atualize os dados da tabela no DBeaver.

## Rodar os testes

Na raiz do repositório, rode a verificação de código e os testes que não precisam de
um banco descartável:

```powershell
uv run --frozen ruff check backend/src backend/tests simulator/src simulator/tests packages/contracts/src packages/contracts/tests
uv run --frozen pytest packages/contracts/tests simulator/tests backend/tests/db -q
```

Sem configurar os bancos de teste, **dois testes de integração são ignorados**. Eles
aplicam migrações e precisam de bancos separados do seu banco `evolver`. Para verificar
o broker MQTT, com ele em execução, rode:

```powershell
docker compose --env-file mqtt/.env -f mqtt/compose.yaml exec mosquitto sh /mosquitto/config/smoke-test.sh
```

Para rodar também os **dois testes de integração do banco**, crie uma vez dois bancos
descartáveis no contêiner (não use o banco `evolver` para isso):

```powershell
docker compose exec timescaledb createdb -U evolver evolver_temperature_test
docker compose exec timescaledb createdb -U evolver evolver_migration_guard_test
docker compose exec timescaledb psql -U evolver -d evolver_temperature_test -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"
docker compose exec timescaledb psql -U evolver -d evolver_migration_guard_test -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"
$env:EVOLVER_TEST_DATABASE_URL = "postgresql+psycopg://evolver:evolver-local-only@127.0.0.1:5432/evolver_temperature_test"
$env:EVOLVER_TEST_GUARD_DATABASE_URL = "postgresql+psycopg://evolver:evolver-local-only@127.0.0.1:5432/evolver_migration_guard_test"
uv run --frozen pytest backend/tests/db -q
```

Se a senha ou a porta do PostgreSQL forem diferentes, ajuste as duas URLs. Os nomes
dos bancos são exclusivos para teste; não repita `createdb` se eles já existirem.
Para remover **somente esses dois bancos de teste** ao terminar:

```powershell
docker compose exec timescaledb dropdb -U evolver evolver_temperature_test
docker compose exec timescaledb dropdb -U evolver evolver_migration_guard_test
Remove-Item Env:EVOLVER_TEST_DATABASE_URL
Remove-Item Env:EVOLVER_TEST_GUARD_DATABASE_URL
```

## Parar e voltar depois

Interrompa a ingestão com `Ctrl+C`. Para parar os contêineres sem apagar os dados:

```powershell
docker compose stop
docker compose --env-file mqtt/.env -f mqtt/compose.yaml stop
```

Você também pode iniciar esses dois contêineres pelo Docker Desktop depois da
primeira configuração. Para fazer outro teste, inicie **também a ingestão no terminal**
antes de executar o simulador. Não use `docker compose down -v` se quiser preservar
as leituras: `-v` remove o volume do banco.

Esta etapa ainda não tem fila de reenvio, confirmação de gravação ao simulador, envio
contínuo, OD, pH ou dados das bombas. Os documentos em `docs/` descrevem o piloto
planejado além do que já funciona.

Agentes de IA devem ler [AGENTS.md](AGENTS.md) antes de alterar o repositório.
