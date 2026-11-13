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

O simulador consulta a ingestão via MQTT para descobrir os vials em uso. Faz dez rodadas
em cinco segundos, a cada 0,5 segundo. Em cada rodada envia OD, pH e temperatura
para todos os vials ativos: 30 eventos por vial em cada execução. Sem vials ativos,
encerra sem enviar medições. Confirmações MQTT lentas podem prolongar a execução.

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

O limite conta medições geradas, não mensagens MQTT. `--max-messages` pode reduzir
a quantidade, mas não aumenta o limite de dez medições de cada tipo por vial. Cada medição é publicada no
contrato `evolver/v1/{equipment_id}/telemetry`. A ingestão salva temperatura em
`temperature_readings`, pH em `ph_readings` e OD em `od_readings`. O PUBACK
confirma a entrega ao broker, não a gravação no banco: confira o log da ingestão ou
consulte a tabela para verificar o salvamento.

## Ajustes opcionais

- `SIMULATOR_SEED`: opcional; com o mesmo número e a mesma configuração, repete
  as sequências para facilitar testes. Sem esse ajuste, cada execução começa com
  novas sequências.
- `SIMULATOR_MAX_MESSAGES`: limite menor de medições; `--max-messages` tem prioridade.
  Nenhum dos dois aumenta o limite de dez medições por tipo e vial.
- Para experimentar uma pausa, configure `SIMULATOR_PAUSE_AFTER_MESSAGES` e
  `SIMULATOR_PAUSE_SECONDS`. Para simular uma falha, use `SIMULATOR_FAIL_AFTER_MESSAGES`.

As opções avançadas de valores, variação e ruído continuam disponíveis na classe
`SimulatorSettings`. MQTT usa versão 5, QoS 1 e mensagens não retidas. Não há fila
local nem confirmação de gravação no banco; se a ingestão ou o banco estiverem fora
do ar, a temperatura pode não ser salva.
