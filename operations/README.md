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
docker compose exec mosquitto sh -c 'mosquitto_pub -V mqttv5 -h 127.0.0.1 -p 1883 -u evolver-health -P "$MQTT_HEALTH_PASSWORD" -t evolver/health -m diagnostic -q 1'
```

O sucesso confirma que o broker aceitou uma publicação MQTT 5 autenticada, QoS 1 e
não retida. Não confirma persistência no banco nem processamento por uma aplicação.
Para conferir autenticação e ACLs por tópico:

```bash
docker compose exec mosquitto sh /mosquitto/config/smoke-test.sh
```

Se o Mosquitto não iniciar após atualizar o repositório, confira se o `.env` tem as
variáveis `MQTT_*_PASSWORD` de `.env.example`.

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
