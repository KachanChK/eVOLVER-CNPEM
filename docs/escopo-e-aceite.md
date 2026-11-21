# E1 · T01 — Escopo e critérios de aceite do piloto

**Etapa:** 1 — Planejamento  
**Prioridade:** P0  
**Período da atividade:** 26–27/10/2026  
**Entrega prevista do piloto:** 27/11/2026  
**Dependências:** nenhuma  
**Status deste documento:** proposta para revisão; pendências listadas ao final.

## Objetivo

Definir exatamente o que será mostrado no piloto local, usando dados e comandos simulados. Para aceitar a entrega, a equipe deverá conseguir iniciar os serviços, ver as leituras na tela e no histórico, interromper e restabelecer a conexão sem perder ou duplicar dados, enviar comandos ao simulador e restaurar um backup. Cada resultado precisa ter uma evidência consultável. O piloto não testa precisão científica nem equipamento físico.

## Escopo do piloto

### Incluído

- Execução na máquina local dos serviços necessários à demonstração: simulador, transporte de mensagens, serviço que recebe os dados, banco, API e interface, conforme a arquitetura definida para a implementação.
- Leituras simuladas de **OD**, **pH** e **temperatura medida**, identificadas por origem e pelos horários em que foram geradas e recebidas.
- **Setpoint de temperatura** (valor desejado) enviado como comando ao simulador e exibido separadamente da temperatura medida.
- Comandos independentes de **ligar e desligar as bombas 1, 2 e 3**, sem afirmar leitura de estado físico, vazão ou volume dispensado.
- Consulta da última leitura e das leituras anteriores, com aviso quando a conexão cair ou o dado exibido estiver antigo.
- Fila gravada localmente no simulador para guardar leituras ainda não confirmadas e reenviá-las após a reconexão (*Store and Forward*). O simulador só remove um item depois que a aplicação confirma que ele foi gravado no banco; reenviar o mesmo `event_id` não duplica o registro.
- Registro de cada comando, da solicitação à resposta e ao resultado simulado, usando o mesmo `command_id` para ligar essas etapas.
- Backup dos dados e metadados usados na demonstração, seguido de restauração e comparação com o que havia antes.

### Fora do escopo

- Conexão ou controle de hardware real, sensores, atuadores, placas ou microcontroladores.
- Agente embarcado, firmware, alterações no equipamento e protocolos experimentais automáticos.
- Garantia de precisão, calibração ou interpretação científica dos valores simulados.
- Execução automática de turbidostato, quimiostato ou outras rotinas experimentais.
- Alegação de que um comando publicado foi executado fisicamente. Resultado significa apenas resposta do simulador.
- Metas de quantidade de equipamentos, volume de dados ou tempo de resposta para produção. O tamanho e o ritmo da demonstração serão definidos e anotados antes do teste.

## Classes de prioridade

### P0 — necessário para o aceite do piloto

1. Mostrar de qual fonte veio cada leitura e guardar tanto o horário de geração quanto o de recebimento.
2. Gravar OD, pH e temperatura medida; mostrar o setpoint de temperatura como comando separado.
3. Consultar a última leitura e o histórico; colocar leituras atrasadas no horário em que foram geradas.
4. Avisar quando a conexão cair ou a última leitura envelhecer, sem apresentá-la como atual.
5. Guardar leituras pendentes em fila, reenviá-las sem duplicar registros e confirmar somente depois da gravação no banco.
6. Enviar setpoint e ligar/desligar cada bomba simulada; guardar identificador, resposta e histórico de cada comando.
7. Fazer backup, restaurar e conferir os dados e vínculos recuperados.
8. Executar os testes locais da tabela abaixo, guardar evidências e anotar configurações e pendências.

### Posterior ao piloto

- Integração física e descoberta/validação de interfaces do equipamento.
- Agente embarcado, firmware, protocolo experimental e automação de rotinas.
- Validação científica de faixa, unidade, calibração, precisão e métricas derivadas.
- Alertas científicos, análises avançadas, alta disponibilidade, implantação remota e metas de produção.
- Escala além do cenário local de demonstração definido para o teste.

Itens posteriores devem manter as garantias P0: cada evento tem identidade estável, entra no histórico pelo horário de geração, não é gravado duas vezes e só sai da fila após confirmação da gravação; leituras e comandos continuam separados e rastreáveis. Depois de uma reconexão, um comando antigo de bomba não pode ser executado automaticamente. Comandos expirados ou sem resposta devem aparecer com esse estado.

## Critérios e roteiro de demonstração

Executar o roteiro em ambiente local limpo ou anotar quais dados já existiam. Antes de começar, registrar número de fontes/posições simuladas, duração, intervalo entre leituras, limite da fila local, versão/configuração do simulador e como identificar os eventos deste teste. Definir também após quanto tempo sem uma nova leitura a tela deve sinalizar dado antigo. Esses números servem apenas para reproduzir a demonstração, não são metas de produção. Usar valores simulados conhecidos, que possam ser conferidos depois.

| ID | Cenário e demonstração | Critério de aceite observável |
| --- | --- | --- |
| A1 — Fluxo normal | Iniciar os serviços e gerar uma amostra conhecida de OD, pH e temperatura para uma fonte identificada; abrir o painel e consultar o histórico pela API ou banco. | As três leituras aparecem na fonte correta, com horários de geração e recebimento. Os `event_id` vistos na consulta correspondem aos eventos aceitos. Temperatura medida e setpoint aparecem em campos distintos. Guardar captura da tela e resultado da consulta. |
| A2 — Histórico | Gerar uma sequência com IDs e horários conhecidos; consultar um intervalo que inclua a sequência e depois pedir a última leitura. | Cada ID aparece uma vez, no horário em que o evento foi gerado. A última leitura continua sendo a de geração mais recente para aquela fonte e tipo, mesmo após consultar o histórico. Guardar as duas consultas. |
| A3 — Desconexão | Cortar a comunicação do simulador com o serviço central, continuar gerando leituras e consultar a tela e a fila após o tempo de desatualização definido antes do teste. | A tela indica desconexão ou mostra a idade da última leitura; não a apresenta como atual. Os IDs gerados durante a falha permanecem na fila gravada localmente. Guardar captura da tela e lista/contagem da fila. |
| A4 — Store and Forward | Restabelecer a comunicação; comparar os IDs da fila antes e depois do reenvio, o histórico no banco e os registros de confirmação da aplicação. | Cada evento válido pendente aparece no histórico com o mesmo `event_id` e horário de geração; o horário de recebimento mostra a chegada posterior. O item só sai da fila após a confirmação emitida depois da gravação no banco. Registrar fila, consulta e confirmação para os mesmos IDs. |
| A5 — Duplicatas | Reenviar um `event_id` já gravado, inclusive em um teste no qual a confirmação anterior não chega ao simulador. | A consulta ao banco retorna um único registro lógico para esse ID. A aplicação identifica a repetição e pode confirmar o registro existente; guardar consulta e registro da confirmação. |
| A6 — Dados atrasados | Depois de gravar uma leitura, enviar outra da mesma fonte e tipo com horário de geração anterior. | A leitura atrasada entra no histórico com seu horário de geração e um horário de recebimento posterior. A consulta da última leitura continua mostrando o evento gerado mais recentemente. Guardar as duas consultas. |
| A7 — Comandos | Enviar um setpoint e comandos de ligar e desligar para cada uma das bombas 1, 2 e 3; consultar o histórico de comandos e as respostas. Testar também um comando de bomba que expire durante uma desconexão. | Cada pedido registra `command_id`, alvo, ação e autor disponível no piloto; a resposta do simulador usa o mesmo ID. É possível conferir a ação de cada bomba separadamente. A tela diferencia pedido, aceitação/rejeição, envio, recebimento e resultado simulado ou desconhecido. O comando expirado não é executado após reconexão. Guardar pedidos, respostas e consulta de auditoria. |
| A8 — Restauração | Antes do backup, anotar a contagem e os IDs das leituras, comandos e metadados usados no teste. Fazer o backup, restaurar em outro ambiente local de verificação e repetir as mesmas consultas. | Contagens e IDs conferem com o inventário anterior; última leitura e histórico continuam acessíveis, e comandos e eventos mantêm seus vínculos com os metadados. Guardar comandos/procedimento usados, inventário anterior e consultas após a restauração. |

**Resultado do aceite:** o executor da demonstração registra, para cada ID de A1 a A8, aprovado, reprovado ou bloqueado; anexa a evidência indicada, versão/configuração usada e o que divergiu do esperado. Se um requisito P0 falhar, o piloto não é aceito: registrar a pendência e o próximo passo. Um cenário bloqueado também precisa da causa registrada e de nova execução antes da decisão final. A decisão final cabe ao responsável pelo aceite (ver abaixo).

## Responsabilidades do aceite

- **Responsável pela decisão de aceite:** pendente de indicação pelo projeto/laboratório. Acompanha ou revisa as evidências e registra a decisão final (aceito/não aceito), a data e eventuais ressalvas.
- **Executor da demonstração:** pendente de indicação. Prepara o ambiente, executa A1–A8 e reúne as evidências.
- **Revisores do escopo e dos critérios:** pendentes de indicação.

## Pendências explícitas para revisão

1. Indicar nominalmente o responsável pela decisão de aceite, o executor da demonstração e os revisores.
2. Aprovar a semântica mínima dos comandos: setpoint de temperatura e ações liga/desliga nas bombas 1, 2 e 3; parâmetros adicionais de bomba ficam fora até decisão explícita.
3. Fixar, antes da execução, número de fontes/posições simuladas, duração e cadência do teste, além do limite da fila. São parâmetros de demonstração, não objetivos de produção.
4. Definir o procedimento de backup/restauração, o local de verificação e qual inventário/contagens serão usados como evidência, de acordo com a implementação local.
5. Definir onde serão guardadas evidências e o registro final do aceite; estabelecer o tempo após o qual uma leitura será marcada como antiga.
6. Revisar este escopo e roteiro até **27/10/2026**.

