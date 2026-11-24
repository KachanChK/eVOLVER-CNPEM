# Simulador de medições

O simulador gera valores de OD, pH e temperatura, nessa ordem, para cada frasco.
Os valores são simulados e servem para testar o software; não vêm de sensores nem
representam calibração ou precisão científica.

## Como o código está organizado

- `config.py` reúne as configurações do simulador.
- `telemetry.py` escolhe o próximo frasco e o tipo de medição e gera um valor.
- `runner.py` controla o intervalo e a parada do programa.
- `mqtt.py` envia as mensagens e verifica a confirmação do broker.

No contrato MQTT, `pump_id: 1` identifica o grupo fixo de bombas `[1, 2, 3]`.
O estado único do grupo por alocação e vial e
os comandos concluídos ficam no SQLite (`~/.evolver-simulator/pump-state.sqlite3`). Configure
`SIMULATOR_PUMP_STATE_PATH` para outro caminho persistente se necessário. O
simulador grava o estado, registra a ação aplicada ao grupo no log e publica um
resultado `executed` com o `command_id` do grupo.

### Atualizar uma instalação existente

Aplique as migrações com `alembic upgrade head`. Inicie e verifique a ingestão
atualizada antes de iniciar o simulador. A telemetria e os comandos do grupo
usam o UUID da alocação no campo `experiment_run_id`. O simulador só confirma
listas com UUID em todos os vials ativos e reaproveita o estado SQLite existente
das bombas. O contrato limita `pump_id` a `1` e exige o UUID nos comandos do grupo.

A ingestão aceita leituras com ID numérico ou sem identificador para o
histórico, pela janela de tempo do experimento. Só a OD ao vivo vinculada ao UUID
pode participar do controle e da retomada do grupo. O UUID mantém leituras
atrasadas na alocação original quando a janela ainda é válida. Um UUID
desconhecido no banco recriado é recusado, mesmo com IDs numéricos repetidos.

Mantenha o SQLite. As tabelas antigas continuam no arquivo. Como seus registros
numéricos podem pertencer a outro banco, o simulador não os restaura nem
reaproveita sua ordem ou seus resultados. Na atualização, reinicie a ingestão
para reconciliar o grupo com `turn_off`. Depois disso, alocações com o mesmo
UUID preservam o estado entre reinícios. Um banco recriado emite UUIDs novos,
mesmo se repetir IDs numéricos.

Revise estas variáveis no ambiente ou no arquivo `.env`:

- `SIMULATOR_OD_BASELINE` agora exige um valor entre 0,10 e 0,80, inclusive.
- `SIMULATOR_OD_NOISE` aceitava até 0,10. Reduza valores acima de 0,01 antes
  de iniciar o simulador. O valor 0 continua desabilitando o ruído.
- Remova `SIMULATOR_OD_VARIATION`. A antiga onda de OD foi substituída pelos
  passos do controle de OD e a variável é ignorada.

### Dinâmica de OD

A primeira leitura de OD de cada par vial/experimento usa `SIMULATOR_OD_BASELINE`
(padrão 0,35). Nas próximas leituras a OD sobe **0,02 por amostra** com o grupo
desligado e desce **0,05 por amostra** com o grupo ligado. O passo se aplica uma
vez por amostra para todo o grupo. Na cadência de 0,5 s,
as taxas nominais são 0,04 OD/s na subida e 0,10 OD/s na descida. A OD satura em
**[0,10; 0,80]**, inclusive. O ruído de OD altera o passo em até
`SIMULATOR_OD_NOISE` em cada sentido (padrão 0,005, máximo 0,01, zero desabilita).
A direção permanece a mesma até a saturação, inclusive com limiares próximos.
Se houver atraso nas rodadas, aplica-se um passo por amostra gerada.

Um novo experimento no mesmo vial começa na OD inicial e com o grupo desligado.
Ao reiniciar o processo, a primeira OD usa a base configurada e os próximos
passos usam o estado do grupo restaurado do SQLite. Ao pausar um experimento, o
controlador envia `turn_off` se o grupo estiver ligado. Após executar o comando,
o simulador confirma o mesmo `command_id` e a OD volta a subir.
As ondas e o ruído de pH e temperatura continuam independentes do grupo.

## Preparar

1. Copie `mqtt/.env.example` para `mqtt/.env` e `simulator/.env.example` para
   `simulator/.env`. As senhas do simulador nos dois arquivos devem ser iguais.
2. Crie experimentos na interface e escolha os vials disponíveis.
3. Inicie o broker em `mqtt/` e a ingestão. A ingestão e o banco precisam
   estar funcionando para guardar as medições.

Na raiz do repositório, instale as dependências e inicie o broker:

```powershell
uv sync --all-packages --group dev --frozen
docker compose --project-directory mqtt up -d
```

## Executar

Na raiz, execute o simulador:

```powershell
.\scripts\simular.ps1
```

O simulador grava rodadas de OD, pH e temperatura a cada 0,5 segundo no
SQLite. Descobre alocações e envia pendências em ciclos independentes da coleta.
Durante uma indisponibilidade usa a última lista confirmada, inclusive depois de
reiniciar. Uma lista confirmada vazia deixa a coleta aguardando novos experimentos.
Para encerrar, pressione **Ctrl+C na janela do simulador**.

Os logs mostram o estado da coleta e do envio, a quantidade em quarentena,
a contagem de pendências, a idade da mais antiga e as confirmações.

Para um teste mais curto com uma medição de cada tipo:

```powershell
uv run --env-file simulator/.env --package evolver-cnpem-simulator python -m evolver_simulator --max-messages 3
```

O limite conta medições novas confirmadas no SQLite. Ao atingir o limite, o
simulador tenta concluir os envios por até 5 s e registra as pendências ao sair.
Cada medição é publicada em `evolver/v1/{equipment_id}/telemetry`. A fila mantém
o evento após o PUBACK do broker e remove a pendência ao receber a confirmação
de gravação da ingestão.

## Ajustes opcionais

- `SIMULATOR_SEED`: opcional; com o mesmo número, a mesma configuração e a mesma
  sequência de vials ativos e de estados do grupo por rodada, repete os valores.
  Sem esse ajuste, cada execução começa com novas sequências.
- `SIMULATOR_MAX_MESSAGES`: limite opcional de medições; `--max-messages` tem prioridade.
  Deixe ambos sem definir para executar sem limite.
- `SIMULATOR_TELEMETRY_QUEUE_PATH` define o arquivo da fila. Por padrão é
  `telemetry.sqlite3` no mesmo diretório do estado das bombas. Use disco local
  e mantenha um simulador por arquivo.
- `SIMULATOR_TELEMETRY_QUEUE_MAX_EVENTS` define a cota para pendências e
  quarentena. A cota de 259.200 eventos cobre uma hora com 12 vials.
- Para experimentar uma pausa, configure `SIMULATOR_PAUSE_AFTER_MESSAGES` e
  `SIMULATOR_PAUSE_SECONDS`. Para simular uma falha, use `SIMULATOR_FAIL_AFTER_MESSAGES`.

Ao faltar espaço para gravar a rodada, a coleta pausa. O envio continua enquanto
o SQLite estiver disponível e a coleta volta quando houver espaço suficiente.
Consulte o [procedimento de inspeção e quarentena](../operations/README.md#recuperação-de-telemetria).

## Reproduzir dois ciclos de OD

Na raiz do repositório, depois de instalar os pacotes do workspace, execute:

```powershell
$env:PYTHONPATH = 'simulator/src;backend/src;packages/contracts/src'
uv run --frozen --all-packages pytest -q -s simulator/tests/test_mqtt.py -k two_controller_cycles
```

O teste liga a regra de histerese do backend ao simulador por um cliente MQTT de
teste. Usa a semente 71 e ruído de 0,01. Para cada par de limiares, imprime as
quatro leituras que acionaram `turn_on`, `turn_off`, `turn_on` e `turn_off`,
seguidas da primeira leitura da nova subida. Verifica a correlação dos resultados
com cada comando e a direção e faixa de todas as amostras.
