# Spec de implementação de alertas

**Escopo acordado em 24/11/2026.** O eVOLVER avisa quando uma leitura de temperatura, pH ou OD sai da faixa, quando deixa de receber leituras recentes ou quando falha um comando do grupo de bombas. Cada alerta identifica o experimento e o vial. O histórico fica na página **Alertas** e um card no canto superior direito avisa quando chega um alerta novo.

A central de testes é uma janela Python local que abre junto com o simulador. Cada botão altera temporariamente um comportamento do simulador. A ingestão detecta a condição pelo mesmo fluxo usado durante a operação normal e registra o alerta no PostgreSQL. [Arquitetura atual](arquitetura-atual.md) · [Simulador](../simulator/README.md)

## Faixas de alerta

A consulta ao PostgreSQL local agrupou as leituras de cinco experimentos em quatro vials. A coluna P5–P95 mostra o intervalo que contém os 90% centrais de cada série. A faixa padrão também considera o que o gerador pode produzir com a configuração padrão e os 12 vials ativos.

| Métrica | Leituras no banco | Mínimo–máximo no banco | P5–P95 | Faixa padrão de alerta | Valor do teste |
| --- | ---: | --- | --- | --- | --- |
| Temperatura | 9.150 | 36,40–37,68 °C | 36,48–37,52 °C | 36,0 a 39,0 °C | 40,0 °C |
| pH | 9.138 | 6,830–7,181 | 6,848–7,152 | 6,80 a 7,50 | 7,70 |
| OD | 9.106 | 0,10–0,80 | 0,101–0,558 | 0,10 a 0,80 | 0,85 |

Com 12 vials, os deslocamentos por posição podem levar a temperatura a 38,7 °C e o pH a 7,39. A OD do gerador pode atingir 0,10 e 0,80 em operação normal, inclusive com bombas pausadas ou aguardando confirmação. As faixas propostas cobrem esses extremos. Uma execução isolada com três sementes e 10.800 amostras por métrica confirmou que todas as leituras normais ficaram dentro das faixas. [Configuração do simulador](../simulator/src/evolver_simulator/config.py) · [Gerador de telemetria](../simulator/src/evolver_simulator/telemetry.py)

As faixas valem para o protótipo simulado. Os limites mínimo e máximo são inclusivos e ficam na configuração do backend, com valores finitos e mínimo menor que o máximo. Todos os experimentos usam esses padrões. Os limites de OD cadastrados em cada experimento continuam regendo a histerese do grupo de bombas. [Controle de OD](../backend/src/evolver/ingestion/control.py)

## Quando emitir e encerrar um alerta

### Leituras discrepantes

- A primeira leitura válida estritamente abaixo ou acima do limite abre um alerta da métrica na alocação ativa. O alerta registra a leitura, a unidade quando houver, os limites aplicados e o horário da emissão.
- Avaliar apenas eventos novos de telemetria ao vivo, vinculados ao UUID da alocação, gerados há menos de 15 segundos e com horário de geração mais recente que a última leitura ao vivo aceita da métrica. Leituras recuperadas pela fila vão para o histórico. Duplicatas mantêm o desfecho da gravação original.
- Leituras discrepantes consecutivas mantêm a ocorrência aberta. A primeira leitura ao vivo dentro da faixa encerra a ocorrência e permite um novo alerta se houver outra discrepância. Um frasco reutilizado começa a ser avaliado com o UUID do novo experimento. [Ingestão de telemetria](../backend/src/evolver/ingestion/telemetry.py)

### Falha no recebimento de dados

- A ingestão verifica a cada segundo o tempo desde a última leitura nova de cada métrica em cada alocação ativa. Depois de **15 segundos** sem uma leitura recente, abre um alerta para o vial. A contagem usa o horário de geração da última leitura ao vivo persistida. Antes da primeira leitura, conta a partir do início do monitoramento da alocação.
- Cada vial tem uma única ocorrência de falta de dados em aberto. O alerta indica as métricas em atraso. Se outras métricas pararem durante a mesma ocorrência, atualizar a lista no registro existente. Se as três pararem, a mensagem indica **Sem dados do vial**.
- Encerrar a ocorrência quando as três métricas voltarem a ter leituras recentes. Reenvios históricos preenchem o histórico e preservam os horários originais. Alocações encerradas saem do monitoramento.
- Na implantação, iniciar a contagem para alocações já ativas a partir da primeira verificação após a migração. Depois disso, persistir a contagem e as ocorrências para retomá-las após reinícios. A verificação roda mesmo durante uma desconexão do MQTT. Se o PostgreSQL estiver indisponível, a ingestão volta a verificar e registrar as condições quando recuperar a conexão com o banco. [Ciclo da ingestão](../backend/src/evolver/ingestion/__main__.py) · [Recuperação de telemetria](spec-store-and-forward.md)

### Falha nas bombas

- **Falha no grupo de bombas** quando um comando válido recebe o resultado `failed`. O registro inclui a ação, o motivo informado e o ID do comando.
- **Comando das bombas sem confirmação** quando um comando enviado expira sem confirmação de execução. Reaproveitar a validade atual de **10 segundos**. Usar a evidência de publicação ou de recebimento do comando, já que `sent_at` registra a reserva do envio. Um resultado `rejected` com motivo `expired` também informa que a ação ficou sem confirmação. Cancelamentos intencionais, falhas de validação do contrato e reconciliações normais ficam no histórico de comandos.
- Manter uma ocorrência de falha por alocação até confirmar que o grupo voltou a responder. Correlacionar resultados pelo `command_id` e tratar reentregas como o mesmo resultado. Para recuperar o estado desconhecido, reutilizar a reconciliação com um novo `turn_off`, com intervalo de pelo menos **10 segundos** entre tentativas automáticas por alocação e uma tentativa pendente por vez. Após confirmar o desligamento, retomar as decisões normais pela OD se a automação estiver habilitada. Preservar as regras de pausa e o fluxo de confirmação no encerramento. [Controle de bombas](../backend/src/evolver/ingestion/control.py) · [Resultados de comandos MQTT](../packages/contracts/src/evolver_contracts/models.py)

## Histórico e interface

- Adicionar **Alertas** à navegação com uma bolinha vermelha e indicação acessível quando houver pelo menos um alerta visível e não lido. O histórico é global no protótipo local e persiste após recarregar a página ou reiniciar a aplicação.
- Na rota `/alertas`, listar todos os alertas visíveis, ordenados pelo horário de emissão do mais recente ao mais antigo, com ID como desempate. Cada item exibe motivo, horário, nome do experimento e vial, mais o valor e a faixa, as métricas em atraso ou a situação do comando, conforme o tipo.
- Abrir a página marca como lidos os alertas existentes na consulta inicial. Alertas que chegarem com a página aberta entram na lista e são marcados como lidos ao aparecer. A bolinha reflete o estado confirmado pelo backend.
- O botão **Limpar alertas** pede confirmação e arquiva os alertas que estavam na lista ao confirmar. Os registros continuam no banco e os que chegarem depois aparecem normalmente. Limpar a lista preserva o estado da ocorrência em andamento até sua recuperação, evitando outro alerta da mesma falha.
- Em qualquer página, mostrar o card no canto superior direito em **até 2 segundos** após o registro do alerta, com a aplicação e a conexão local funcionando normalmente. O card exibe o motivo, horário, experimento, vial e os dados específicos da ocorrência. Fica por **5 segundos** e pode ser fechado antes. Quando alertas chegam juntos, empilhar os cards e manter um tempo de exibição próprio para cada um. Na abertura ou recarga da aplicação, alertas anteriores ficam disponíveis na lista e na bolinha.

## Persistência e API

- Adicionar uma migração Alembic para registrar o alerta e o acompanhamento da última leitura ao vivo por alocação e métrica. Guardar no alerta o ID, o tipo, a alocação, o experimento, o nome exibido, o vial, o horário de emissão, os dados do motivo e os horários de leitura, arquivamento e encerramento da ocorrência. O horário de encerramento da ocorrência é independente dos horários de leitura e arquivamento.
- Atualizar os alertas de telemetria e de bombas na transação que grava o evento correspondente. Usar chave de ocorrência aberta por alocação e tipo para evitar duplicatas se a ingestão reprocessar uma mensagem ou a verificação ocorrer em paralelo. Preservar os estados no banco e serializar a emissão para que o cursor da API siga a ordem em que os alertas se tornam visíveis.
- `GET /api/alerts` devolve a lista paginada por horário de emissão e ID, o indicador global de não lidos e os alertas novos após o cursor de emissão informado. O Vue consulta os alertas a cada **1 segundo**, aproveitando a API HTTP com uma consulta independente dos gráficos. Depois de uma interrupção, a consulta retoma do último cursor confirmado.
- `POST /api/alerts/read` marca como lidos os alertas visíveis até o cursor informado. `POST /api/alerts/clear` arquiva os alertas visíveis até o cursor que o usuário confirmou. As duas operações podem ser repetidas com o mesmo cursor e preservam os alertas emitidos depois dele. [API atual](../backend/src/evolver/api/main.py) · [Navegação Vue](../frontend/src/main.js)

## Central de testes do simulador

Adicionar a janela **Central de testes** dentro de `simulator/`, com Tkinter. Na execução interativa, `scripts/simular.ps1` abre a janela junto com a coleta. A CLI também oferece um modo sem janela para automação e execuções curtas. Fechar a janela deixa o simulador em execução. Encerrar o simulador fecha a janela.

A janela lista as alocações ativas para escolher o experimento e o vial. Cada teste vale para a alocação selecionada e termina sozinho. Mostrar o cenário atual e seu andamento, bloquear cliques repetidos enquanto estiver em execução e informar quando faltarem dados ou condições para iniciá-lo. Se a alocação terminar ou mudar, encerrar o teste e liberar a seleção.

| Botão | Comportamento do simulador | Duração |
| --- | --- | --- |
| **Pico de temperatura** | Substitui a próxima leitura de temperatura do vial por **40,0 °C**. | Uma leitura. A geração normal volta na rodada seguinte. |
| **pH fora da faixa** | Substitui a próxima leitura de pH por **7,70** no perfil padrão. | Uma leitura. |
| **OD fora da faixa** | Publica uma leitura de **0,85** no perfil padrão. A dinâmica interna de OD segue a geração normal. | Uma leitura. |
| **Interromper envio de dados** | Suspende a publicação das novas leituras do vial. Mantém a coleta, a fila e as demais alocações operando. Ao final, prioriza as leituras novas e reenvia as que ficaram na fila como históricas. | **20 segundos**, ultrapassando o prazo padrão de 15 segundos. |
| **Falha nas bombas** | Responde com `failed` e motivo `simulation_error` a comandos válidos do grupo do vial, preservando o estado aplicado no simulador. Se for necessário provocar um comando, emite uma leitura no limite de controle de OD apropriado para o estado confirmado. O controlador existente decide e emite o comando. | **60 segundos**. Ao final, o simulador volta a processar comandos normalmente. |

Para o teste de bombas, usar um experimento ativo com automação habilitada, grupo em estado conhecido e limites de OD cadastrados. O valor para exercitar a automação fica dentro da faixa de alerta de OD. A tela informa quando o teste aguarda o comando e quando a falha foi aplicada. O simulador guarda e reapresenta o mesmo resultado se o MQTT reentregar o comando durante ou após o teste. [Comandos do simulador](../simulator/src/evolver_simulator/mqtt.py) · [Ciclo da coleta e do envio](../simulator/src/evolver_simulator/runner.py)

## Critérios de aceite

| Verificação | Resultado esperado |
| --- | --- |
| Gerar leituras normais com os 12 vials ativos e executar ciclos de OD | As faixas inclusivas cobrem os valores normais e os cruzamentos dos limites de controle. |
| Acionar os testes de temperatura, pH e OD | Cada botão gera uma leitura discrepante de fato, um alerta para o experimento e vial selecionados e um card. A rodada seguinte volta à geração normal. |
| Manter uma leitura discrepante por várias rodadas, normalizar e repetir | Sai um alerta na primeira leitura discrepante e outro ao iniciar a segunda ocorrência. Reentregar a mesma leitura preserva o primeiro registro. |
| Tirar uma métrica do ar, depois suspender as demais no mesmo vial | Após 15 segundos, o alerta identifica as métricas em atraso. Permanece um registro por vial durante a interrupção. O reenvio do histórico mantém os registros anteriores e as leituras novas encerram a ocorrência. |
| Acionar **Falha nas bombas** e testar também a expiração sem confirmação | Um comando MQTT real do fluxo de controle produz o alerta com o motivo correspondente. Durante os 60 segundos de falha, reentregas e tentativas de recuperação mantêm uma ocorrência. Após o cenário, um novo desligamento confirmado restabelece o estado conhecido. |
| Navegar pela aplicação e receber alertas | O card aparece em até 2 segundos e permanece por 5 segundos. Recarregar preserva o indicador de não lidos. Abrir **Alertas** apaga o indicador após a confirmação e mantém a lista em ordem de emissão. |
| Limpar a lista e emitir outro alerta enquanto a limpeza é confirmada | A limpeza arquiva a seleção confirmada. O alerta posterior permanece visível. Uma falha ainda em andamento mantém sua única ocorrência. |
| Reiniciar a aplicação no meio de uma interrupção e reutilizar um vial em outro experimento | A ocorrência persiste após o reinício. Uma alocação nova começa com seu próprio estado e o alerta anterior continua ligado ao experimento original. |
| Abrir a central pelo script e executar cada cenário | A janela abre junto com o simulador, mostra o andamento e cada teste termina sozinho. Fechar a janela mantém a coleta em andamento. |
