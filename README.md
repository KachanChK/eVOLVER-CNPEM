# eVOLVER CNPEM

Este repositório reúne a primeira prova local do fluxo de temperatura:

```text
Simulador Python → Mosquitto (MQTT) → ingestão Python → PostgreSQL + TimescaleDB
```

O simulador envia uma leitura de 37 °C por execução. A ingestão valida a mensagem e
a grava em `temperature_readings`, vinculada a um registro em `vials`. O banco e o
broker rodam em contêineres independentes; simulador e ingestão rodam no Windows com
Python 3.12 e `uv`.

## Teste local completo

Execute os comandos no PowerShell, a partir da raiz do repositório. É necessário
Docker Desktop iniciado e `uv` instalado.

1. Prepare as configurações locais e as dependências:

   ```powershell
   if (!(Test-Path .env)) { Copy-Item .env.example .env }
   if (!(Test-Path mqtt/.env)) { Copy-Item mqtt/.env.example mqtt/.env }
   if (!(Test-Path backend/.env)) { Copy-Item backend/.env.example backend/.env }
   if (!(Test-Path simulator/.env)) { Copy-Item simulator/.env.example simulator/.env }
   uv sync --all-packages --group dev --frozen
   ```

   Ajuste senhas e portas de forma correspondente nos arquivos de cada serviço.

2. Inicie banco e broker e espere ambos ficarem saudáveis:

   ```powershell
   docker compose up -d --wait
   docker compose -f mqtt/compose.yaml --env-file mqtt/.env up -d --wait
   ```

3. Aplique as migrações do banco:

   ```powershell
   uv run --env-file backend/.env --package evolver-cnpem-backend alembic -c backend/alembic.ini upgrade head
   ```

   A migração que simplifica o schema recusa um banco antigo que contenha dados.
   Consulte [migrações](backend/migrations/README.md) antes de converter um banco já
   utilizado.

4. Cadastre um frasco de teste. O número retornado será o `VIAL_ID` do simulador:

   ```powershell
   docker compose exec timescaledb psql -U evolver -d evolver -c "INSERT INTO vials (equipment_id, label, created_at) VALUES ('evolver-sim-01', 'Frasco de teste', now()) RETURNING vial_id;"
   ```

   Se você já cadastrou um frasco para `evolver-sim-01`, pode usar o ID existente.
   Ajuste `VIAL_ID` em `simulator/.env` para o número escolhido.

5. Deixe a ingestão aberta em um terminal:

   ```powershell
   uv run --env-file backend/.env --package evolver-cnpem-backend python -m evolver.ingestion
   ```

   Ela deve mostrar `Ingestão MQTT pronta para temperaturas.`

6. Em outro terminal, na raiz do repositório, publique a leitura:

   ```powershell
   uv run --env-file simulator/.env --package evolver-cnpem-simulator python -m evolver_simulator
   ```

   O simulador deve mostrar `PUBACK recebido`. A ingestão deve mostrar `Temperatura
   gravada`. Cada nova execução gera outro `event_id` e outra linha.

7. Consulte o histórico:

   ```powershell
   docker compose exec timescaledb psql -U evolver -d evolver -c "SELECT vial_id, temperature_celsius, generated_at, received_at FROM temperature_readings ORDER BY generated_at DESC LIMIT 10;"
   ```

## Visualizar no DBeaver

Crie uma conexão **PostgreSQL** com host `127.0.0.1`, porta `5432`, banco `evolver`,
usuário `evolver` e senha `evolver-local-only` (ou os valores de `.env`). A extensão
TimescaleDB funciona dentro do PostgreSQL; não requer driver separado. Abra
`evolver` → `Schemas` → `public` → `Tables` para ver `vials` e
`temperature_readings`. A consulta sugerida em
[banco de dados](backend/src/evolver/db/README.md) mostra leitura e frasco juntos.

Para parar os serviços preservando os dados, interrompa a ingestão com `Ctrl+C` e
execute `docker compose down` e `docker compose -f mqtt/compose.yaml --env-file
mqtt/.env down`. Não use `down -v` para um banco que queira manter.

## Limites desta prova

O PUBACK confirma que o broker recebeu a publicação; ainda não há confirmação de
gravação devolvida ao simulador, fila de reenvio ou envio contínuo. O tópico
`evolver/dev` e o payload atual são temporários; o contrato MQTT `evolver/v1`, a API,
a interface web, OD, pH e bombas continuam como etapas futuras. Os documentos em
`docs/` descrevem o piloto completo, além do que já está executável.

Agentes de IA devem ler [AGENTS.md](AGENTS.md) antes de alterar o repositório.
