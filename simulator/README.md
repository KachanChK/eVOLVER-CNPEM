# Simulador de medições

O simulador gera valores de OD, pH e temperatura, nessa ordem, para cada frasco.
Os valores são simulados e servem para testar o software; não vêm de sensores nem
representam calibração ou precisão científica.

## Como o código está organizado

- `config.py` reúne as configurações do simulador.
- `telemetry.py` escolhe o próximo frasco e o tipo de medição e gera um valor.
- `runner.py` controla o intervalo e a parada do programa.
- `mqtt.py` envia as mensagens e verifica a confirmação do broker.

O estado da bomba simulada e os comandos concluídos ficam em um arquivo SQLite
durável (`~/.evolver-simulator/pump-state.sqlite3`). Configure
`SIMULATOR_PUMP_STATE_PATH` para outro caminho persistente se necessário. O
simulador grava o estado antes de confirmar a execução de um comando.

### Atualizar uma instalação existente

Aplique a migração Alembic `20261122_03` e atualize a ingestão e o simulador
juntos. A descoberta MQTT inclui o UUID da alocação, que os comandos de bomba
carregam no campo existente `experiment_run_id`. Os tópicos, o schema dos
comandos e resultados, e os IDs numéricos na API e na telemetria são preservados.
O simulador novo consegue ler alocações antigas sem UUID para publicar
telemetria, mas rejeita comandos numéricos e usa a bomba desligada nesses vials.
O simulador antigo não reconhece a resposta nova de descoberta.

Mantenha o SQLite. As tabelas antigas continuam no arquivo. Como seus registros
numéricos podem pertencer a outro banco, o simulador não os restaura nem
reaproveita sua ordem ou seus resultados. Na atualização, reinicie a ingestão
para reconciliar a bomba com `turn_off`. Depois disso, alocações com o mesmo
UUID preservam o estado entre reinícios. Um banco recriado emite UUIDs novos,
mesmo se repetir IDs numéricos.

Revise estas variáveis no ambiente ou no arquivo `.env`:

- `SIMULATOR_OD_BASELINE` agora exige um valor entre 0,10 e 0,80, inclusive.
- `SIMULATOR_OD_NOISE` aceitava até 0,10. Reduza valores acima de 0,01 antes
  de iniciar o simulador. O valor 0 continua desabilitando o ruído.
- Remova `SIMULATOR_OD_VARIATION`. A antiga onda de OD foi substituída pelos
  passos da bomba e a variável é ignorada.

### Dinâmica de OD

A primeira leitura de OD de cada par vial/experimento usa `SIMULATOR_OD_BASELINE`
(padrão 0,35). Nas próximas leituras a OD sobe **0,02 por amostra** com a bomba
desligada e desce **0,05 por amostra** com a bomba ligada. Na cadência de 0,5 s,
as taxas nominais são 0,04 OD/s na subida e 0,10 OD/s na descida. A OD satura em
**[0,10; 0,80]**, inclusive. O ruído de OD altera o passo em até
`SIMULATOR_OD_NOISE` em cada sentido (padrão 0,005, máximo 0,01, zero desabilita).
A direção permanece a mesma até a saturação, inclusive com limiares próximos.
Se houver atraso nas rodadas, aplica-se um passo por amostra gerada.

Um novo experimento no mesmo vial começa na OD inicial e com a bomba desligada.
Ao reiniciar o processo, a primeira OD usa a base configurada e os próximos
passos usam o estado da bomba restaurado do SQLite. Ao pausar um experimento, o
controlador envia `turn_off` se a bomba estiver ligada. Após executar o comando,
o simulador confirma o mesmo `command_id` e a OD volta a subir.
As ondas e o ruído de pH e temperatura continuam independentes da bomba.

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

O simulador executa continuamente, com rodadas a cada 0,5 segundo. Em cada rodada,
consulta a ingestão via MQTT para descobrir os vials em uso e envia OD, pH e temperatura
para cada um. Novos experimentos passam a receber medições automaticamente; experimentos
encerrados deixam de recebê-las na próxima consulta. Sem vials ativos, continua aguardando.
Para encerrar, pressione **Ctrl+C na janela do simulador**. Os demais serviços continuam
funcionando. Confirmações MQTT lentas podem atrasar as rodadas; falhas de conexão ainda
são informadas e encerram o programa.

O terminal mostra o valor de cada medição enviada, por exemplo:

```text
Frasco 1 | OD: 0.346191 | Enviado ao MQTT
Frasco 1 | pH: 7.000101 | Enviado ao MQTT
Frasco 1 | Temperatura: 37.002365 °C | Enviado ao MQTT
```

O envio ao MQTT não confirma que a medição foi gravada no banco.

Para um teste mais curto com uma medição de cada tipo:

```powershell
uv run --env-file simulator/.env --package evolver-cnpem-simulator python -m evolver_simulator --max-messages 3
```

O limite conta medições geradas, não mensagens de consulta MQTT. Sem limite configurado,
a execução continua até a interrupção por Ctrl+C. Cada medição é publicada no
contrato `evolver/v1/{equipment_id}/telemetry`. A ingestão salva temperatura em
`temperature_readings`, pH em `ph_readings` e OD em `od_readings`. O PUBACK
confirma a entrega ao broker, não a gravação no banco: confira o log da ingestão ou
consulte a tabela para verificar o salvamento.

## Ajustes opcionais

- `SIMULATOR_SEED`: opcional; com o mesmo número, a mesma configuração e a mesma
  sequência de vials ativos e de estados da bomba por rodada, repete os valores.
  Sem esse ajuste, cada execução começa com novas sequências.
- `SIMULATOR_MAX_MESSAGES`: limite opcional de medições; `--max-messages` tem prioridade.
  Deixe ambos sem definir para executar sem limite.
- Para experimentar uma pausa, configure `SIMULATOR_PAUSE_AFTER_MESSAGES` e
  `SIMULATOR_PAUSE_SECONDS`. Para simular uma falha, use `SIMULATOR_FAIL_AFTER_MESSAGES`.

As opções avançadas de pH e temperatura estão em `SimulatorSettings`.
MQTT usa versão 5, QoS 1 e mensagens não retidas. Não há fila
local nem confirmação de gravação no banco; se a ingestão ou o banco estiverem fora
do ar, a temperatura pode não ser salva.

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
