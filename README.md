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

   Os exemplos trazem credenciais apenas para desenvolvimento local. Se alterá-las, mantenha a conexão do banco em `backend/.env` compatível com `.env`, e as senhas MQTT de ingestão e do simulador compatíveis com `mqtt/.env`. `VIAL_ID` e `SIMULATOR_VIAL_IDS` de configurações antigas não são mais usados. Os arquivos `.env` reais são privados e não devem ser enviados ao Git.

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

O comando abre uma janela de PowerShell para cada serviço local: API, ingestão e interface. A saída de cada processo aparece na respectiva janela; pressione **Ctrl+C** nela para interromper somente aquele serviço. Abra [http://127.0.0.1:5173](http://127.0.0.1:5173), clique em **Criar experimento** e escolha um dos 12 vials livres. O script avisa se as portas 8000 ou 5173 já estiverem em uso; não é necessário iniciá-lo novamente enquanto o programa estiver funcionando.

Em outro PowerShell, também na raiz, gere leituras:

```powershell
.\scripts\simular.ps1
```

O simulador envia OD, pH e temperatura para todos os vials ativos em rodadas a cada 0,5 segundo, **sem limite de duração**. Para parar, pressione **Ctrl+C na janela do simulador**. A lista de experimentos ativos é consultada pela ingestão via MQTT a cada rodada: novos experimentos começam a receber medições e os encerrados deixam de recebê-las. Sem experimentos ativos, o simulador continua aguardando. Os gráficos são atualizados a cada cinco segundos.

O simulador usa sequências independentes para os três tipos. Por padrão, uma nova execução gera outros valores. Para repetir uma sequência em testes, defina `SIMULATOR_SEED` em `simulator/.env`; com a mesma semente, configuração e sequência de vials ativos por rodada, os valores são reproduzíveis. Confirmações MQTT lentas podem atrasar as rodadas. O limite opcional `SIMULATOR_MAX_MESSAGES` continua disponível para testes curtos; deixe-o sem definir para simular continuamente.

**Inativar** libera o vial e mantém o histórico visível. **Excluir** oculta o experimento na interface e preserva os dados no banco.

## Acompanhar os gráficos

- Os três gráficos começam mostrando o **último minuto**. Use **1 min**, **5 min**, **30 min** ou **Tudo** para mudar o período de temperatura, pH e OD juntos.
- **Pausar visualização** congela as curvas e o período mostrado, sem parar o simulador ou a gravação no banco. Use **Retomar visualização** para voltar aos dados atuais. Você também pode trocar de período enquanto a visualização está pausada.
- Intervalos maiores que cinco segundos sem medições aparecem como espaços com a indicação **Sem leituras**. A linha não liga os dois lados da pausa. Esse intervalo considera o ritmo atual do simulador, de uma leitura de cada tipo a cada 0,5 segundo.
- Cada gráfico informa há quanto tempo a última leitura foi recebida. Após 15 segundos sem dados novos, o aviso fica destacado. Se uma atualização falhar, os dados anteriores continuam visíveis com um aviso.
- **Mostrar média de 5 s** acrescenta uma linha tracejada com a média das leituras dos últimos cinco segundos. A curva original continua visível e a média recomeça após uma lacuna. A opção começa desligada.
- Em períodos longos, a curva usa uma seleção de pontos que preserva os maiores e menores valores por trecho. Todas as leituras originais do período continuam disponíveis na tabela, em páginas de 50, da mais recente para a mais antiga. Os registros no banco não são alterados.

Experimentos encerrados mostram o período final da execução, sem deslocar o gráfico conforme o relógio avança.

## Consultar o banco e acompanhar os serviços

As principais tabelas no banco `evolver` são `vials`, `experiments`, `temperature_readings`, `ph_readings` e `od_readings`. As leituras mantêm o ID do experimento e do vial.

Para consultar as últimas leituras pela linha de comando:

```powershell
docker compose exec timescaledb psql -U evolver -d evolver -c "SELECT experiment_id, vial_id, temperature_celsius, generated_at FROM temperature_readings ORDER BY generated_at DESC LIMIT 10;"
docker compose exec timescaledb psql -U evolver -d evolver -c "SELECT experiment_id, vial_id, ph_value, generated_at FROM ph_readings ORDER BY generated_at DESC LIMIT 10;"
docker compose exec timescaledb psql -U evolver -d evolver -c "SELECT experiment_id, vial_id, od_value, generated_at FROM od_readings ORDER BY generated_at DESC LIMIT 10;"
```

Os comandos usam o nome de banco e usuário dos exemplos; ajuste-os se os tiver alterado. No DBeaver, conecte a `127.0.0.1:5432` com o banco, usuário e senha configurados em `.env`.

As mensagens da API, ingestão e interface aparecem nas janelas abertas pelo script e são gravadas em `.local/api.log`, `.local/ingestao.log` e `.local/interface.log`. Se um serviço encerrar, a janela permanece aberta para você ler o erro.

O PUBACK confirma a entrega ao broker, não a gravação. Mantenha a ingestão em execução antes de iniciar o simulador e confirme o resultado na interface ou no banco. Neste piloto não há fila de reenvio após falha; mantenha também os relógios do simulador e do banco sincronizados.

## Testes

Na raiz:

```powershell
uv run --locked --all-packages ruff check backend/src backend/tests simulator/src simulator/tests packages/contracts/src packages/contracts/tests
uv run --locked --all-packages pytest
npm --prefix frontend run build
npm --prefix frontend test
```

Os testes de integração exigem bancos TimescaleDB descartáveis; sem as URLs de teste, são ignorados. Consulte [as instruções de integração](backend/migrations/README.md).

Para parar apenas os contêineres sem apagar dados:

```powershell
docker compose stop
docker compose --env-file mqtt/.env -f mqtt/compose.yaml stop
```

Para encerrar a aplicação local, pressione **Ctrl+C** nas três janelas dos serviços. Os contêineres continuam em execução até receberem os comandos `docker compose stop` acima. Não use `docker compose down -v` se quiser manter o banco: essa opção remove o volume de dados.

Leia [AGENTS.md](AGENTS.md) antes de alterar o repositório com agentes.
