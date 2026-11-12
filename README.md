# eVOLVER CNPEM

Esta versão permite testar o caminho de uma leitura de temperatura:

```text
Simulador → Mosquitto → ingestão → TimescaleDB → FastAPI → interface Vue
```

Cadastre experimentos pela interface e escolha um dos 12 vials do equipamento simulado.
Cada execução do simulador envia uma leitura de **37 °C** para cada vial com um
experimento ativo. A página do experimento mostra o gráfico e o histórico.

## 1. Instalar o Docker Desktop no Windows

Se o Docker Desktop já abre e mostra o mecanismo em execução, vá para a etapa 2.

1. Abra o **PowerShell como administrador** e verifique o WSL com `wsl --version`.
   Se o WSL ainda não estiver instalado, execute `wsl --install` e **reinicie o
   Windows**. Se já estiver instalado, execute `wsl --update`. O Docker usa WSL 2
   para rodar os contêineres Linux deste projeto.
2. Baixe o instalador na [página oficial do Docker Desktop para Windows](https://docs.docker.com/desktop/setup/install/windows-install/).
   Execute o instalador, selecione o mecanismo **WSL 2** quando solicitado e conclua
   a instalação. Reinicie o Windows se o instalador pedir.
3. Abra **Docker Desktop** pelo menu Iniciar. Aguarde até ele indicar que está em
   execução. Em **Settings → General**, confirme o uso do mecanismo WSL 2, se essa
   opção aparecer.
4. Abra um novo PowerShell comum e confirme que o Docker responde:

   ```powershell
   docker info
   docker compose version
   ```

Se o Docker mostrar **“Virtual Machine Platform is not enabled”**, abra o PowerShell
como administrador, execute o comando abaixo e **reinicie o Windows**. Depois, abra
o Docker Desktop novamente:

```powershell
Enable-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform -All
```

Se o Docker ainda não iniciar, confira se a virtualização do processador está
habilitada no BIOS/UEFI, conforme os [requisitos do Docker](https://docs.docker.com/desktop/setup/install/windows-install/)
e o [guia do WSL da Microsoft](https://learn.microsoft.com/windows/wsl/install).

## 2. Instalar o uv e preparar o Python

Se `uv --version` já funcionar no PowerShell, vá para a etapa 3. Caso contrário,
instale o `uv` pelo [instalador oficial para Windows](https://docs.astral.sh/uv/getting-started/installation/):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Feche e abra o PowerShell após instalar. Confira a instalação e prepare o Python 3.12:

```powershell
uv --version
uv python install 3.12
```

O `uv` gerencia o Python usado pelo projeto; não é necessário instalar Python por
outro instalador.

## 3. Preparar os arquivos do projeto

Abra a pasta `eVOLVER-CNPEM` que contém este README no Explorador de Arquivos,
digite `powershell` na barra de endereço e pressione Enter. Todos os próximos
comandos devem ser executados **nessa pasta**, a raiz do repositório.

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

## 4. Iniciar o banco e o MQTT

```powershell
docker compose up -d --wait
docker compose --env-file mqtt/.env -f mqtt/compose.yaml up -d --wait --force-recreate
```

Espere os dois comandos terminarem com os serviços saudáveis (`healthy`). Eles criam
dois projetos separados no Docker Desktop: `evolver-cnpem` e `evolver-mqtt`. Recriar
o contêiner do Mosquitto aplica as permissões de consulta dos vials ativos.

## 5. Criar as tabelas

```powershell
uv run --env-file backend/.env --package evolver-cnpem-backend alembic -c backend/alembic.ini upgrade head
```

Isso cria `experiments` e cadastra os vials 1 a 12 em um banco novo. A migração
recusa um banco com vials do piloto anterior. Para fazer o reinício local e descartar
esses vials e leituras, siga as instruções de [migrações do banco](backend/migrations/README.md).

## 6. Abrir a interface e cadastrar um experimento

Em um terminal na raiz, inicie a API:

```powershell
uv run --env-file backend/.env --package evolver-cnpem-backend uvicorn evolver.api.main:app --reload
```

Em outro terminal, com Node.js 22.12 ou superior, inicie a interface:

```powershell
cd frontend
npm ci
npm run dev
```

Abra [a interface local](http://localhost:5173), clique em **Criar experimento** e
escolha um vial livre. **Inativar** libera o vial e mantém o histórico visível.
**Excluir** libera o vial e retira o experimento da interface, preservando os dados no banco.

## 7. Receber e enviar a temperatura

Abra outro PowerShell na raiz do repositório e inicie a ingestão:

```powershell
uv run --env-file backend/.env --package evolver-cnpem-backend python -m evolver.ingestion
```

Deixe esse terminal aberto. Ele deve mostrar `Ingestão MQTT pronta para temperaturas.`

Em outro PowerShell na raiz, execute o simulador:

```powershell
uv run --env-file simulator/.env --package evolver-cnpem-simulator python -m evolver_simulator
```

O simulador consulta os experimentos ativos via MQTT e mostra `PUBACK recebido`
por vial. Quando a ingestão mostrar `Temperatura gravada`, recarregue a página do
experimento para ver a leitura. Execute o simulador novamente para gerar mais pontos.

## 8. Visualizar o banco no DBeaver

Se ainda não tiver o DBeaver, instale o [DBeaver Community para Windows](https://dbeaver.io/download/).
Depois, selecione **Nova conexão → PostgreSQL** e preencha:

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
`temperature_readings` e escolha **Visualizar dados**. Use `experiment_id` para
consultar o histórico de um experimento mesmo depois da reutilização do vial:

```sql
SELECT e.name, t.vial_id, t.temperature_celsius,
       t.generated_at, t.received_at
FROM temperature_readings AS t
JOIN experiments AS e ON e.id = t.experiment_id
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
