# E1 · T03 — Stack e modo de desenvolvimento local

**Etapa:** 1 — Planejamento  
**Prioridade:** P0  
**Período:** 26–28/10/2026  
**Dependências:** E1 · T01 (#1); complementa E1 · T02 (arquitetura externa e fluxos)  
**Issue:** [#18](https://github.com/KachanChK/eVOLVER-CNPEM/issues/18)  
**Status:** proposta para revisão  
**Fronteira:** piloto local de 27/11/2026, em uma única máquina, com simulador externo e comandos sem efeito físico.

## Objetivo

Fixar as escolhas mínimas de tecnologia, versões iniciais, ferramentas de migração e teste, estrutura do repositório e forma de execução local. As escolhas servem à arquitetura do T02 e não alteram seus contratos: telemetria e comandos via MQTT, persistência central no PostgreSQL + TimescaleDB e acesso do navegador somente pela API.

## Stack confirmada

| Camada | Escolha | Motivo | Papel no piloto |
| --- | --- | --- | --- |
| Transporte | **Eclipse Mosquitto (MQTT 5)** | Confirmado no T02; broker leve, fácil de rodar em contêiner e com persistência opcional. | Telemetria, ACK de aplicação, comandos e respostas entre simulador e serviços. |
| Banco | **PostgreSQL + TimescaleDB** | Confirmado no T02; relacional para metadados e auditoria, hypertables para séries temporais no mesmo banco. | Fonte única do histórico persistido, deduplicação por `event_id`. |
| Backend | **Python** | Confirmado no T02; mesma linguagem para simulador, ingestão e API. | Simulador, ingestão e API. |
| API | **FastAPI** | Tipagem com Pydantic (mesmos modelos validam MQTT e HTTP), OpenAPI gerado automaticamente, suporte assíncrono e SSE simples. | Consultas, comandos autorizados e atualizações ao vivo. |
| Cliente MQTT | **paho-mqtt 2.x** (via `aiomqtt` nos serviços assíncronos) | Cliente de referência da Eclipse, suporta MQTT 5; `aiomqtt` o envolve para uso com `asyncio` no FastAPI e na ingestão. | Publicar/assinar tópicos em simulador, ingestão e API. |
| Interface | **Vue 3 + Vite** | Curva de aprendizado curta, componentes de arquivo único, build rápido e servidor de desenvolvimento com recarga a quente. | Painéis, histórico, estado de conexão e operações simuladas. |
| Gráficos | **Chart.js 4** (com `vue-chartjs`) | Suficiente para séries de OD, pH e temperatura; leve e bem documentado. | Gráficos atuais e históricos. |

Nenhum impedimento foi identificado para as escolhas sugeridas na issue; todas foram adotadas.

### Escolhas complementares

| Tema | Escolha | Motivo |
| --- | --- | --- |
| Acesso ao banco | **SQLAlchemy 2** + driver **psycopg 3** | ORM/Core maduro, compatível com async e com SQL explícito quando a consulta temporal exigir. |
| Migrações | **Alembic** | Padrão do SQLAlchemy; migrações versionadas no repositório. Hypertables e índices do TimescaleDB entram como SQL dentro das migrações (`op.execute`). |
| Atualização ao vivo | **SSE (Server-Sent Events)** | Fluxo unidirecional servidor → navegador basta: comandos seguem por HTTP. Reconexão nativa no navegador (`EventSource`); após reconectar, a interface recarrega o estado pela API. Atualizações são enviadas **depois** da gravação no banco; atrasos de alguns segundos são aceitáveis. |
| Aviso ingestão → API | **PostgreSQL `LISTEN/NOTIFY`** | A ingestão emite `NOTIFY` dentro da transação que grava o evento; o PostgreSQL só entrega a notificação após o commit. A notificação leva apenas identificadores; a API lê o dado no banco antes de enviá-lo pelo SSE. Notificações emitidas enquanto a API estiver desconectada se perdem, então, ao (re)conectar, a API recarrega o estado pelo banco. Consultar o banco periodicamente é a alternativa, se `LISTEN/NOTIFY` se mostrar inadequado. |
| Unicidade de eventos | **Tabela de IDs processados** (tabela comum, não hypertable), com `event_id` como chave primária | Em hypertables, índices únicos precisam incluir a coluna de particionamento (tempo), então `event_id` sozinho não pode ser único na tabela de medições. A ingestão grava o `event_id` nessa tabela e a medição **na mesma transação**; conflito na chave identifica a duplicata. |
| Fila do Store and Forward | **SQLite** (arquivo local do simulador) | Durável, transacional, sem serviço extra; sobrevive a reinício do processo. |
| Servidor ASGI | **Uvicorn** | Padrão para FastAPI. |
| Configuração | Variáveis de ambiente + arquivo `.env` (lido por `pydantic-settings`); `.env.example` versionado | Mesma configuração serve aos dois modos de execução. |
| Gerenciador Python | **uv** | Instalação rápida, `pyproject.toml` + `uv.lock` reprodutível. |
| Gerenciador JS | **npm** + `package-lock.json` | Vem com o Node; sem ferramenta extra. |
| Testes Python | **pytest** + `pytest-asyncio` | Testes unitários e de integração (com banco e broker reais do Compose). |
| Testes da interface | **Vitest** + Vue Test Utils | Integrado ao Vite. |
| Qualidade | **Ruff** (lint/format Python), **ESLint** + **Prettier** (frontend) | Configuração mínima, rápida. |

## Versões iniciais

Faixas-alvo para iniciar o projeto. As versões exatas ficam fixadas nos arquivos de lock (`uv.lock`, `package-lock.json`) e nas tags das imagens do `compose.yaml` no momento em que o esqueleto do código for criado; atualizações posteriores são feitas por PR.

| Componente | Versão inicial |
| --- | --- |
| Python | 3.12 |
| FastAPI | 0.115 ou superior (0.x) |
| Pydantic / pydantic-settings | 2.x |
| SQLAlchemy | 2.0.x |
| Alembic | 1.x |
| psycopg | 3.x |
| paho-mqtt / aiomqtt | 2.x / 2.x |
| Uvicorn | 0.3x |
| pytest | 8.x |
| PostgreSQL | 17 |
| TimescaleDB | 2.x compatível com PG 17 (imagem `timescale/timescaledb:<2.x>-pg17`, tag fixa) |
| Eclipse Mosquitto | 2.0.x (imagem `eclipse-mosquitto:2.0.x`) |
| Node.js | 22 LTS, **22.12 ou superior** (mínimo do Vite atual nessa linha); versão validada registrada em `.nvmrc` e em `engines` do `package.json` |
| Vue | 3.5.x |
| Vite | versão estável atual, fixada no lock |
| Chart.js / vue-chartjs | 4.x / 5.x |
| Docker Engine / Compose | Docker Desktop recente com Compose v2 (`docker compose`) |

Critério de compatibilidade: o TimescaleDB deve suportar a versão do PostgreSQL da imagem; Python 3.12 deve ser suportado por todas as bibliotecas; Node na linha LTS em uso e no mínimo exigido pela versão do Vite fixada no lock.

## Estrutura do repositório

Monorepo, com um diretório por componente do T02:

```text
eVOLVER-CNPEM/
├── docs/                    # documentos de planejamento (E1-T01, E1-T02, E1-T03...)
├── backend/                 # pacote Python único (pyproject.toml, uv.lock)
│   ├── src/evolver/
│   │   ├── contracts/       # modelos Pydantic das mensagens MQTT (versionados)
│   │   ├── db/              # modelos SQLAlchemy e sessão
│   │   ├── ingestion/       # serviço de ingestão (assina MQTT, grava, emite ACK)
│   │   ├── api/             # app FastAPI (consultas, comandos, SSE)
│   │   └── simulator/       # simulador externo + fila SQLite
│   ├── migrations/          # Alembic
│   └── tests/
├── frontend/                # Vue 3 + Vite (package.json, package-lock.json)
│   ├── src/
│   └── tests/
├── infra/
│   ├── mosquitto/           # mosquitto.conf
│   └── db/                  # scripts de inicialização (extensão timescaledb)
├── compose.yaml             # dependências: mosquitto + timescaledb
├── compose.full.yaml        # serviços da aplicação (override para o modo completo)
├── .env.example
└── README.md                # como rodar
```

Simulador, ingestão e API ficam no mesmo pacote Python para compartilhar os contratos (`contracts/`), mas rodam como **processos separados**, preservando as fronteiras de falha do T02. O simulador não importa nada de `db/` nem de `api/`: ele conversa apenas por MQTT.

## Modos de desenvolvimento

Os dois modos rodam no mesmo computador e usam as mesmas variáveis de ambiente; só muda onde o código da aplicação executa.

### Modo 1 — Dependências em Compose, código local (dia a dia)

Docker roda só a infraestrutura; Python e Vue rodam direto na máquina, com recarga automática e depurador.

```bash
docker compose up -d                        # mosquitto (1883) + timescaledb (5432)
cd backend && uv sync
uv run alembic upgrade head
uv run python -m evolver.ingestion          # terminal 1
uv run uvicorn evolver.api.main:app --reload   # terminal 2 (porta 8000)
uv run python -m evolver.simulator          # terminal 3
cd frontend && npm install && npm run dev   # terminal 4 (porta 5173, proxy /api → 8000)
```

Uso: desenvolvimento, depuração e testes de integração (`uv run pytest`, que usa o banco e o broker do Compose).

**Windows nativo:** o loop padrão do `asyncio` no Windows (`ProactorEventLoop`) não oferece `add_reader`, exigido pelo `aiomqtt` e pelo psycopg assíncrono. No Windows, simulador, ingestão, API e testes precisam rodar com `SelectorEventLoop`: por exemplo, `asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)` nos pontos de entrada próprios, a configuração de loop equivalente do Uvicorn para a API e a do `pytest-asyncio` para os testes. O esqueleto da aplicação deve validar esse modo. Nos contêineres (Linux) a questão não se aplica.

### Modo 2 — Compose completo (reprodução)

Todos os componentes em contêineres, para reproduzir o piloto em outra máquina ou executar a demonstração.

```bash
docker compose -f compose.yaml -f compose.full.yaml up --build
```

Inclui um serviço de migração que roda `alembic upgrade head` antes de ingestão e API; a interface é servida já compilada (build do Vite). Uso: demonstração de 27/11, validação dos cenários do T01 e verificação de que o projeto sobe a partir de um clone limpo.

### Regras comuns

- Portas padrão: MQTT 1883, PostgreSQL 5432, API 8000, interface 5173 (dev) / 8080 (completo).
- Volumes nomeados para dados do banco, persistência do Mosquitto e fila SQLite do simulador, para testar reinício sem perder estado.
- `docker compose down -v` apaga os dados locais; usar somente quando se quiser recomeçar do zero.
- Nenhuma credencial real no repositório: `.env.example` traz apenas valores de desenvolvimento.

## Como rever a decisão sem trocar os contratos

Os contratos estáveis são: **tópicos e payloads MQTT** (versionados por `schema_version`) e **rotas/esquemas da API HTTP** (descritos no OpenAPI). Qualquer troca de tecnologia deve manter esses dois contratos; os testes de contrato verificam isso.

| Se for preciso trocar… | Impacto contido em | Contrato preservado |
| --- | --- | --- |
| FastAPI por outro framework Python | `backend/src/evolver/api/` | Rotas e esquemas JSON do OpenAPI atual. |
| Biblioteca MQTT | camada de publicação/assinatura em ingestão, API e simulador | Tópicos, QoS e payloads definidos em `contracts/`. |
| Vue/Chart.js | `frontend/` | Consome a mesma API HTTP e o mesmo fluxo SSE. |
| SSE por WebSocket | rota de atualizações da API e cliente na interface | Conteúdo dos eventos enviados ao navegador. |
| SQLite da fila por outro armazenamento | `simulator/` | `event_id`, sequência, `generated_at` e semântica de ACK pós-commit. |
| Modo de execução (ex.: serviço nativo em vez de contêiner) | arquivos de Compose e documentação | Mesmas variáveis de ambiente e portas. |

Mosquitto e PostgreSQL + TimescaleDB foram confirmados no T02; trocá-los exige revisão daquela decisão, não só desta.

Processo: registrar a mudança proposta e o motivo em uma issue, verificar contra os critérios P0 do T01 (durabilidade, idempotência, rastreabilidade, distinção de estados), atualizar este documento e as versões nos locks no mesmo PR.

## Pendências desta decisão

- Fixar as tags exatas das imagens e gerar os locks ao criar o esqueleto (próxima task de implementação).
- Confirmar que todas as máquinas da equipe rodam Docker Desktop com Compose v2 e têm Python 3.12 e Node 22.12+ instalados (ou usam só o Modo 2).
- Validar no esqueleto a execução nativa no Windows com `SelectorEventLoop` (simulador, ingestão, API e testes).
- Definir convenção de tópicos, QoS e ACLs do broker (pendência do T02).

## Concluída quando

- [x] MQTT/Mosquitto, PostgreSQL + TimescaleDB e backend Python confirmados.
- [x] FastAPI, cliente MQTT Python, Vue 3 + Vite e Chart.js adotados, sem impedimento.
- [x] Versões iniciais, migrações (Alembic), testes (pytest/Vitest) e estrutura dos componentes definidos.
- [x] Dois modos de desenvolvimento local descritos.
- [x] Forma de revisão da decisão registrada sem troca de contrato MQTT/API.
