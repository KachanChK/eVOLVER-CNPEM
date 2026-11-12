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

O broker deve aparecer como `healthy`. O teste completo com o simulador está em
[`docs/plano-mqtt-independente.md`](../docs/plano-mqtt-independente.md).

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

## Aplicação

O simulador publica OD, pH e temperatura simulados. A ingestão atual recebe e grava
somente temperatura; API e frontend ainda não existem como serviços executáveis.

Cada projeto Python tem seu próprio pacote no workspace `uv` da raiz. O comando do
simulador e a ingestão funcionam após iniciar o Compose independente em `mqtt/` e
o banco. Consulte o [teste completo](../README.md#7-receber-e-enviar-a-temperatura):

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
