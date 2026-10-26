# E1 · T01 — Escopo e critérios de aceite do piloto

**Etapa:** 1 — Planejamento  
**Prioridade:** P0  
**Período da atividade:** 26–27/10/2026  
**Entrega prevista do piloto:** 27/11/2026  
**Dependências:** nenhuma  
**Status deste documento:** proposta para revisão; pendências listadas ao final.

## Objetivo

Fechar o escopo de um piloto inteiramente local, executado com dados e comandos simulados. O aceite demonstra que o software externo consegue receber, preservar, consultar e apresentar dados de forma rastreável e que os comandos chegam ao simulador e têm resultado simulado identificável. O piloto não valida precisão científica nem comportamento de equipamento físico.

## Escopo do piloto

### Incluído

- Execução local dos serviços externos necessários ao fluxo demonstrado: simulador, transporte/mensageria, ingestão, persistência, API e interface, conforme a arquitetura escolhida para a implementação.
- Telemetria simulada de **OD**, **pH** e **temperatura medida**, com identificadores de origem e horários de geração e recebimento.
- **Setpoint de temperatura** como comando simulado, mantido distinto da temperatura medida.
- Comandos independentes de **ligar e desligar as bombas 1, 2 e 3**, sem afirmar leitura de estado físico, vazão ou volume dispensado.
- Consulta do estado mais recente e do histórico, incluindo indicação de dados antigos/desconexão.
- Persistência durável de telemetria pendente no produtor/simulador e reenvio após reconexão (*Store and Forward*). A remoção da fila depende de confirmação da aplicação após commit no banco; reenvios da mesma identidade não criam registros duplicados.
- Registro rastreável de comandos: solicitação, resposta do simulador e estado final simulado, correlacionados por `command_id`.
- Backup e restauração dos dados e metadados necessários à demonstração, com verificação da consistência após restauração.

### Fora do escopo

- Conexão ou controle de hardware real, sensores, atuadores, placas ou microcontroladores.
- Agente embarcado, firmware, alterações no equipamento e protocolos experimentais automáticos.
- Garantia de precisão, calibração ou interpretação científica dos valores simulados.
- Execução automática de turbidostato, quimiostato ou outras rotinas experimentais.
- Alegação de que um comando publicado foi executado fisicamente. Resultado significa apenas resposta do simulador.
- Meta de escala, taxa de produção ou latência de produção. Escala e cadência usadas no aceite são parâmetros de teste, a serem registrados antes da execução.

## Classes de prioridade

### P0 — necessário para o aceite do piloto

1. Identificar origem e evento; preservar horário de geração e horário de recebimento.
2. Ingerir OD, pH e temperatura sem confundir temperatura medida com setpoint.
3. Consultar valores recentes e históricos, mantendo dados atrasados no ponto temporal correto.
4. Indicar desconexão e desatualização sem apresentar dado antigo como leitura atual.
5. Persistir e reenviar telemetria pendente; tolerar reentrega sem duplicar registros; só confirmar após persistência central.
6. Enviar comandos de setpoint e liga/desliga para cada bomba simulada, com identificador, resposta e auditoria.
7. Fazer backup, restaurar e demonstrar a consistência do conjunto restaurado.
8. Executar localmente o roteiro de aceite com configurações de teste registradas e pendências explícitas.

### Posterior ao piloto

- Integração física e descoberta/validação de interfaces do equipamento.
- Agente embarcado, firmware, protocolo experimental e automação de rotinas.
- Validação científica de faixa, unidade, calibração, precisão e métricas derivadas.
- Alertas científicos, análises avançadas, alta disponibilidade, implantação remota e metas de produção.
- Escala além do cenário local de demonstração definido para o teste.

Itens posteriores não podem enfraquecer os requisitos P0 de identidade, ordenação temporal, idempotência, confirmação após persistência, separação entre leitura e comando, ou rastreabilidade. Não se deve executar automaticamente comando de bomba antigo após reconexão; comandos expirados ou de resultado desconhecido devem permanecer identificados como tal.

## Critérios e roteiro de demonstração

Executar o roteiro em ambiente local limpo ou documentar o estado inicial. Antes da demonstração, registrar os parâmetros do ensaio: número de posições/fontes simuladas, duração, cadência, tamanho/limite da fila local e versão/configuração do simulador. Esses valores caracterizam apenas o teste; não são metas de produção. Valores simulados podem ser arbitrários, desde que identificáveis e reproduzíveis.

| ID | Cenário e demonstração | Critério de aceite observável |
| --- | --- | --- |
| A1 — Fluxo normal | Iniciar os serviços locais e o simulador; produzir OD, pH e temperatura; abrir o painel e consultar o histórico. | Cada tipo aparece associado à origem correta, com horário de geração e recebimento. O histórico consultado no backend coincide com os eventos aceitos. Temperatura medida aparece separada do setpoint. |
| A2 — Histórico | Produzir uma sequência conhecida de eventos e consultar intervalo histórico e leitura mais recente. | Eventos aparecem uma única vez e em ordem temporal apropriada; consulta histórica não altera nem substitui indevidamente a leitura mais recente. |
| A3 — Desconexão | Interromper a conexão do simulador/produtor com o serviço central enquanto ele gera eventos. | A interface/sistema indica desconexão ou dado desatualizado; eventos não confirmados permanecem na fila durável. Não são apresentados como dados atuais. |
| A4 — Store and Forward | Restabelecer a conexão e deixar o simulador reenviar a fila; demonstrar a confirmação da aplicação após persistência. | Todos os eventos válidos retidos chegam ao histórico com horário original e identidade preservada. A fila só remove eventos após confirmação pós-commit; o atraso pendente pode ser observado. |
| A5 — Duplicatas | Reenviar um evento já persistido com o mesmo `event_id`, inclusive simulando perda da confirmação original. | O histórico contém uma única ocorrência lógica; a aplicação reconhece a duplicata e pode confirmá-la sem criar outro registro. |
| A6 — Dados atrasados | Injetar evento cujo horário de geração seja anterior ao da leitura mais recente. | O evento atrasado é preservado no histórico no seu horário de geração, recebe horário de recebimento, e não substitui o estado mais recente por chegada tardia. |
| A7 — Comandos | Enviar setpoint de temperatura e ligar/desligar cada bomba individualmente; inspecionar respostas e auditoria. | Cada pedido tem `command_id`, alvo, ação, autor disponível no piloto e resposta correlacionada do simulador. Comandos das três bombas são independentes. A interface distingue solicitado/aceito/rejeitado e resultado simulado; não declara execução física. Comando antigo não é executado automaticamente após reconexão. |
| A8 — Restauração | Gerar dados e metadados, realizar backup, restaurar em ambiente local de verificação e repetir consultas. | Após restauração, contagens e identificadores dos registros do conjunto de demonstração conferem com o inventário/consulta anterior; leitura recente e histórico continuam consultáveis e comandos/eventos mantêm referências. O procedimento e o resultado ficam registrados. |

**Resultado do aceite:** registrar cada cenário como aprovado, reprovado ou bloqueado, com evidência (saída/consulta/captura ou log), versão/configuração utilizada e desvio observado. Falha em qualquer critério P0 impede declarar o piloto aceito; abrir pendência com responsável e próximo passo.

## Responsabilidades e governança do aceite

- **Responsável pelo aceite:** **pendente de indicação pelo projeto/laboratório**. Não atribuído neste documento.
- **Executor da demonstração:** pendente de indicação.
- **Revisores do escopo e dos critérios:** pendentes de indicação.
- O responsável pelo aceite deve acompanhar ou revisar as evidências e registrar a decisão final (aprovado/reprovado), data e eventuais ressalvas.

## Pendências explícitas para revisão

1. Indicar nominalmente responsável pelo aceite, executor e revisores.
2. Aprovar a semântica mínima dos comandos: setpoint de temperatura e ações liga/desliga nas bombas 1, 2 e 3; parâmetros adicionais de bomba ficam fora até decisão explícita.
3. Fixar, antes da execução, número de fontes/posições simuladas, duração e cadência do teste, além do limite da fila. São parâmetros de demonstração, não objetivos de produção.
4. Definir o procedimento de backup/restauração e qual inventário/contagens serão usados como evidência, de acordo com a implementação local.
5. Definir onde serão guardadas evidências e o registro final do aceite.
6. Revisar este escopo e roteiro até **27/10/2026** para manter a entrega do piloto prevista para **27/11/2026**.

## Base de contexto

Este documento segue a fronteira e as decisões descritas em `VISAO_GERAL.md` do repositório `KachanChK/eVOLVER-CNPEM`: simulador externo, dados mockados, Mosquitto/MQTT, PostgreSQL + TimescaleDB, backend Python, interface web e Store and Forward. Essa visão trata mensagens e comandos como simulação nesta fase e não confirma integração física. O roteiro acima transforma as necessidades da etapa E1 · T01 em critérios observáveis; decisões ainda não fornecidas pelo projeto permanecem marcadas como pendentes.

