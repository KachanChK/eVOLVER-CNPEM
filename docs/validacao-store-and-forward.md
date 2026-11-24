# Validação do Store and Forward

Ensaio local de 24/11/2026 na branch `e2-t06-store-and-forward`, a partir de
`2f2dcea`, com a migração `20261123_02`. Mosquitto 2.0.22 e TimescaleDB
2.31.0 sobre PostgreSQL 17 rodaram em instâncias descartáveis. A ingestão e
o simulador usaram Python 3.12 e MQTT 5 com QoS 1. A API e o frontend foram
verificados com os dados do mesmo banco de ensaio.

## Recuperação e consistência

| Ensaio | Resultado observado |
| --- | --- |
| Broker fora e reinício forçado | A ingestão iniciou com o broker parado. O simulador abriu o SQLite, aguardou a primeira descoberta e, em uma segunda queda, recuperou 11 itens já duráveis após ser encerrado à força. Os 20 IDs da amostra final chegaram uma vez às séries centrais. |
| Ingestão fora | O produtor usou a lista local enquanto o broker seguia disponível. Os 12 IDs da amostra foram conciliados após o retorno. |
| Banco fora e reinício da ingestão | A ingestão permaneceu em execução e recuperou a conexão. Os 93 IDs da amostra foram conciliados. |
| ACK perdido | O primeiro envio gravou o evento. O simulador recuperado recebeu `duplicate` para o mesmo UUID e removeu a pendência, com `received_at` preservado. |
| Erros de identidade e esquema | Alterações de tipo, conteúdo e horário para o mesmo UUID foram rejeitadas. A versão inválida recebeu `unsupported_schema_version`. JSON sem UUID correlacionável apareceu apenas no log. |
| Falhas de transação | Falhas injetadas durante a reserva e no commit deixaram o UUID disponível e ficaram sem ACK. Após remover cada falha, o mesmo evento recebeu `persisted`. Uma leitura com horário futuro também foi aceita após nova tentativa. |
| Reuso de vial | A OD gerada 1 ms antes de `ended_at` foi vinculada a A. A leitura exatamente no limite foi para a quarentena. O simulador descobriu B e gravou as novas leituras em B. |
| Controle de OD | A OD histórica acima do limite e dentro de 10 s permaneceu inelegível. Uma OD ao vivo equivalente gerou comando `od_max`. A seleção de retomada também foi exercitada com OD histórica mais recente. |
| Monitoramento | A tabela mostrou a temperatura antiga abaixo da leitura gerada depois dela, embora a antiga tivesse chegado por último. Os avisos usaram o horário de geração. O histórico da alocação A permaneceu visível após a inativação. |
| SQLite cheio | Um limite de páginas produziu `SQLITE_FULL`. O rollback manteve as linhas já gravadas. Após liberar espaço houve nova gravação. Falha injetada de remoção manteve a pendência até reaplicar o ACK. |

As amostras de queda registraram o payload original do SQLite e o resultado
central pelo mesmo UUID, incluindo `generated_at`, `received_at`, alocação e,
para OD, sequência e elegibilidade. Os desfechos MQTT, as respostas da API
e os registros de comandos ficaram no diretório local de evidências do ensaio.

Use o [guia de operação](../operations/README.md#recuperação-de-telemetria)
para repetir as quedas, inspecionar a fila e exportar a quarentena.
