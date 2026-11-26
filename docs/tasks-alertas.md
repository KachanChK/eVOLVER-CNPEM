# Tasks · Alertas do eVOLVER

As nove tarefas entregam a [spec de alertas](spec-alertas.md). Cada tarefa termina com um resultado verificável. Os limites, valores de teste e prazos seguem a spec.

| Task | Entrega | Dependências |
| --- | --- | --- |
| 1 | Persistência de alertas e estado do monitoramento | — |
| 2 | Alertas de temperatura, pH e OD fora da faixa | 1 |
| 3 | Alertas de falta de dados | 2 |
| 4 | Alertas e recuperação do grupo de bombas | 1 |
| 5 | API de consulta, leitura e arquivamento | 1 |
| 6 | Página Alertas, indicador e cards | 5 |
| 7 | Central Python e cenários de telemetria | — |
| 8 | Cenário de falha de bombas no simulador | 4, 7 |
| 9 | Aceite de ponta a ponta | 2, 3, 4, 5, 6, 7, 8 |

Para uma pessoa ou um agente, a ordem numérica permite validar primeiro a detecção, depois a interface e por fim a demonstração de ponta a ponta. Com dois agentes, um pode cuidar de persistência, detecção e API enquanto o outro começa pela central Python. Depois, o segundo pode integrar o cenário de bombas e a interface conforme os contratos estiverem disponíveis. A task 9 reúne as evidências de toda a entrega.

## Task 1 · Persistir alertas e o estado do monitoramento

- [x] Adicionar a migração Alembic, os modelos e as operações de persistência. Registrar identidade do experimento e da alocação, nome exibido, vial, tipo, motivo e horários de emissão, leitura, arquivamento e encerramento.
- [x] Persistir o início do monitoramento e a última leitura ao vivo por alocação e métrica. Garantir que a gravação da leitura e a mudança da ocorrência possam usar a mesma transação.
- [x] Garantir unicidade de ocorrência aberta por alocação e tipo, inclusive sob concorrência. Ordenar o cursor de emissão pela visibilidade das transações confirmadas.
- [x] Testar migração sobre banco com dados prévios, rollback de uma emissão, duas tentativas concorrentes de abrir a mesma ocorrência e retomada do estado após reconexão.

**Aceite.** Uma ocorrência aberta gera um único registro. O estado sobrevive ao reinício. Reverter a transação da leitura reverte o alerta associado. Alertas confirmados em momentos diferentes podem ser consultados em sequência sem lacunas.

[Persistência na spec](spec-alertas.md#persistência-e-api) · [Modelos atuais](../backend/src/evolver/db/models.py)

## Task 2 · Detectar leituras fora da faixa

- [x] Adicionar as faixas inclusivas à configuração do backend e validar limites finitos e ordenados. Aplicar os padrões de 36,0 a 39,0 °C, pH 6,80 a 7,50 e OD 0,10 a 0,80.
- [x] Integrar a avaliação à gravação de telemetria e avançar o horário da última leitura elegível por alocação e métrica. Usar apenas eventos novos, ao vivo, com UUID de alocação ativa e idade inferior a 15 segundos.
- [x] Abrir um alerta na primeira leitura fora da faixa, armazenar o valor e os limites e encerrar a ocorrência na primeira leitura elegível dentro da faixa. Cobrir limite exato, desvios nas duas direções, duplicatas, reenvios, leituras fora de ordem e troca de alocação.

**Aceite.** Para cada métrica, um valor igual ao limite fica na faixa. Uma leitura discrepante abre um alerta, as seguintes mantêm a ocorrência e o retorno à faixa permite um novo alerta. Os ciclos normais de OD e a telemetria recuperada seguem seus fluxos atuais.

[Leituras discrepantes na spec](spec-alertas.md#leituras-discrepantes) · [Ingestão](../backend/src/evolver/ingestion/telemetry.py)

## Task 3 · Detectar falta de dados por vial

- [x] Executar a verificação na ingestão a cada segundo, inclusive quando o MQTT estiver desconectado. Medir a idade pelo horário de geração da última leitura elegível ou pelo início do monitoramento se a alocação ainda não tiver dados.
- [x] Após 15 segundos, abrir uma ocorrência no vial com as métricas em atraso. Atualizar a mesma ocorrência conforme a lista mudar e mostrar **Sem dados do vial** quando as três métricas estiverem em atraso. Encerrar quando as três voltarem a ter leituras recentes.
- [x] Testar ausência antes da primeira leitura, falta de uma métrica seguida das demais, reenvio histórico durante a falha, reinício da ingestão, retorno do PostgreSQL e encerramento da alocação.

**Aceite.** Com relógio controlado, aos 14 segundos o vial segue sem alerta de falta de dados. A primeira verificação a partir de 15 segundos registra a falha. Leituras históricas entram no histórico e a ocorrência encerra somente após o retorno das leituras recentes das três métricas.

[Falta de dados na spec](spec-alertas.md#falha-no-recebimento-de-dados) · [Ciclo da ingestão](../backend/src/evolver/ingestion/__main__.py)

## Task 4 · Alertar e recuperar falhas do grupo de bombas

- [x] Registrar **Falha no grupo de bombas** ao receber `failed`. Registrar **Comando das bombas sem confirmação** quando um comando efetivamente enviado expirar sem execução confirmada ou for rejeitado como `expired`. Correlacionar pelo `command_id` e distinguir o envio da reserva em `sent_at`.
- [x] Manter uma ocorrência por alocação durante reentregas e falhas sucessivas. Usar um novo `turn_off` para a recuperação, com pelo menos 10 segundos entre tentativas automáticas e uma tentativa pendente por alocação. Encerrar a ocorrência quando o desligamento for confirmado.
- [x] Exercitar confirmação normal, resultado explícito, expiração, comando apenas reservado, cancelamento, reentrega e recuperação. Rodar os testes existentes de pausa, retomada, reconciliação e encerramento.

**Aceite.** Falha explícita e ausência de confirmação exibem motivos distintos. Um comando apenas reservado fica fora dos alertas de falta de confirmação. Durante a falha, as tentativas de recuperação respeitam o intervalo e mantêm um alerta. Após confirmar o desligamento, o controle por OD volta quando estiver habilitado.

[Falhas de bombas na spec](spec-alertas.md#falha-nas-bombas) · [Controle atual](../backend/src/evolver/ingestion/control.py)

## Task 5 · Expor o histórico e as ações pela API

- [x] Implementar `GET /api/alerts` com histórico paginado por horário de emissão e ID, indicador global de não lidos e consulta incremental pelo cursor de emissão.
- [x] Implementar `POST /api/alerts/read` e `POST /api/alerts/clear` para o conjunto visível até o cursor informado. Arquivar preservando os registros e seus estados de ocorrência.
- [x] Testar ordenação com empates, paginação, retomada da consulta incremental, persistência dos não lidos e repetição segura das ações. Concorrer emissão nova com leitura e limpeza para verificar o limite do cursor.

**Aceite.** Um cliente consegue recuperar todos os alertas visíveis na ordem da spec, continuar a consulta depois de uma interrupção e preservar alertas emitidos após o cursor usado para ler ou limpar.

[API na spec](spec-alertas.md#persistência-e-api) · [API atual](../backend/src/evolver/api/main.py)

## Task 6 · Implementar a página Alertas e os cards

- [x] Adicionar a rota `/alertas` e a entrada na navegação. Mostrar indicador acessível de não lidos e consultar a API a cada segundo a partir da interface compartilhada entre as páginas.
- [x] Exibir o histórico em ordem de emissão com os detalhes de cada tipo. Marcar como lidos os alertas ao entrar na página e quando aparecerem com a página aberta. Implementar **Limpar alertas** com confirmação sobre o cursor da lista.
- [x] Mostrar cards no canto superior direito, empilhados em caso de chegada simultânea, cada um com seu prazo de cinco segundos e opção de fechar. Na primeira carga, usar os alertas anteriores para o histórico e o indicador. Em reconexão, retomar a partir do último cursor confirmado.
- [x] Testar chegada simultânea, atualização de um alerta de falta de dados já visível, troca de rota, recarga e chegada durante a limpeza. Rodar `npm test` e `npm run build` em `frontend/`.

**Aceite.** Em condições locais normais, um alerta novo chega ao card em até dois segundos após o registro e fica visível por cinco segundos. Abrir **Alertas** apaga o indicador confirmado pela API. A limpeza preserva alertas mais novos que o conjunto confirmado.

[Interface na spec](spec-alertas.md#histórico-e-interface) · [Navegação atual](../frontend/src/main.js)

## Task 7 · Abrir a central Python e simular anomalias de telemetria

- [x] Adicionar a janela Tkinter em `simulator/`, iniciada por `scripts/simular.ps1`. Oferecer modo sem janela pela CLI. Fechar a janela deixa a coleta em execução, e encerrar o simulador fecha a janela.
- [x] Listar alocações ativas para selecionar experimento e vial. Mostrar o andamento, bloquear disparos repetidos e concluir o cenário caso a alocação mude ou termine.
- [x] Implementar uma emissão de 40,0 °C, pH 7,70 ou OD 0,85 ao acionar o botão correspondente. Restaurar a geração normal na rodada seguinte e preservar a dinâmica interna da OD.
- [x] Suspender por 20 segundos apenas a publicação das novas leituras do vial selecionado, mantendo a coleta e a fila. Na retomada, priorizar as leituras novas e enviar as acumuladas como históricas. Testar os efeitos com dois vials, a expiração automática e o reuso de uma alocação.

**Aceite.** Cada botão de discrepância produz uma única leitura anômala no fluxo MQTT. A pausa mantém a coleta do vial escolhido e a publicação do outro. Os eventos acumulados mantêm os IDs e os horários originais no reenvio.

[Central na spec](spec-alertas.md#central-de-testes-do-simulador) · [Ciclo do simulador](../simulator/src/evolver_simulator/runner.py)

## Task 8 · Simular falha nas bombas por 60 segundos

- [x] Adicionar **Falha nas bombas** com validação da alocação ativa, dos limites de OD, da automação habilitada e do estado conhecido do grupo. Mostrar quando a central aguarda um comando e quando aplica a falha.
- [x] Quando for preciso provocar um comando, emitir uma leitura normal para a faixa de alerta no limite adequado do controle de OD. Durante 60 segundos, responder a comandos válidos do grupo com `failed` e `simulation_error`, preservando o estado aplicado. Persistir o desfecho para reentregar o mesmo resultado pelo `command_id`.
- [x] Testar as precondições, a seleção do vial, a duplicação de comandos durante e depois da janela e a execução bem-sucedida de um comando de recuperação após seu término.

**Aceite.** O alerta resulta do comando do controlador e da falha recebida por MQTT. O cenário afeta somente o vial escolhido. Ao fim dos 60 segundos, o simulador volta a executar comandos novos e conserva o resultado dos anteriores.

[Central na spec](spec-alertas.md#central-de-testes-do-simulador) · [Cliente MQTT do simulador](../simulator/src/evolver_simulator/mqtt.py)

## Task 9 · Validar a entrega de ponta a ponta

- [x] Aplicar a migração em um banco local de teste com dados prévios. Executar os testes Python de contrato, simulador, controle e integração com TimescaleDB, além dos testes e do build do frontend.
- [x] Com simulador, Mosquitto, ingestão, PostgreSQL, API e Vue, executar a matriz de aceite da spec. Cobrir operação com 12 vials, cada botão, perda de uma única métrica, expiração de comando, reenvio histórico, reinício durante uma ocorrência, reuso de vial e limpeza com alerta concorrente.
- [x] Medir o intervalo entre o registro do alerta e a aparição do card e os cinco segundos de exibição. Guardar os IDs de alerta, leitura ou comando e alocação, além do resultado da API e da tela. Registrar a versão utilizada e os cenários verificados.

**Aceite.** Cada cenário de falha produz a ocorrência esperada na alocação correta, com histórico e card verificáveis. Os cenários de recuperação encerram a ocorrência e permitem que uma nova falha emita um novo alerta. O resultado de cada linha da matriz fica registrado.

[Matriz de aceite](spec-alertas.md#critérios-de-aceite)

[Resultados e evidências da validação](validacao-alertas.md)
