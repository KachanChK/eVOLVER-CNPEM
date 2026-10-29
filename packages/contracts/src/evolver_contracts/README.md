# Contratos MQTT — piloto simulado eVOLVER CNPEM

- **Versão do contrato:** `1.0`
- **Escopo:** comunicação local entre o simulador externo e os serviços do piloto.
- **Fora do escopo:** firmware, hardware real, unidades/calibrações científicas e garantia de efeito físico.

Os modelos Pydantic em `models.py` são a fonte de verdade para as mensagens MQTT
do piloto. Simulador, ingestão e API importam esses mesmos modelos; os schemas
JSON em `schemas/` são gerados por `export_schemas.py` para consumidores que não
usam Python. Isso evita regras paralelas para o mesmo payload. Uma alteração
incompatível exige nova versão do contrato e novos tópicos `v{N}`.

Todo payload deve informar explicitamente `schema_version`; a versão não é inferida
nem preenchida pelo consumidor. Os arquivos declaram o dialeto JSON Schema Draft
2020-12 e os testes garantem que os schemas versionados correspondam aos modelos.

## Tópicos e política de entrega

`{equipment_id}` é o mesmo identificador presente no payload e deve obedecer ao
formato dos schemas. Todos os tópicos usam JSON UTF-8 sobre MQTT 5.

| Direção | Tópico | QoS | Retain | Payload |
| --- | --- | --- | --- | --- |
| Simulador → ingestão | `evolver/v1/{equipment_id}/telemetry` | 1 | não | `schemas/telemetry.schema.json` |
| Ingestão → simulador | `evolver/v1/{equipment_id}/telemetry/ack` | 1 | não | `schemas/telemetry-ack.schema.json` |
| Ingestão → simulador | `evolver/v1/{equipment_id}/telemetry/rejection` | 1 | não | `schemas/telemetry-rejection.schema.json` |
| API → simulador | `evolver/v1/{equipment_id}/commands` | 1 | **não** | `schemas/command.schema.json` |
| Simulador → ingestão | `evolver/v1/{equipment_id}/command-results` | 1 | não | `schemas/command-result.schema.json` |

QoS 1 cobre somente o transporte MQTT e permite reentregas. Ele não substitui a
confirmação de aplicação em `telemetry/ack`, que é emitida **apenas depois do commit
da transação central**. Nenhum comando pode ser publicado como retido: um comando
antigo não pode ser executado por um simulador que acabou de se reconectar.

## Telemetria, ACK e rejeição

1. O simulador cria a medição com `event_id`, `sequence` e `generated_at` e a grava
   primeiro em sua fila local durável.
2. Ele publica a mensagem em `telemetry` e mantém o item na fila até um desfecho de
   aplicação.
3. A ingestão valida o schema, a origem e a regra de idempotência; em seguida grava
   a medição (ou reconhece a mesma identidade como duplicata) em uma transação.
4. Somente após o commit, a ingestão publica `ack` com `status: persisted` ou
   `status: duplicate`. Ambos permitem remover a pendência ativa da fila.
5. Uma rejeição permanente publica `telemetry/rejection` com `disposition:
   quarantined`. O simulador deve mover o item para uma quarentena durável com o
   motivo registrado e removê-lo da fila de reenvio — uma mensagem inválida não
   pode bloquear as seguintes.
6. Falha de transporte, indisponibilidade do banco ou ausência de ACK/rejeição são
   situações transitórias: o item continua pendente com o mesmo `event_id`, horário
   e sequência. O reenvio jamais cria outra identidade.

Um payload que nem pode ser convertido de JSON não permite correlação confiável;
nesse caso a ingestão registra o erro operacional e, quando possível, o simulador
deve manter a mensagem em quarentena local. Os exemplos inválidos deste diretório
são JSON legível justamente para que a rejeição possa conter o `event_id`.

`received_at` é adicionado pela ingestão no armazenamento central; ele não faz parte
do payload publicado pelo simulador. Eventos atrasados continuam válidos: entram no
histórico por `generated_at` e não devem substituir automaticamente a leitura mais
recente só porque chegaram depois.

## Comandos e resultados simulados

O único comando de temperatura do piloto é `target_type: temperature_setpoint` com
`action: set`. As bombas usam `target_type: pump`, `pump_id` entre 1 e 3 e as ações
`turn_on` ou `turn_off`. Não há unidade, vazão, duração nem volume implícitos nesta
versão.

A API registra `command_id`, autor, alvo, ação, criação e validade antes de publicar.
O simulador valida a identidade e o prazo e pode enviar uma atualização de resultado
com `status: received`, seguida de `executed`, ou encerrar em `rejected`/`failed`.
`executed` significa somente que a alteração ocorreu no estado simulado. Se não
houver resultado no prazo definido pela implementação, a API registra **resultado
desconhecido**; não reenvia automaticamente comando de bomba.

`expires_at` deve ser posterior a `created_at`; o modelo Pydantic rejeita o comando
caso essa relação não seja respeitada. O cenário de aceite A7 também é exercitado:
um comando inicialmente válido expira durante a desconexão e recebe uma resposta
`rejected`/`expired` com o mesmo `command_id`.

## Schemas, exemplos e testes

- `models.py`: modelos Pydantic compartilhados pelos processos Python.
- `schemas/`: JSON Schemas Draft 2020-12 gerados a partir dos modelos.
- `packages/contracts/tests/fixtures/`: exemplos válidos, inválidos e semânticos.
- `packages/contracts/tests/test_contract_examples.py`: valida os mesmos exemplos
  tanto nos JSON Schemas quanto nos modelos Pydantic.

Para validar todo o conjunto:

```bash
uv sync --all-packages --group dev --frozen
uv run --all-packages ruff check backend/src simulator/src packages/contracts/src packages/contracts/tests
uv run --all-packages pytest packages/contracts/tests
```

O teste impede que um exemplo inválido seja aceito por engano e também falha se um
schema versionado deixar de corresponder ao modelo de execução.
