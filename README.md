# eVOLVER-CNPEM
Repositório do projeto de monitoramento de células eVOLVER. Parceria PUCC e CNPEM

Agentes de IA que trabalham neste repositório devem ler [AGENTS.md](AGENTS.md).

## Contratos MQTT do piloto

O contrato versionado do piloto simulado — tópicos, QoS, regras de confirmação,
modelos Pydantic, schemas JSON e exemplos de mensagens — está em
[packages/contracts/src/evolver_contracts/README.md](packages/contracts/src/evolver_contracts/README.md).
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

Com Python 3.12 e `uv` instalados, na raiz do repositório:

```bash
uv sync --all-packages --group dev --frozen
uv run --all-packages ruff check backend/src simulator/src packages/contracts/src packages/contracts/tests
uv run --all-packages pytest packages/contracts/tests
```

Os modelos Pydantic continuam sendo a fonte de verdade. A infraestrutura não muda
schemas, exemplos ou semântica das mensagens MQTT.

## Estrutura preparada

```text
pyproject.toml            workspace Python uv
uv.lock                   lock compartilhado dos projetos Python
packages/contracts/       modelos Pydantic, schemas e testes MQTT existentes
backend/                  pacote Python para API, ingestão e banco
  migrations/             reservado para Alembic
  src/evolver/api/        reservado para FastAPI e SSE
  src/evolver/db/         reservado para SQLAlchemy e Alembic
  src/evolver/ingestion/  reservado para o processo de ingestão
simulator/                projeto Python independente, ainda sem ponto de entrada
  src/evolver_simulator/  reservado para o processo externo
frontend/                 reservado para Vue 3 + Vite
  src/                    reservado para componentes Vue
  tests/                  reservado para testes da interface
infra/                    configuração do broker e inicialização da extensão
operations/               comandos de operação e diagnóstico
compose.yaml              Mosquitto + PostgreSQL/TimescaleDB
```

O navegador acessará apenas a API. Simulador e backend são projetos Python
distintos que compartilham apenas `evolver_contracts`. API e ingestão serão
processos separados do backend; o simulador terá processo próprio quando for
implementado. Ele não importará `evolver.db` nem `evolver.api`.

## Limites do piloto

O ambiente é local e usa dados simulados. Ele não comprova integração com hardware,
precisão científica nem execução física de comandos. MQTT transporta mensagens;
uma confirmação de transporte não equivale ao commit no banco. Comandos MQTT não
são retidos.

O modo Compose completo será preparado apenas quando os serviços da aplicação e o
frontend tiverem pontos de entrada e imagens reais. Esta etapa não afirma que a
pilha completa já funciona.
