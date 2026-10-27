# E1 · T03 — Stack e modo de desenvolvimento local

**Etapa:** 1 — Planejamento  
**Prioridade:** P0  
**Período:** 26–28/10/2026  
**Dependências:** E1 · T01 (#1); complementa E1 · T02 (arquitetura externa e fluxos)  
**Issue:** [#18](https://github.com/KachanChK/eVOLVER-CNPEM/issues/18)  
**Status:** proposta para revisão  
**Fronteira:** piloto local de 27/11/2026, em uma única máquina, com simulador externo e comandos sem efeito físico.

## Objetivo

Documentar a stack, as versões iniciais, as ferramentas de migração e teste, a estrutura prevista do repositório e os dois modos de execução local. No piloto, telemetria e comandos usam MQTT; o PostgreSQL + TimescaleDB guarda os dados; e o navegador acessa os dados pela API. Este documento registra escolhas e um roteiro de implementação, não comprova que todos os serviços já foram criados ou executados.

**Escopo incluído nesta decisão:** componentes de software externo, dependências de desenvolvimento, execução em uma máquina e verificações necessárias para reproduzir o piloto com dados simulados.

**Fora do escopo:** integração com equipamento real, comandos com efeito físico, calibração científica, implantação remota e metas de produção. O simulador representa a origem dos dados e o destino dos comandos nesta fase.

## Stack confirmada

| Camada | Escolha | Motivo | Papel no piloto |
| --- | --- | --- | --- |
| Transporte | **Eclipse Mosquitto (MQTT 5)** | Broker (servidor de mensagens) executável em contêiner, com persistência configurável. | Transportar telemetria, ACK de aplicação (confirmação após gravação), comandos e respostas entre simulador e serviços. |
| Banco | **PostgreSQL + TimescaleDB** | Guarda metadados e auditoria em tabelas relacionais e séries temporais em hypertables (tabelas particionadas por tempo). | Fonte do histórico persistido; deduplicação por `event_id` com uma tabela de IDs processados. |
| Backend | **Python** | Permite compartilhar modelos de mensagem entre os processos. | Simulador, ingestão e API, executados separadamente. |
| API | **FastAPI** | Usa modelos Pydantic para validar dados e gera a descrição OpenAPI das rotas HTTP. | Consultas, comandos autorizados e atualizações ao vivo. |
| Cliente MQTT | **paho-mqtt 2.x** (via `aiomqtt` nos serviços assíncronos) | Suporta MQTT 5; `aiomqtt` permite integrá-lo ao `asyncio` (execução assíncrona do Python). | Publicar e assinar os tópicos do simulador, da ingestão e da API. |
| Interface | **Vue 3 + Vite** | Curva de aprendizado curta, componentes de arquivo único, build rápido e servidor de desenvolvimento com recarga a quente. | Painéis, histórico, estado de conexão e operações simuladas. |
| Gráficos | **Chart.js 4** (com `vue-chartjs`) | Suficiente para séries de OD, pH e temperatura; leve e bem documentado. | Gráficos atuais e históricos. |

As tecnologias pedidas na issue foram adotadas para o piloto. A compatibilidade entre versões e a execução dos serviços ainda precisam ser verificadas quando as dependências restantes forem instaladas.

### Escolhas complementares

| Tema | Escolha | Motivo |
| --- | --- | --- |
| Acesso ao banco | **SQLAlchemy 2** + driver **psycopg 3** | ORM/Core maduro, compatível com async e com SQL explícito quando a consulta temporal exigir. |
| Migrações | **Alembic** | Versionar as alterações de esquema junto ao código. Criar a extensão, as hypertables e os índices do TimescaleDB por SQL nas migrações (`op.execute`) e conferir o resultado no banco. |
| Atualização ao vivo | **SSE (Server-Sent Events)** | A API envia eventos ao navegador por uma conexão HTTP contínua (`EventSource`); comandos seguem por requisições HTTP. Ao reconectar, a interface consulta novamente o estado pela API. Enviar atualizações somente após a gravação no banco; não há meta numérica de latência definida. |
| Aviso ingestão → API | **PostgreSQL `LISTEN/NOTIFY`** | Na transação de gravação, a ingestão emite `NOTIFY` com identificadores, sem enviar o dado inteiro. O PostgreSQL entrega o aviso após o commit; a API lê o registro no banco e o envia por SSE. Ao (re)conectar, a API relê o estado persistido, pois notificações perdidas não são recuperadas. Se esse mecanismo não atender ao piloto, consultar o banco periodicamente é a alternativa a avaliar. |
| Unicidade de eventos | **Tabela de IDs processados** (tabela comum, não hypertable), com `event_id` como chave primária | A chave única de uma hypertable precisa incluir a coluna de particionamento; por isso a ingestão grava o ID na tabela comum e a medição **na mesma transação**. Conflito de chave indica reenvio do mesmo evento e não cria outra medição lógica. |
| Fila do Store and Forward | **SQLite** (arquivo local do simulador) | Durável, transacional, sem serviço extra; sobrevive a reinício do processo. |
| Servidor ASGI | **Uvicorn** | Padrão para FastAPI. |
| Configuração | Variáveis de ambiente + arquivo `.env` (lido por `pydantic-settings`); `.env.example` versionado | Mesma configuração serve aos dois modos de execução. |
| Gerenciador Python | **uv** | Instalação rápida, `pyproject.toml` + `uv.lock` reprodutível. |
| Gerenciador JS | **npm** + `package-lock.json` | Vem com o Node; sem ferramenta extra. |
| Testes Python | **pytest** + `pytest-asyncio` | Testes unitários e de integração (com banco e broker reais do Compose). |
| Testes da interface | **Vitest** + Vue Test Utils | Integrado ao Vite. |
| Qualidade | **Ruff** (lint/format Python), **ESLint** + **Prettier** (frontend) | Configuração mínima, rápida. |

## Versões iniciais

Versões e faixas escolhidas para o piloto; a tabela não afirma que todas já estejam instaladas ou testadas. O `backend/pyproject.toml` e o `backend/uv.lock` já fixam as dependências do pacote de contratos MQTT. Quando os demais componentes forem criados, registrar as versões exatas no `uv.lock`, no `package-lock.json`, na versão de Node indicada por `.nvmrc`/`package.json` e nas tags das imagens do Compose. Uma atualização dessas escolhas deve ser documentada junto à alteração do projeto.

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
| Node.js | Linha 22, **22.12 ou superior**; conferir o mínimo exigido pela versão de Vite fixada e registrar a versão validada em `.nvmrc` e em `engines` do `package.json` |
| Vue | 3.5.x |
| Vite | Versão estável compatível com Node escolhido, a fixar no lock |
| Chart.js / vue-chartjs | 4.x / 5.x |
| Docker Engine / Compose | Docker Desktop com Compose v2 (`docker compose`); versão exata a registrar na validação |

**Verificar ao montar o ambiente:** conferir a compatibilidade da tag do TimescaleDB com PostgreSQL 17, instalar as dependências Python com o lock, instalar as dependências da interface com o lock e executar o build do Vite com a versão de Node registrada. Guardar versões efetivamente usadas, saída dos comandos e, se houver falha, o erro e a combinação que falhou. O resultado esperado é instalar e compilar sem conflito de versão; isso ainda não está comprovado para a aplicação completa.

## Estrutura do repositório

Estrutura prevista para o monorepo. Hoje, os documentos de planejamento estão na raiz e `backend/` contém os contratos MQTT, o `pyproject.toml`, o `uv.lock` e testes de contrato. Os demais caminhos abaixo descrevem o que deverá ser criado; mover os documentos para `docs/` exige atualizar seus links.

```text
eVOLVER-CNPEM/
├── docs/                    # destino previsto para documentos de planejamento; hoje estão na raiz
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

Simulador, ingestão e API devem ficar no mesmo pacote Python para compartilhar os modelos de mensagens (`contracts/`), mas rodar como **processos separados**. O simulador não deve importar `db/` nem `api/`: sua comunicação com os serviços centrais ocorre por MQTT. Conferir essa separação ao criar os pontos de entrada e testar cada processo isoladamente.

## Modos de desenvolvimento

Os dois modos previstos rodam no mesmo computador e usam os mesmos nomes de variáveis de ambiente; seus valores de conexão podem mudar conforme os serviços sejam acessados pela máquina ou pela rede do Compose. Esta seção é um roteiro para quando os arquivos e serviços descritos acima existirem. No estado atual do repositório, os comandos abaixo ainda não constituem uma execução comprovada.

### Modo 1 — Dependências em Compose, código local (dia a dia)

O Compose inicia Mosquitto e TimescaleDB; Python e Vue rodam diretamente na máquina, para depuração e recarga automática. Antes de executar, criar `compose.yaml`, configurar `.env` a partir de `.env.example` e implementar os pontos de entrada citados abaixo. Os comandos estão separados por terminal e diretório de trabalho.

Na raiz do repositório:

```bash
docker compose up -d
docker compose ps
```

Em `backend/`, preparar o ambiente e aplicar as migrações:

```bash
cd backend
uv sync --frozen
uv run alembic upgrade head
```

Em três terminais separados, todos iniciados em `backend/`:

```bash
uv run python -m evolver.ingestion
```

```bash
uv run uvicorn evolver.api.main:app --reload    # API na porta 8000
```

```bash
uv run python -m evolver.simulator
```

Em outro terminal, a partir da raiz:

```bash
cd frontend
npm ci
npm run dev                                    # interface na porta 5173; proxy /api para 8000
```

`uv sync --frozen` pressupõe o lock atualizado com as dependências da aplicação; `npm ci` pressupõe `package-lock.json`. Ambos ainda dependem da criação dos componentes correspondentes.

Uso previsto: desenvolvimento, depuração e testes de integração com banco e broker do Compose. Depois de iniciar os serviços, conferir `docker compose ps`, aplicar migrações sem erro, consultar a API, abrir a interface e executar `uv run pytest` em `backend/`. Registrar saídas, versões e a configuração usada; para um teste de ponta a ponta, guardar também os IDs das leituras simuladas e a consulta correspondente no banco ou na API. Resultado esperado: serviços acessíveis, sem erro de migração, e leituras simuladas visíveis no histórico. Ainda falta implementar e executar esse roteiro.

**Windows nativo:** o loop padrão `ProactorEventLoop` não fornece `add_reader`, usado pelo `aiomqtt`. A implementação precisa selecionar um loop compatível nos processos e testes que usarem esse cliente e verificar a conexão MQTT no Windows. Registrar a configuração adotada e o resultado do teste; se não funcionar, manter o desenvolvimento desses processos no Modo 2 até resolver a pendência. Essa verificação ainda não foi executada.

### Modo 2 — Compose completo (reprodução)

Todos os componentes em contêineres, para reproduzir o piloto em outra máquina ou executar a demonstração. Antes de executar, criar `compose.full.yaml`, as imagens da aplicação e o serviço de migração.

```bash
docker compose -f compose.yaml -f compose.full.yaml up --build
```

O arquivo completo deve incluir um serviço que execute `alembic upgrade head` antes da ingestão e da API; a interface deve ser servida após o build do Vite. Verificar a ordem de inicialização, consultar a API e a interface e executar os cenários A1–A8 de [escopo e aceite](escopo-e-aceite.md). Em um clone limpo, registrar o commit, as tags das imagens, `docker compose ps`, logs de migração e dos serviços e evidências dos cenários. Resultado esperado: o piloto sobe e os cenários produzem os dados simulados esperados; esse resultado depende da implementação e dos testes.

### Regras comuns

- Portas padrão: MQTT 1883, PostgreSQL 5432, API 8000, interface 5173 (dev) / 8080 (completo).
- No Modo 2, usar volumes nomeados para banco, persistência do Mosquitto e fila SQLite do simulador. No Modo 1, a fila SQLite é um arquivo local do simulador. Em ambos, verificar reinício sem perder leituras pendentes.
- `docker compose down -v` apaga os volumes locais do Compose; usar somente quando se quiser recomeçar do zero. No Modo 1, isso não apaga automaticamente o arquivo SQLite fora do Compose.
- Nenhuma credencial real no repositório: `.env.example` traz apenas valores de desenvolvimento.
