# eVOLVER CNPEM

Piloto local para cadastrar experimentos, simular medições de temperatura, pH e densidade óptica (OD) e acompanhar o histórico na interface.

```text
Simulador → MQTT (Mosquitto) → ingestão → PostgreSQL/TimescaleDB → API → interface
```

Os valores são simulados e não representam sensores ou medições científicas. O uso descrito abaixo é local, no Windows.

## Requisitos

- Docker Desktop em execução, com Docker Compose.
- Python 3.12 e [uv](https://docs.astral.sh/uv/getting-started/installation/).
- Node.js 22.12 ou superior e npm.
- PowerShell na pasta raiz deste repositório.

## Primeira configuração

1. Crie os arquivos de configuração sem substituir os que já existirem:

   ```powershell
   if (!(Test-Path .env)) { Copy-Item .env.example .env }
   if (!(Test-Path mqtt/.env)) { Copy-Item mqtt/.env.example mqtt/.env }
   if (!(Test-Path backend/.env)) { Copy-Item backend/.env.example backend/.env }
   if (!(Test-Path simulator/.env)) { Copy-Item simulator/.env.example simulator/.env }
   ```

   Os exemplos trazem credenciais apenas para desenvolvimento local. Se alterá-las, mantenha a conexão do banco em `backend/.env` compatível com `.env`, e as senhas MQTT de ingestão e do simulador compatíveis com `mqtt/.env`. Os arquivos `.env` reais são privados e não devem ser enviados ao Git.

2. Instale as dependências Python e da interface:

   ```powershell
   uv sync --all-packages --group dev --frozen
   Push-Location frontend
   npm ci
   Pop-Location
   ```

3. Inicie o banco e o broker e aguarde ambos ficarem saudáveis:

   ```powershell
   docker compose up -d --wait
   docker compose --env-file mqtt/.env -f mqtt/compose.yaml up -d --wait
   ```

4. Crie ou atualize as tabelas:

   ```powershell
   uv run --env-file backend/.env --package evolver-cnpem-backend alembic -c backend/alembic.ini upgrade head
   ```

   As migrações recusam certos bancos antigos que já têm dados. Antes de alterar uma instalação usada, faça backup e consulte [migrações do banco](backend/migrations/README.md). Não apague volumes para contornar essa proteção.

## Iniciar e usar

Com os contêineres em execução, na raiz do repositório:

```powershell
.\scripts\iniciar-local.ps1
```

O comando inicia a API, a ingestão e a interface em segundo plano. Abra [http://127.0.0.1:5173](http://127.0.0.1:5173), clique em **Criar experimento** e escolha um dos 12 vials livres. O script avisa se as portas 8000 ou 5173 já estiverem em uso; não é necessário iniciá-lo novamente enquanto o programa estiver funcionando.

Em outro PowerShell, também na raiz, gere leituras:

```powershell
.\scripts\simular.ps1
```

O script consulta os experimentos ativos e envia medições para os vials correspondentes. Cada execução gera até três leituras de OD, três de pH e três de temperatura por vial; depois, encerra. Os gráficos são atualizados a cada cinco segundos.

O simulador usa sequências independentes para os três tipos. Por padrão, uma nova execução gera outros valores. Para repetir uma sequência em testes, defina `SIMULATOR_SEED` em `simulator/.env`; com a mesma semente e configuração, os resultados são reproduzíveis. `SIMULATOR_INTERVAL_SECONDS` ajusta o intervalo entre as medições.

**Inativar** libera o vial e mantém o histórico visível. **Excluir** oculta o experimento na interface e preserva os dados no banco.

## Consultar o banco e os registros

As principais tabelas no banco `evolver` são `vials`, `experiments`, `temperature_readings`, `ph_readings` e `od_readings`. As leituras mantêm o ID do experimento e do vial.

Para consultar as últimas leituras pela linha de comando:

```powershell
docker compose exec timescaledb psql -U evolver -d evolver -c "SELECT experiment_id, vial_id, temperature_celsius, generated_at FROM temperature_readings ORDER BY generated_at DESC LIMIT 10;"
docker compose exec timescaledb psql -U evolver -d evolver -c "SELECT experiment_id, vial_id, ph_value, generated_at FROM ph_readings ORDER BY generated_at DESC LIMIT 10;"
docker compose exec timescaledb psql -U evolver -d evolver -c "SELECT experiment_id, vial_id, od_value, generated_at FROM od_readings ORDER BY generated_at DESC LIMIT 10;"
```

Os comandos usam o nome de banco e usuário dos exemplos; ajuste-os se os tiver alterado. No DBeaver, conecte a `127.0.0.1:5432` com o banco, usuário e senha configurados em `.env`.

Os registros da API, ingestão e interface ficam em `.local`, por exemplo:

```powershell
Get-Content .local/ingestao.log -Tail 20
Get-Content .local/api-error.log -Tail 20
```

O PUBACK confirma a entrega ao broker, não a gravação. Mantenha a ingestão em execução antes de iniciar o simulador e confirme o resultado na interface ou no banco. Neste piloto não há fila de reenvio após falha; mantenha também os relógios do simulador e do banco sincronizados.

## Testes

Na raiz:

```powershell
uv run --locked --all-packages ruff check backend/src backend/tests simulator/src simulator/tests packages/contracts/src packages/contracts/tests
uv run --locked --all-packages pytest
npm --prefix frontend run build
```

Os testes de integração exigem bancos TimescaleDB descartáveis; sem as URLs de teste, são ignorados. Consulte [as instruções de integração](backend/migrations/README.md).

Para parar apenas os contêineres sem apagar dados:

```powershell
docker compose stop
docker compose --env-file mqtt/.env -f mqtt/compose.yaml stop
```

A API, a ingestão e a interface iniciadas pelo script são processos locais separados. Seus PIDs ficam em `.local/pids.json` e podem ser usados para identificá-los no Gerenciador de Tarefas. Não use `docker compose down -v` se quiser manter o banco: essa opção remove o volume de dados.

Leia [AGENTS.md](AGENTS.md) antes de alterar o repositório com agentes.
