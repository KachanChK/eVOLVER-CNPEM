# Validação do Store and Forward

Ensaio local de 24/11/2026 para a implementação `c9fb317` da branch
`e2-t06-store-and-forward`, com a migração `20261123_02`. Mosquitto 2.0.22 e TimescaleDB
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
| Migração e replay legados | Um UUID repetido em duas séries interrompeu a migração e preservou os dois registros originais. Após resolver o conflito no banco de teste, o replay equivalente retornou `duplicate` e manteve `received_at`. Duas tentativas concorrentes de um ID novo produziram uma gravação e uma duplicata. |
| Falhas de transação | Falhas injetadas durante a reserva e no commit deixaram o UUID disponível e ficaram sem ACK. Após remover cada falha, o mesmo evento recebeu `persisted`. Uma leitura com horário futuro também foi aceita após nova tentativa. |
| Reuso de vial | A OD gerada 1 ms antes de `ended_at` foi vinculada a A. A leitura exatamente no limite foi para a quarentena. O simulador descobriu B e gravou as novas leituras em B. |
| Controle de OD | A OD histórica acima do limite e dentro de 10 s permaneceu inelegível. Uma OD ao vivo equivalente gerou comando `od_max`. A seleção de retomada também foi exercitada com OD histórica mais recente. |
| Monitoramento | A tabela mostrou a temperatura antiga abaixo da leitura gerada depois dela, embora a antiga tivesse chegado por último. Os avisos usaram o horário de geração. O histórico da alocação A permaneceu visível após a inativação. |
| SQLite cheio | Um limite de páginas produziu `SQLITE_FULL`. O rollback manteve as linhas já gravadas. Após liberar espaço houve nova gravação. Falha injetada de remoção manteve a pendência até reaplicar o ACK. |

As amostras de queda registraram o payload original do SQLite e o resultado
central pelo mesmo UUID, incluindo `generated_at`, `received_at`, alocação e,
para OD, sequência e elegibilidade. Os desfechos MQTT, as respostas da API
e os registros de comandos ficaram no diretório local de evidências do ensaio.

Passaram 113 testes Python de unidade e contrato, 33 testes de integração
com TimescaleDB e 28 testes de frontend. O build Vite, Ruff e a revisão
independente também passaram.

## Capacidade com doze vials

A fila começou vazia. O gerador gravou 7.200 rodadas de 36 leituras, com
horário avançando 0,5 s por rodada para representar uma hora de queda.
Os 259.200 UUIDs originais tiveram ACK de aplicação observável e apareceram
uma única vez nas três séries do banco, com 86.400 leituras por série.
Os horários de geração, vínculos e valores foram conferidos por ID. A sequência
também foi conferida na OD, que está disponível na série central. Nenhuma OD
histórica da carga gerou comando de bombas.

A recuperação prosseguiu com a mesma fila após reinícios de teste. A vazão da
fase Windows oscilou perto da capacidade de geração. No trecho final, de
28 min 12 s, com rede e volume locais do Docker Linux, o simulador gerou
71,58 eventos/s. A taxa de confirmação ficou em torno de 124,42 eventos/s
e a fila caiu de 246.026 para 156.625 pendências no mesmo intervalo.

No encerramento, a união do registro central e do SQLite conciliou os
482.400 eventos gravados localmente no ensaio. O PostgreSQL tinha 325.848
IDs e o SQLite, 156.655 pendências novas, das quais 103 já tinham sido
gravadas no banco e ainda aguardavam aplicação do ACK na fila.

| Arquivo | Maior tamanho observado |
| --- | ---: |
| SQLite | 136.065.024 bytes |
| WAL | 6.538.472 bytes |
| Memória compartilhada do WAL | 32.768 bytes |
| Soma dos picos individuais | 142.636.264 bytes (136,03 MiB) |

Para esse perfil, reserve **160 MiB** em disco local para a fila e seus
arquivos auxiliares. O ensaio guardou o inventário original do SQLite,
os desfechos MQTT por UUID, as leituras centrais conciliadas, as pendências
no encerramento e as amostras de vazão.

Use o [guia de operação](../operations/README.md#recuperação-de-telemetria)
para repetir as quedas, inspecionar a fila e exportar a quarentena.
