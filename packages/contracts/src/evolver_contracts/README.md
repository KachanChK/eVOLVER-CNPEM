# Contratos MQTT — piloto simulado eVOLVER CNPEM

- **Versão do contrato:** `1.0`
- **Escopo:** comunicação local entre o simulador externo e os serviços do piloto.
- **Fora do escopo:** firmware, hardware real, unidades/calibrações científicas e garantia de efeito físico.

Os modelos Pydantic em `models.py` e `pilot.py` definem os payloads MQTT do
piloto. O script `export_schemas.py` gera os schemas JSON de `models.py` em
`schemas/`, no dialeto JSON Schema Draft 2020-12. Os testes verificam que os
schemas versionados correspondem aos modelos. Uma alteração incompatível
exige nova versão do contrato e novos tópicos `v{N}`.

Os payloads de `models.py` exigem o campo explícito `schema_version`.

## Tópicos e política de entrega

Nos tópicos parametrizados, `{equipment_id}` é o mesmo identificador presente no
payload e segue o formato dos schemas. A consulta de vials ativos usa o
identificador fixo no tópico. Todos os tópicos usam JSON UTF-8 sobre MQTT 5.

| Direção | Tópico | QoS | Retain | Payload |
| --- | --- | --- | --- | --- |
| Simulador → ingestão | `evolver/v1/{equipment_id}/telemetry` | 1 | não | `schemas/telemetry.schema.json` |
| Ingestão → simulador | `evolver/v1/{equipment_id}/telemetry/ack` | 1 | não | `schemas/telemetry-ack.schema.json` |
| Ingestão → simulador | `evolver/v1/{equipment_id}/telemetry/rejection` | 1 | não | `schemas/telemetry-rejection.schema.json` |
| Ingestão → simulador | `evolver/v1/{equipment_id}/commands` | 1 | **não** | `schemas/command.schema.json` |
| Simulador → ingestão | `evolver/v1/{equipment_id}/command-results` | 1 | não | `schemas/command-result.schema.json` |
| Simulador → ingestão | `evolver/v1/evolver-sim-01/active-vials/request` | 1 | não | `AllocationRequest` em `pilot.py` |
| Ingestão → simulador | `evolver/v1/evolver-sim-01/active-vials/response` | 1 | não | `AllocationResponse` em `pilot.py` |

QoS 1 cobre somente o transporte MQTT e permite reentregas. Ele não substitui a
confirmação de aplicação em `telemetry/ack`, que é emitida **apenas depois do commit
da transação central**. Nenhum comando pode ser publicado como retido: um comando
antigo não pode ser executado por um simulador que acabou de se reconectar.

## Consulta de vials ativos

O simulador assina a resposta antes de publicar o pedido. O pedido contém apenas
`request_id` (UUID). A ingestão devolve o mesmo `request_id` e `vials`, uma lista
de até 12 alocações ativas ordenadas por `vial_id`. Cada item contém `vial_id`
(inteiro entre 1 e 12), `experiment_id` (inteiro positivo de até 64 bits com sinal)
e `allocation_id` (UUID da alocação). O simulador atualizado usa esse UUID
em `experiment_run_id` e exige o UUID para aceitar a lista.
Quando não há alocações ativas, `vials` é uma lista vazia. Os modelos de
`pilot.py` aceitam somente os campos descritos aqui.

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
6. Falha de transporte, indisponibilidade do banco, horário de geração ainda
   no futuro ou ausência de ACK/rejeição são
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

A propriedade MQTT 5 `evolver-telemetry-mode` vai nos User Properties. O simulador
usa `live` na primeira tentativa de uma rodada com alocação recém-confirmada e
sessão pronta, com expiração MQTT de 2 s. Usa `history` para pendências recuperadas
e novas tentativas. A ingestão limita o controle de OD a publicações elegíveis e
mantém a janela de geração de 10 s. A ausência da propriedade segue o fluxo
legado. O JSON v1 é igual nos dois modos.

## Comandos e resultados simulados

O único comando de temperatura do piloto é `target_type: temperature_setpoint` com
`action: set`. Na versão `1.0`, `target_type: pump` e `pump_id: 1` identificam
o alvo lógico do grupo fixo de bombas `[1, 2, 3]` por alocação. Cada ação `turn_on`
ou `turn_off` usa um único comando.
Os valores `pump_id: 2` e `pump_id: 3` são inválidos. Não há unidade, vazão, duração
nem volume implícitos nesta versão.

A ingestão registra `command_id`, autor, alvo, ação, criação e validade antes de publicar.
O simulador valida a identidade e o prazo e pode enviar uma atualização de resultado
com `status: received`, seguida de `executed`, ou encerrar em `rejected`/`failed`.
Para `target_type: pump`, `executed` confirma a aplicação da ação ao grupo no
estado simulado. Se o prazo terminar sem resultado, a ingestão registra
**resultado desconhecido**, sem reenvio automático do comando do grupo.

`expires_at` deve ser posterior a `created_at`; o modelo Pydantic rejeita o comando
caso essa relação não seja respeitada. O cenário de expiração também é exercitado:
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
