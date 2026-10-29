# eVOLVER-CNPEM
Repositório do projeto de monitoramento de células eVOLVER. Parceria PUCC e CNPEM

Agentes de IA que trabalham neste repositório devem ler [AGENTS.md](AGENTS.md).

## Contratos MQTT do piloto

O contrato versionado do piloto simulado — tópicos, QoS, regras de confirmação,
modelos Pydantic, schemas JSON e exemplos de mensagens — está em
[backend/src/evolver/contracts/README.md](backend/src/evolver/contracts/README.md).
Simulador, ingestão e API usam os mesmos modelos antes da implementação dos
serviços.

## Estado atual

A E2-T03 prepara somente a infraestrutura local e a organização do monorepo. Neste
momento, `compose.yaml` inicia:

| Serviço | Imagem fixada | Porta local | Persistência |
| --- | --- | --- | --- |
| Mosquitto | `eclipse-mosquitto:2.0.22` | `127.0.0.1:1883` | volume `mosquitto_data` |
| PostgreSQL + TimescaleDB | `timescale/timescaledb:2.31.0-pg17` | `127.0.0.1:5432` | volume `postgres_data` |

Simulador, ingestão, API e frontend ainda não são executáveis. Seus diretórios
registram apenas responsabilidades e fronteiras para as tasks seguintes.

## Início rápido da infraestrutura

Pré-requisito: Docker Desktop com Docker Compose v2.

No PowerShell:

```powershell
Copy-Item .env.example .env
docker compose config --quiet
docker compose up -d
docker compose ps
```

Em Bash:

```bash
cp .env.example .env
docker compose config --quiet
docker compose up -d
docker compose ps
```

Os serviços devem aparecer como `healthy`. Diagnóstico, logs e parada estão em
[operations/README.md](operations/README.md).

## Verificar os contratos existentes

Com Python 3.12 e `uv` instalados:

```bash
cd backend
uv sync --group dev --frozen
uv run ruff check src tests
uv run pytest tests/contracts
```

Os modelos Pydantic continuam sendo a fonte de verdade. A infraestrutura não muda
schemas, exemplos ou semântica das mensagens MQTT.

## Estrutura preparada

```text
backend/                  pacote Python e contratos existentes
  migrations/             reservado para Alembic
  src/evolver/api/        reservado para FastAPI e SSE
  src/evolver/db/         reservado para SQLAlchemy e Alembic
  src/evolver/ingestion/  reservado para o processo de ingestão
  src/evolver/simulator/  reservado para o simulador externo
frontend/                 reservado para Vue 3 + Vite
  src/                    reservado para componentes Vue
  tests/                  reservado para testes da interface
infra/                    configuração do broker e inicialização da extensão
operations/               comandos de operação e diagnóstico
compose.yaml              Mosquitto + PostgreSQL/TimescaleDB
```

O navegador acessará apenas a API. O simulador, a ingestão e a API serão processos
Python separados no mesmo pacote; o simulador não importará `db/` nem `api/`.

## Limites do piloto

O ambiente é local e usa dados simulados. Ele não comprova integração com hardware,
precisão científica nem execução física de comandos. MQTT transporta mensagens;
uma confirmação de transporte não equivale ao commit no banco. Comandos MQTT não
são retidos.

O modo Compose completo será preparado apenas quando os serviços da aplicação e o
frontend tiverem pontos de entrada e imagens reais. Esta etapa não afirma que a
pilha completa já funciona.
