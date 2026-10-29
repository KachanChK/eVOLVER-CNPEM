# Operação do ambiente local

Execute os comandos na raiz do repositório. O Docker Desktop com Compose v2 é
pré-requisito. Copie `.env.example` para `.env` antes da primeira execução; os
valores fornecidos são exclusivos para desenvolvimento local. Os comandos abaixo
estão em uma linha para funcionar tanto no PowerShell quanto em Bash.

## Validar a configuração

```bash
docker compose config --quiet
```

Esse comando valida a interpolação e a estrutura do Compose sem iniciar serviços.

## Iniciar e observar

```bash
docker compose up -d
docker compose ps
docker compose logs --tail=100 mosquitto timescaledb
```

Espere ambos os serviços aparecerem como `healthy` antes de continuar.

## Diagnóstico do Mosquitto

```bash
docker compose exec mosquitto mosquitto_pub -V mqttv5 -h 127.0.0.1 -p 1883 -t evolver/health -m diagnostic -q 1
```

O sucesso confirma que o broker aceitou uma publicação MQTT 5, QoS 1 e não retida.
Não confirma persistência no banco nem processamento por uma aplicação.

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

Simulador, ingestão, API e frontend ainda não existem como serviços executáveis.
Quando forem implementados pelas tasks correspondentes, o desenvolvimento diário
usará a infraestrutura em Compose e o código Python/Vue executado na máquina.

Os comandos previstos abaixo são apenas referência e ainda não funcionam porque os
pontos de entrada e o projeto Vue não foram implementados. Cada projeto Python tem
seu próprio pacote no workspace `uv` da raiz:

```bash
uv run --package evolver-cnpem-backend python -m evolver.ingestion
uv run --package evolver-cnpem-backend uvicorn evolver.api.main:app --reload
uv run --package evolver-cnpem-simulator python -m evolver_simulator
```

```bash
cd frontend
npm ci
npm run dev
```

O futuro `compose.full.yaml` será um segundo arquivo, aplicado junto a
`compose.yaml`, somente depois que existirem Dockerfiles e pontos de entrada reais.
Não há modo de pilha completa validado nesta etapa.
