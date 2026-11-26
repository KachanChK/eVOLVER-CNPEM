# eVOLVER CNPEM

Piloto local para cadastrar experimentos e acompanhar leituras simuladas de temperatura, pH e densidade óptica (OD). [Visão do projeto](docs/projeto.md) · [Arquitetura](docs/arquitetura-atual.md)

## Requisitos

- Windows com PowerShell e Docker Desktop em execução.
- Python 3.12 e `uv`.
- Node.js 22.12 ou superior e npm.

Execute os comandos na raiz do repositório, onde está este README.

## Primeira configuração

1. Crie os arquivos `.env` a partir dos exemplos. Os arquivos existentes são preservados.

   ```powershell
   if (!(Test-Path .env)) { Copy-Item .env.example .env }
   if (!(Test-Path mqtt/.env)) { Copy-Item mqtt/.env.example mqtt/.env }
   if (!(Test-Path backend/.env)) { Copy-Item backend/.env.example backend/.env }
   if (!(Test-Path simulator/.env)) { Copy-Item simulator/.env.example simulator/.env }
   ```

   Se personalizar a configuração, alinhe `backend/.env` com o banco definido em `.env` e os dados de conexão MQTT do backend e do simulador com `mqtt/.env`.

2. Instale as dependências Python e da interface.

   ```powershell
   uv sync --all-packages --group dev --frozen
   npm.cmd --prefix frontend ci
   ```

## Iniciar o banco e o MQTT

Suba os dois serviços, aguarde os contêineres ficarem saudáveis e aplique as migrações.

```powershell
docker compose up -d --wait
docker compose --env-file mqtt/.env -f mqtt/compose.yaml up -d --wait
uv run --env-file backend/.env --package evolver-cnpem-backend alembic -c backend/alembic.ini upgrade head
```

Se estiver atualizando um banco antigo com dados, consulte o [guia de migrações](backend/migrations/README.md).

## Iniciar e usar

1. Execute `.\scripts\iniciar-local.ps1`. O script abre três janelas, uma para a API, uma para a ingestão e uma para a interface. Os logs ficam em `.local/`.
2. Abra [a interface local](http://127.0.0.1:5173), clique em **Novo experimento**, preencha os dados e escolha um vial livre.
3. Execute `.\scripts\simular.ps1` em outro PowerShell. Abra o detalhe do experimento para acompanhar as leituras. O simulador continua em execução até você interrompê-lo.

O simulador grava as leituras em uma fila SQLite antes de publicá-las. Durante uma queda, ele usa a última lista confirmada de vials ativos. No retorno, reenvia as pendências até receber da ingestão a confirmação de gravação no PostgreSQL. O painel usa o horário de geração para mostrar a idade de cada leitura. [Recuperação de telemetria](operations/README.md#recuperação-de-telemetria)

## Parar e manter os dados

Pressione **Ctrl+C** no simulador e em cada janela da aplicação. Para parar também os contêineres, execute:

```powershell
docker compose --env-file mqtt/.env -f mqtt/compose.yaml stop
docker compose stop
```

## Resetar o ambiente local

**O reset apaga os dados locais.** Isso inclui experimentos, leituras, histórico de comandos, dados do broker MQTT, estado das bombas simuladas e telemetria pendente no SQLite. Para guardar o histórico dos experimentos, faça [backup do banco](operations/README.md#backup-e-restauração) antes de continuar.

1. Pressione **Ctrl+C** no simulador e nas janelas da API, da ingestão e da interface.
2. Remova os contêineres e os volumes locais do MQTT e do banco. Se iniciou os serviços com nomes de projeto Compose personalizados, use os mesmos nomes aqui.

   ```powershell
   docker compose --env-file mqtt/.env -f mqtt/compose.yaml down --volumes
   docker compose down --volumes
   ```

3. Com o simulador parado, execute o comando abaixo na raiz do repositório. Ele limpa o estado das bombas simuladas e a fila de telemetria pendente, incluindo os arquivos auxiliares do SQLite. Os caminhos seguem a configuração do simulador em `simulator/.env` e nas variáveis de ambiente. Os bancos são recriados ao iniciar o simulador.

   ```powershell
   .\scripts\simular.ps1 -ResetSqlite
   ```

4. Para limpar também os logs e as saídas locais de testes, apague a pasta `.local` na raiz do repositório. Os arquivos `.env` e as dependências instaladas podem ser reutilizados.
5. Volte a [iniciar o banco e o MQTT](#iniciar-o-banco-e-o-mqtt) e [abra a aplicação](#iniciar-e-usar). Antes de cadastrar um experimento novo, a lista deve estar vazia e os 12 vials devem estar livres.

## Testes

```powershell
uv run --locked --all-packages pytest
npm.cmd --prefix frontend test
```

Os testes de integração usam um [banco descartável](backend/migrations/README.md#testes-de-integração).
