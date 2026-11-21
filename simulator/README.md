# Simulador de medições

O simulador gera valores de OD, pH e temperatura, nessa ordem, para cada frasco.
Os valores são simulados e servem para testar o software; não vêm de sensores nem
representam calibração ou precisão científica.

## Como o código está organizado

- `config.py` reúne as configurações do simulador.
- `telemetry.py` escolhe o próximo frasco e o tipo de medição e gera um valor.
- `runner.py` controla o intervalo e a parada do programa.
- `mqtt.py` envia as mensagens e verifica a confirmação do broker.

Cada valor parte de uma base e recebe uma variação e um ruído simulado. OD, pH e
temperatura têm geradores independentes e ondas com fases e períodos diferentes.
Esses padrões servem para testar o sistema, sem representar medições reais.

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
  sequência de vials ativos por rodada, repete os valores para facilitar testes.
  Sem esse ajuste, cada execução começa com novas sequências.
- `SIMULATOR_MAX_MESSAGES`: limite opcional de medições; `--max-messages` tem prioridade.
  Deixe ambos sem definir para executar sem limite.
- Para experimentar uma pausa, configure `SIMULATOR_PAUSE_AFTER_MESSAGES` e
  `SIMULATOR_PAUSE_SECONDS`. Para simular uma falha, use `SIMULATOR_FAIL_AFTER_MESSAGES`.

As opções avançadas de valores, variação e ruído continuam disponíveis na classe
`SimulatorSettings`. MQTT usa versão 5, QoS 1 e mensagens não retidas. Não há fila
local nem confirmação de gravação no banco; se a ingestão ou o banco estiverem fora
do ar, a temperatura pode não ser salva.
