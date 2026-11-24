# Tasks · Store and Forward de telemetria

As tasks 1 a 7 entregam a [spec](spec-store-and-forward.md) da [issue #6](https://github.com/KachanChK/eVOLVER-CNPEM/issues/6). A task 8 executa o aceite integrado da [issue #13](https://github.com/KachanChK/eVOLVER-CNPEM/issues/13).

| Task | Entrega | Dependências |
| --- | --- | --- |
| 1 | [Persistência idempotente no PostgreSQL](#task-1--garantir-a-unicidade-dos-eventos-no-postgresql) | — |
| 2 | [Confirmação e recuperação da ingestão](#task-2--emitir-ack-pós-commit-e-rejeições-na-ingestão) | 1 |
| 3 | [Proteção do controle de bombas](#task-3--impedir-que-od-histórica-acione-as-bombas) | 2 |
| 4 | [Fila durável no SQLite](#task-4--criar-a-fila-durável-no-sqlite) | — |
| 5 | [Coleta offline e descoberta de vials](#task-5--manter-a-coleta-com-a-última-lista-de-alocações) | 4 |
| 6 | [Reenvio e processamento de respostas MQTT](#task-6--reenviar-pendências-e-aplicar-respostas-mqtt) | 3, 5 |
| 7 | [Frescor no monitoramento](#task-7--corrigir-o-frescor-das-séries-no-monitoramento) | — |
| 8 | [Aceite integrado e documentação operacional](#task-8--validar-a-recuperação-de-ponta-a-ponta) | 6, 7 |

As tasks 1, 4 e 7 podem começar em paralelo. Aplicar a migração e atualizar a ingestão antes de iniciar o simulador com reenvio habilitado. Isso garante que a ingestão interprete a marcação de OD histórica desde o primeiro reenvio. [Ordem de implementação da spec](spec-store-and-forward.md#ordem-de-implementação)

## Task 1 · Garantir a unicidade dos eventos no PostgreSQL

- [ ] Criar via Alembic o registro global de IDs e o atributo de elegibilidade de OD para o controle. Preencher o registro a partir das três séries existentes, preservar a elegibilidade legada e interromper a migração com diagnóstico se houver UUIDs conflitantes.
- [ ] Gravar a reserva do ID, a leitura e a eventual decisão de OD na mesma transação. Armazenar tipo, horário de geração e hash determinístico do payload. Reconhecer duplicatas antigas pelos campos e vínculos disponíveis.
- [ ] Verificar a migração e a persistência com TimescaleDB descartável. Cobrir as três séries, concorrência no mesmo ID, colisão com conteúdo divergente, rollback e preservação do `received_at` original.

**Aceite.** Uma mesma leitura produz uma única linha lógica, inclusive sob concorrência. Alterações de tipo, horário ou conteúdo para um ID existente geram conflito. Um rollback deixa o ID disponível para nova tentativa.

[Migrações](../backend/migrations/) · [Modelos do banco](../backend/src/evolver/db/models.py) · [Testes de integração do banco](../backend/tests/db/test_database_integration.py)

## Task 2 · Emitir ACK pós-commit e rejeições na ingestão

- [ ] Publicar `persisted` ou `duplicate` em `telemetry/ack` após o commit síncrono. Publicar `telemetry/rejection` para falha permanente correlacionável e registrar as mensagens sem UUID ou origem seguros.
- [ ] Aplicar as validações do contrato e do vínculo `[started_at, ended_at)`. Manter falha de banco, commit incerto e horário ainda no futuro disponíveis para nova tentativa. Conferir início e recuperação da ingestão com broker ou banco indisponível.
- [ ] Atualizar o README do contrato MQTT com `allocation_id`, os desfechos e o momento da confirmação. Exercitar falha antes e durante o commit, alocação encerrada ou reutilizada, conflito de identidade e versão inválida.

**Aceite.** A ingestão emite ACK de sucesso após o commit da gravação ou da transação que reconheceu a duplicata. Uma leitura gerada durante a alocação original continua no experimento certo. A ingestão volta a processar telemetria quando o serviço indisponível retorna.

[Ingestão](../backend/src/evolver/ingestion/__main__.py) · [Contrato MQTT](../packages/contracts/src/evolver_contracts/README.md) · [Testes do contrato](../packages/contracts/tests/test_contract_examples.py)

## Task 3 · Impedir que OD histórica acione as bombas

- [ ] Ler `evolver-telemetry-mode` na ingestão e gravar a elegibilidade da OD. Respeitar a compatibilidade prevista na spec para publicações legadas e documentar a propriedade MQTT.
- [ ] Usar a elegibilidade em `consider_od` e na seleção da leitura candidata e das leituras mais recentes em `resume_reading`. Preservar a janela de 10 s para OD ao vivo e a reconciliação do grupo após a queda.
- [ ] Exercitar OD histórica dentro da janela de 10 s, OD mais recente inelegível e retomada por OD ao vivo. Conferir os comandos e as transições registrados.

**Aceite.** Reenvios entram no histórico com a alocação verificada quando válida. Eles não criam comandos nem interferem na retomada por uma leitura ao vivo elegível.

[Controle do grupo](../backend/src/evolver/ingestion/control.py) · [Testes de integração do controle](../backend/tests/db/test_pump_control_integration.py)

## Task 4 · Criar a fila durável no SQLite

- [ ] Criar banco dedicado com `WAL` e `synchronous=FULL`, vinculado ao equipamento e ao produtor. Persistir rodadas atômicas com o JSON original, a última lista confirmada de alocações e os desfechos de quarentena.
- [ ] Implementar as transações que removem pendências confirmadas ou registram rejeição com motivo. Validar os registros locais antes de enviá-los. Disponibilizar contagem, idade da pendência mais antiga e quantidade em quarentena para os logs.
- [ ] Configurar `SIMULATOR_TELEMETRY_QUEUE_PATH` e `SIMULATOR_TELEMETRY_QUEUE_MAX_EVENTS`. Aplicar a cota padrão de 259.200 eventos, incluindo a quarentena. Cobrir reabertura do arquivo, lista vazia, rodada sem espaço, rollback e falha de escrita ou remoção.

**Aceite.** Após reabrir o SQLite, os registros e payloads originais continuam íntegros. Cota atingida ou falha de escrita preserva a fila. Uma rejeição confirmada preserva o registro para inspeção local.

[Configuração do simulador](../simulator/src/evolver_simulator/config.py) · [Exemplo de configuração](../simulator/.env.example) · [Testes do simulador](../simulator/tests/)

## Task 5 · Manter a coleta com a última lista de alocações

- [ ] Desacoplar a cadência de coleta da descoberta de alocações e das tentativas de envio. Atualizar a lista em segundo plano somente após uma resposta válida e correlacionada. Persistir os UUIDs de alocação e a lista vazia.
- [ ] Retomar a coleta usando a última lista após reinício. Na primeira execução sem lista confirmada, aguardar a descoberta sem impedir o envio de pendências. Gravar cada rodada antes de disponibilizar seus eventos para envio.
- [ ] Pausar e retomar a coleta conforme a capacidade do SQLite. Contar apenas eventos novos confirmados localmente em `--max-messages` e nos cenários de pausa e falha. Ao atingir o limite da CLI, tentar concluir os envios dentro do prazo de confirmação e registrar as pendências ao sair.

**Aceite.** A coleta segue com o broker ou a ingestão fora e continua após reinício com a lista salva. Uma resposta vazia ou uma nova alocação passa a valer para as próximas rodadas. A geração pausa quando falta espaço e volta quando cabe uma rodada.

[Ciclo de coleta](../simulator/src/evolver_simulator/runner.py) · [Gerador](../simulator/src/evolver_simulator/telemetry.py) · [CLI](../simulator/src/evolver_simulator/__main__.py) · [Testes de coleta](../simulator/tests/test_runner.py)

## Task 6 · Reenviar pendências e aplicar respostas MQTT

- [ ] Assinar ACK, rejeição, alocações e comandos e aguardar `SUBACK`. Reconectar com a sessão e o cliente Paho conforme a spec. Preservar o processamento de comandos e resultados das bombas.
- [ ] Usar a fila durável como fonte das publicações pendentes. Aplicar janela limitada, atraso progressivo e prazo de confirmação. Enviar a primeira tentativa elegível como `live`, com expiração curta, e as recuperações e novas tentativas como `history`. Preservar o payload em todos os envios e reservar espaço na janela para leituras ao vivo.
- [ ] Correlacionar ACK e rejeição de aplicação por tópico, versão, equipamento e `event_id`. Testar PUBACK sem confirmação central, perda de ACK, reconexão, resposta inválida e rejeição seguida de leitura válida. Registrar mudanças de estado, contagem, idade da fila e diagnósticos de quarentena e recuperação.

**Aceite.** PUBACK, desconexão e timeout deixam a leitura pendente. ACK de aplicação conclui a pendência e rejeição válida a move à quarentena. Depois da reconexão, uma pendência antiga conserva o mesmo payload e é enviada como histórica.

[Cliente MQTT](../simulator/src/evolver_simulator/mqtt.py) · [Testes MQTT](../simulator/tests/test_mqtt.py) · [Permissões do broker](../mqtt/acl)

## Task 7 · Corrigir o frescor das séries no monitoramento

- [ ] Calcular a idade a partir do maior `generated_at` de cada série. Manter o aviso de 15 s, os horários de geração e recebimento na tabela e a consulta HTTP existente.
- [ ] Exercitar recarga do histórico com leituras fora de ordem, recebimento recente de evento antigo e recuperação de ponto no período original.

**Aceite.** O histórico preenche o horário original, inclusive para experimento inativado. Um evento antigo recém-recebido não remove o aviso de leitura antiga nem substitui o valor mais recente por horário de geração.

[Gráfico das séries](../frontend/src/TemperatureHistory.vue) · [Funções de histórico](../frontend/src/history.js) · [Testes de histórico](../frontend/tests/history.test.js)

## Task 8 · Validar a recuperação de ponta a ponta

- [ ] Executar a [matriz de aceite da spec](spec-store-and-forward.md#aceite) com simulador, Mosquitto, ingestão, TimescaleDB, API e interface. Interromper broker, ingestão e banco separadamente. Cobrir reinício com dependências indisponíveis, ACK perdido, duplicatas e conteúdo divergente, rejeição, troca de alocação e OD histórica dentro de 10 s.
- [ ] Simular uma hora de queda com geração de 72 eventos/s e fila inicialmente vazia. Conciliar os 259.200 eventos, medir espaço em disco e verificar que a fila diminui com a coleta ativa após a reconexão. Exercitar disco cheio e retomada em ensaio separado.
- [ ] Registrar a versão, a configuração e as evidências por ID no SQLite, nas respostas MQTT e no PostgreSQL. Anexar evidências da API, da tela e do histórico de comandos ao registro do ensaio. Atualizar os guias com a ordem de atualização, a reserva de disco medida e o procedimento de inspeção e exportação da quarentena.

**Aceite.** Cada evento durável do ensaio é conciliado com um desfecho observável. Após a recuperação, cada evento válido aparece exatamente uma vez no histórico correto, as rejeições aparecem na quarentena e somente a OD ao vivo interfere no controle. A capacidade, o espaço e a vazão são registrados na tarefa de validação.

[Validação #13](https://github.com/KachanChK/eVOLVER-CNPEM/issues/13) · [Guia de operação](../operations/README.md) · [Guia do simulador](../simulator/README.md) · [Guia da ingestão](../backend/src/evolver/ingestion/README.md)
