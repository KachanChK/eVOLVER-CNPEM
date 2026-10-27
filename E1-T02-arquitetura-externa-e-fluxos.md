# E1 · T02 — Arquitetura externa e fluxos

**Etapa:** 1 — Planejamento  
**Prioridade:** P0  
**Período:** 27–29/10/2026  
**Dependências:** E1 · T01 (#1) e decisões técnicas  
**Status:** proposta de arquitetura para revisão  
**Fronteira:** software e serviços executados fora do equipamento; piloto inteiramente local, com simulador e comandos sem efeito físico.

## Objetivo

Documentar uma arquitetura executável em uma única máquina e explicitar as fronteiras entre produção de telemetria simulada, transporte, persistência central, interface e operação simulada de comandos. Os fluxos preservam identidade, horários e rastreabilidade diante de desconexões e reentregas.

## Diagrama de contexto

Todos os componentes abaixo rodam na mesma máquina no piloto. O simulador Python representa a origem e o destino dos dados/comandos nesta fase; não representa o firmware nem um serviço executado dentro do eVOLVER.

![Diagrama de contexto da arquitetura externa](https://github.com/user-attachments/assets/bcc3deb3-2922-4a41-b377-49eb698b84be)


A atualização ao vivo da interface usa SSE (definido no T03): a ingestão avisa a API por `LISTEN/NOTIFY` do PostgreSQL, entregue somente após o commit, e a API envia ao navegador o dado lido do banco. Após reconexão, API e navegador recarregam o estado pelo banco/API. A API continua sendo o caminho de consulta e autoridade para o estado persistido; o navegador não acessa diretamente o banco.

## Diagrama de componentes e fronteiras

![Diagrama de componentes e fronteiras de falha](https://github.com/user-attachments/assets/04648556-a70c-4bd2-8db6-0400f4d6e677)



**Fronteiras de falha:** a fila protege telemetria ainda não confirmada no lado produtor; o banco é a persistência central; o broker é transporte e não prova gravação no banco; a API separa o navegador das regras de acesso e do banco. A implantação local não oferece, por si só, alta disponibilidade ou proteção contra perda física da máquina.

## Responsabilidades dos componentes

| Componente | Responsabilidade no piloto | Não significa |
| --- | --- | --- |
| Simulador Python | Gerar OD, pH e temperatura medida com IDs, sequência e horário de geração; persistir eventos na fila antes de publicar; receber setpoint e comandos ligar/desligar das bombas 1, 2 e 3; responder com o mesmo command_id e resultado simulado. | Sensor calibrado, atuador real, volume bombeado ou execução física. |
| Fila local durável | Manter eventos até confirmação da aplicação; preservar event_id, sequência e horário original; recuperar pendências após reinício; expor quantidade/idade pendente e erro de publicação. | Substituto de backup ou garantia contra perda do disco/host. |
| Mosquitto / MQTT | Transportar mensagens entre produtores e consumidores locais, com tópicos separados para telemetria, ACK, comandos e respostas. | Banco de dados, confirmação de commit, execução de comando ou interface comprovada do hardware eVOLVER. |
| Ingestão Python | Validar esquema, origem, IDs e horários; registrar horário de recebimento; deduplicar; transacionar eventos; emitir ACK de aplicação somente após commit; receber resultados simulados de comandos e persistir eventos correlacionados. | Autoridade para inferir efeito científico ou físico. |
| PostgreSQL + TimescaleDB | Guardar metadados, medições, eventos de conexão, comandos e auditoria; garantir unicidade lógica por event_id (ou chave idempotente aprovada); servir como fonte do histórico persistido. | Prova de que um comando alterou equipamento físico. |
| API Python | Fornecer consultas e estado consistente, impor autorização para ações, validar prazo/alvo de comandos, registrar autor e publicar comandos; expor mudanças persistidas à interface. | Acesso direto do navegador ao MQTT ou ao banco. |
| Interface web | Mostrar estado recente e histórico, horários de geração/recebimento, frescor/conexão e fila pendente; permitir ações simuladas e apresentar os estados do comando sem confundi-los. | Fonte primária dos dados ou confirmação independente de execução física. |

## Contratos e distinções de estado

### Telemetria

Cada evento de telemetria inclui no mínimo: versão do esquema, event_id, equipment_id lógico do simulador, posição/frasco e, quando aplicável, experiment_run_id; tipo od, ph ou temperature e valor numérico; generated_at e sequência/ordem do produtor. A ingestão acrescenta received_at. O event_id permanece estável em toda tentativa de reenvio. O banco impede duas gravações lógicas para o mesmo ID.

Um horário antigo não torna o evento inválido: ele entra no histórico pelo horário de geração, mas não substitui automaticamente o valor mais recente já conhecido.

### Comandos

Todo comando contém command_id, tipo/alvo, ação/valor, instante de criação, validade, autor e correlação com a execução experimental quando aplicável. No piloto, os alvos são setpoint de temperatura e bombas 1, 2 e 3 com ação ligar/desligar.

Apresentar estados separados e só avançar quando houver evidência correspondente:

1. **Solicitado:** a API registrou a intenção e seu autor.
2. **Aceito ou rejeitado:** validação local do comando e do prazo.
3. **Enviado:** publicação ao broker concluída; isto só comprova envio ao transporte.
4. **Recebido:** o simulador confirmou recebimento correlacionado.
5. **Executado no simulador / falhou / resultado desconhecido:** resposta do simulador registrada. “Executado” aqui significa exclusivamente operação simulada.

Temperatura **medida** é telemetria; temperatura **desejada** é setpoint. Valores publicados, recebidos e executados são estados diferentes. Para bombas, não inferir estado físico, vazão nem volume real.

## Fluxos principais

### 1. Telemetria normal e confirmação pós-commit

1. O simulador cria evento com event_id, sequência e generated_at.
2. Grava o evento na fila durável antes de tentar publicar.
3. Publica telemetria no tópico MQTT correspondente.
4. A ingestão valida esquema e origem, inicia transação e insere o evento (ou detecta duplicata).
5. Após commit bem-sucedido, a ingestão publica ACK de aplicação contendo o event_id e resultado persistido/duplicado.
6. O simulador recebe o ACK e marca o evento como concluído/removível da fila.
7. A API consulta o banco e atualiza a interface com valor, horário de geração, horário de recebimento e frescor.

ACK de QoS MQTT confirma uma etapa do transporte. Ele não substitui o ACK de aplicação emitido depois da persistência central.

### 2. Desconexão, Store and Forward e reinício

1. Se broker/ingestão/banco estiver indisponível, a publicação falha ou não recebe ACK de aplicação.
2. O evento continua na fila local, sem trocar identidade ou horário.
3. A tela indica desconexão, idade da última leitura e/ou pendências; dados anteriores não são rotulados como atuais.
4. Após reconexão, o produtor reenvia eventos pendentes segundo a política configurada.
5. Se o evento já tiver sido persistido antes da perda do ACK, a ingestão o reconhece como duplicata, não cria novo registro e pode emitir novamente o ACK.
6. Depois do ACK pós-commit, o produtor conclui o item da fila.
7. Se a máquina reiniciar, o produtor recupera a fila durável; ingestão e API recuperam estado do banco.

Capacidade da fila, política quando cheia, intervalo de repetição e mecanismo de atualização da interface são configurações a decidir e registrar. Se a fila atingir o limite, o sistema deve sinalizar explicitamente e não apagar eventos antigos silenciosamente.

### 3. Mensagens inválidas e quarentena

Evento malformado ou incompatível com o esquema recebe rejeição explícita e motivo registrado. Deve ser isolado em quarentena ou encaminhado para tratamento manual, para não bloquear indefinidamente os demais eventos. Evento inválido não recebe confirmação de persistência válida e não deve ser descartado silenciosamente.

### 4. Dados atrasados e fora de ordem

A ingestão conserva generated_at, received_at e a identidade do produtor. Armazena eventos atrasados no histórico sem reescrever o passado nem regredir o indicador de leitura mais recente. Ordenação de série usa o horário de geração; investigação de atraso considera também horário de recebimento e sequência.

### 5. Comandos e respostas simuladas

1. Usuário solicita ação pela interface.
2. API autoriza, valida alvo/ação e prazo e registra command_id, autor e estado **solicitado**.
3. API publica comando não retido, com validade limitada, para o simulador por MQTT.
4. O estado **enviado** é registrado separadamente do recebimento.
5. Simulador valida validade e identidade, executa apenas a ação em seu estado simulado e devolve resposta com o mesmo command_id.
6. Ingestão valida a correlação e grava a resposta/evento; API mostra estado final simulado.
7. Se a resposta não chegar, mostrar **resultado desconhecido**. Não repetir automaticamente comando antigo de bomba após reconexão. Uma nova tentativa exige política explícita e não deve esconder a incerteza do resultado anterior.

Comandos expirados durante desconexão são recusados pelo simulador e permanecem auditáveis como expirados/rejeitados. O piloto não usa comandos MQTT retidos para atuadores.

## Decisões registradas e decisões pendentes

### Base adotada para o desenho

- Uma máquina local, com os componentes externos do piloto.
- Simulador Python e valores mockados como origem/destino de telemetria e comandos.
- Mosquitto/MQTT para transporte no protótipo simulado.
- Ingestão e API em Python; PostgreSQL + TimescaleDB como persistência central; interface web.
- Fila durável no produtor, ACK de aplicação após commit, deduplicação por identidade estável e histórico que aceita dados atrasados.
- Separação entre temperatura medida e setpoint; entre publicar, receber e executar comando simulado.

### Decidido no T03

- FastAPI, `aiomqtt`/paho-mqtt, Vue 3 + Vite e Chart.js.
- Atualização ao vivo por SSE; aviso ingestão → API por `LISTEN/NOTIFY`, com recarga do estado pelo banco após reconexão.
- Unicidade por `event_id` em tabela de IDs processados, gravada na mesma transação da medição.

### Pendente de decisão técnica/revisão

- Convenção de tópicos, QoS, autenticação local e ACLs do broker.
- Esquema/versionamento final e demais tabelas/índices.
- Formato e capacidade da fila, política para disco cheio, retentativas e quarentena.
- Validade dos comandos, timeouts, estados persistidos e política manual para resultado desconhecido.
- Backup, destino seguro, frequência e procedimento de restauração.
- Parâmetros do ensaio de demonstração, conforme T01; são parâmetros de teste e não metas de produção.

Essas pendências não alteram a fronteira do piloto nem autorizam comportamento físico. Decisões que possam enfraquecer durabilidade, idempotência, rastreabilidade ou distinção de estados precisam ser revistas contra os critérios P0 do T01 antes de implementação.

## Limite em relação ao hardware físico

O uso de MQTT/Mosquitto está definido para conectar o simulador externo aos serviços locais do piloto. **Não foi comprovado que o hardware físico eVOLVER ofereça MQTT**, nem que possua uma interface adequada para esses fluxos. O desenho não conecta nem presume protocolo físico. Uma integração futura exige descoberta e validação separadas; se necessário, um adaptador externo deverá ser definido sem introduzir agente embarcado ou disputar a autoridade de controle existente.



