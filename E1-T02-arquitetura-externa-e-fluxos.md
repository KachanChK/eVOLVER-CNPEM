# E1 · T02 — Arquitetura externa e fluxos

**Etapa:** 1 — Planejamento  
**Prioridade:** P0  
**Período:** 27–29/10/2026  
**Dependências:** E1 · T01 (#1) e decisões técnicas  
**Status:** desenho documentado; decisões de implementação e testes do piloto pendentes

**Fronteira:** software e serviços executados fora do equipamento; piloto inteiramente local, com simulador e comandos sem efeito físico.

## Objetivo

Registrar o desenho exigido pela [issue #2](https://github.com/KachanChK/eVOLVER-CNPEM/issues/2): componentes em uma máquina, responsabilidades, fronteiras, falhas e recuperação. Separar telemetria simulada, confirmação após gravação, comandos e respostas. Este documento descreve o comportamento esperado; a implementação e os resultados dos testes serão comprovados pelo roteiro de [escopo e aceite](escopo-e-aceite.md).

## Diagrama de contexto

Todos os componentes abaixo rodam na mesma máquina no piloto. O simulador Python representa a origem e o destino dos dados/comandos nesta fase; não representa o firmware nem um serviço executado dentro do eVOLVER.

```mermaid
flowchart LR
    user["Pessoa usuária"] --> web["Interface web"]
    web -->|"HTTP: consultas e comandos"| api["API Python"]
    api -->|"SSE: atualizações"| web
    api <-->|"consultas e registros"| db[("PostgreSQL + TimescaleDB")]
    sim["Simulador Python + fila SQLite"] <-->|"mensagens MQTT"| mqtt["Mosquitto"]
    api -->|"comandos"| mqtt
    mqtt -->|"telemetria e respostas"| ingestion["Ingestão Python"]
    ingestion -->|"medições e eventos"| db
    ingestion -->|"ACK de aplicação"| mqtt
```

**Leitura do diagrama:** MQTT (*Message Queuing Telemetry Transport*) é o protocolo de mensagens; Mosquitto é o *broker* (servidor que as encaminha). SQLite guarda a fila em arquivo local; TimescaleDB acrescenta suporte a séries temporais ao PostgreSQL. ACK é a confirmação da aplicação de uma leitura. O banco é a fonte do estado persistido. O navegador não acessa o banco nem o broker diretamente. As setas mostram o caminho previsto, não execução comprovada.

A atualização ao vivo usa SSE (*Server-Sent Events*, envio da API ao navegador), conforme o [T03](E1-T03-stack-e-desenvolvimento-local.md). A ingestão emite `NOTIFY` na transação de gravação; o PostgreSQL só entrega o aviso após o *commit* (confirmação da transação). A API recebe o aviso por `LISTEN`, lê o dado no banco e o envia por SSE. Como avisos perdidos não são recuperados por `LISTEN/NOTIFY`, a API relê o banco ao reconectar, e o navegador recarrega o estado pela API ao restabelecer o SSE.

## Diagrama de componentes e fronteiras

Os caminhos abaixo separam leitura de comando. A fila durável protege **leituras** ainda não confirmadas; comandos têm validade própria e não são reenviados automaticamente após desconexão.

**Telemetria, gravação e confirmação**

```mermaid
sequenceDiagram
    autonumber
    participant Sim as Simulador
    participant Fila as Fila SQLite
    participant MQTT as Mosquitto
    participant Ing as Ingestão
    participant BD as PostgreSQL
    Sim->>Fila: Grava leitura
    Sim->>MQTT: Publica leitura da fila
    MQTT->>Ing: Entrega leitura
    Ing->>BD: Grava ID e medição
    BD-->>Ing: Commit confirmado
    Ing->>MQTT: ACK de aplicação
    MQTT->>Sim: ACK do event_id
    Sim->>Fila: Conclui item
```

**Comando e resposta simulada**

```mermaid
sequenceDiagram
    autonumber
    participant Web as Interface
    participant API as API
    participant BD as PostgreSQL
    participant MQTT as Mosquitto
    participant Sim as Simulador
    participant Ing as Ingestão
    Web->>API: Solicita ação
    API->>BD: Registra command_id e autor
    API->>MQTT: Publica comando aceito
    API->>BD: Registra envio
    MQTT->>Sim: Entrega comando com validade
    Sim->>MQTT: Confirma recebimento
    Sim->>MQTT: Responde com command_id
    MQTT->>Ing: Entrega confirmação e resposta
    Ing->>BD: Grava recebimento e resultado
    API->>BD: Consulta estado persistido
    API-->>Web: Exibe estado via consulta ou SSE
```

**Fronteiras de falha:** a fila SQLite mantém leituras pendentes se o broker ou o serviço central ficar indisponível. O broker transporta mensagens, mas sua confirmação MQTT não prova gravação no banco. O banco guarda histórico e auditoria; a API controla o acesso do navegador. Rodar tudo em uma máquina não oferece alta disponibilidade nem protege contra perda física do host. Backup e restauração são requisitos do piloto definidos no T01, com procedimento ainda pendente.

## Responsabilidades dos componentes

| Componente | Responsabilidade no piloto | Não significa |
| --- | --- | --- |
| Simulador Python | Gerar OD (densidade óptica), pH e temperatura medida com IDs, sequência e horário de geração; gravar leituras na fila antes de publicar; receber setpoint e comandos ligar/desligar das bombas 1, 2 e 3; responder com o mesmo `command_id` e resultado simulado. | Sensor calibrado, atuador real, vazão, volume bombeado ou execução física. |
| Fila local durável (SQLite) | Manter leituras até confirmação da aplicação; preservar `event_id`, sequência e horário original; recuperar pendências após reinício; expor quantidade, idade pendente e erro de publicação. | Substituto de backup ou garantia contra perda do disco/host. |
| Mosquitto / MQTT | Transportar mensagens entre produtores e consumidores locais, com tópicos separados para telemetria, ACK, comandos e respostas. | Banco de dados, confirmação de commit, execução de comando ou interface comprovada do hardware eVOLVER. |
| Ingestão Python | Validar esquema, origem, IDs e horários; registrar horário de recebimento; impedir duplicatas; gravar em transação; emitir ACK de aplicação somente após commit; receber resultados simulados e persistir eventos correlacionados. | Autoridade para inferir efeito científico ou físico. |
| PostgreSQL + TimescaleDB | Guardar metadados, medições, eventos de conexão, comandos e auditoria; garantir unicidade lógica por `event_id` na tabela de IDs processados, gravada na mesma transação da medição; servir como fonte do histórico persistido. | Prova de que um comando alterou equipamento físico. |
| API Python | Fornecer consultas e estado consistente, impor autorização para ações, validar prazo/alvo de comandos, registrar autor e publicar comandos; expor mudanças persistidas à interface. | Acesso direto do navegador ao MQTT ou ao banco. |
| Interface web | Mostrar estado recente e histórico, horários de geração/recebimento, frescor/conexão e fila pendente; permitir ações simuladas e apresentar os estados do comando sem confundi-los. | Fonte primária dos dados ou confirmação independente de execução física. |

## Contratos e distinções de estado

### Telemetria

Cada leitura inclui no mínimo: `schema_version` (versão do formato), `event_id` (identidade estável), `equipment_id` lógico do simulador, posição/frasco e, quando aplicável, `experiment_run_id`; tipo `od`, `ph` ou `temperature` e valor numérico; `generated_at` (horário de geração) e sequência do produtor. A ingestão acrescenta `received_at` (horário de recebimento). Reenvios preservam `event_id`, sequência e `generated_at`; o banco impede duas gravações lógicas para o mesmo ID.

Um horário antigo não torna o evento inválido: ele entra no histórico pelo horário de geração, mas não substitui automaticamente o valor mais recente já conhecido.

### Comandos

Todo comando contém `command_id` (identidade de correlação), tipo/alvo, ação/valor, instante de criação, prazo de validade, autor e vínculo com a execução experimental quando aplicável. No piloto, os alvos são setpoint de temperatura e bombas 1, 2 e 3 com ação ligar/desligar.

Apresentar estados separados e só avançar quando houver evidência correspondente:

1. **Solicitado:** a API registrou a intenção e seu autor.
2. **Aceito ou rejeitado:** a API validou autorização, alvo, ação e prazo; a rejeição tem motivo.
3. **Enviado:** publicação ao broker concluída; isto só comprova envio ao transporte.
4. **Recebido:** há confirmação correlacionada de que o simulador recebeu o comando.
5. **Executado no simulador ou falhou:** a resposta correlacionada foi gravada. **Resultado desconhecido** indica ausência de resposta conclusiva; não deve ser apresentado como execução.

Temperatura **medida** é telemetria; temperatura **desejada** é setpoint. Valores publicados, recebidos e executados são estados diferentes. Para bombas, não inferir estado físico, vazão nem volume real.

## Fluxos principais

### 1. Telemetria normal e confirmação pós-commit

1. O simulador cria a leitura com `event_id`, sequência e `generated_at`.
2. Grava a leitura na fila SQLite antes de tentar publicar.
3. Publica telemetria no tópico MQTT correspondente.
4. A ingestão valida esquema e origem, abre transação e grava a medição e o ID processado, ou identifica uma duplicata já gravada.
5. Após commit bem-sucedido, a ingestão publica ACK de aplicação com `event_id` e resultado `persistido` ou `duplicado`. Falha de gravação não gera ACK de persistência.
6. O simulador recebe o ACK e marca o evento como concluído/removível da fila.
7. A API consulta o banco e atualiza a interface com valor, horário de geração, horário de recebimento e frescor.

ACK de QoS (nível de qualidade de serviço) do MQTT confirma uma etapa do transporte. Ele não substitui o ACK de aplicação emitido depois da persistência central. **Verificar e registrar na implementação:** para o mesmo `event_id`, guardar estado da fila antes/depois, log de commit e do ACK posterior, consulta ao banco e captura da interface. Espera-se um registro lógico e saída da fila somente após o ACK de aplicação. Corresponde a A1, A2 e A4 do T01; este documento não comprova o ensaio.

### 2. Desconexão, Store and Forward e reinício

1. Se broker/ingestão/banco estiver indisponível, a publicação falha ou não recebe ACK de aplicação. *Store and Forward* significa guardar localmente e reenviar depois.
2. O evento continua na fila local, sem trocar identidade ou horário.
3. A tela indica desconexão, idade da última leitura e/ou pendências; dados anteriores não são rotulados como atuais.
4. Após reconexão, o produtor reenvia eventos pendentes segundo a política configurada.
5. Se o evento já tiver sido persistido antes da perda do ACK, a ingestão o reconhece como duplicata, não cria novo registro e pode emitir novamente o ACK.
6. Depois do ACK pós-commit, o produtor conclui o item da fila.
7. Se a máquina reiniciar, o produtor recupera a fila durável; ingestão e API recuperam estado do banco.

**Verificar e registrar:** anotar os IDs e a contagem da fila antes da falha, durante a falha e após reconexão/reinício; guardar logs de reenvio e ACK, consulta de unicidade no banco e captura do aviso de dado antigo. Espera-se preservar todos os eventos válidos, sem duplicatas lógicas (A3–A5 do T01). Capacidade da fila, política quando cheia e intervalo de repetição ainda serão definidos. Se a fila atingir o limite, o sistema deve sinalizar o problema sem apagar eventos antigos silenciosamente. A atualização da interface por SSE já foi decidida no T03.

### 3. Mensagens inválidas e quarentena

Evento malformado ou incompatível com `schema_version` recebe rejeição explícita e motivo registrado. Deve ser isolado em quarentena ou encaminhado para tratamento manual, para não bloquear indefinidamente os demais eventos. Evento inválido não recebe confirmação de persistência válida e não deve ser descartado silenciosamente. **Verificar e registrar:** enviar mensagem inválida identificável, guardar log de rejeição e motivo, registro de quarentena/tratamento e evidência de que a leitura válida seguinte foi processada. O mecanismo de quarentena ainda será definido.

### 4. Dados atrasados e fora de ordem

A ingestão conserva `generated_at`, `received_at`, sequência e identidade do produtor. Armazena eventos atrasados no histórico pelo horário de geração, sem regredir a última leitura da mesma fonte e tipo. Para investigar atraso, comparar também horário de recebimento e sequência. **Verificar e registrar:** enviar dois eventos da mesma fonte e tipo em ordem inversa de geração; guardar consultas do histórico e da última leitura. Espera-se que ambos apareçam uma vez e que o mais recente por geração continue como último (A6 do T01).

### 5. Comandos e respostas simuladas

1. Usuário solicita ação pela interface.
2. API registra `command_id`, autor e estado **solicitado**; valida autorização, alvo/ação e prazo, e registra **aceito** ou **rejeitado**, com motivo.
3. API publica comando não retido, com validade limitada, para o simulador por MQTT.
4. O estado **enviado** é registrado separadamente do recebimento.
5. Simulador valida prazo e identidade, altera apenas seu estado simulado e devolve resposta com o mesmo `command_id`. A confirmação de recebimento e o resultado são eventos distintos.
6. Ingestão valida a correlação e grava a resposta/evento; a API mostra o resultado persistido como executado no simulador, falhou ou rejeitado, conforme a evidência.
7. Se a resposta não chegar, mostrar **resultado desconhecido**. Não repetir automaticamente comando antigo de bomba após reconexão. Uma nova tentativa exige política explícita e não deve esconder a incerteza do resultado anterior.

Comandos expirados durante desconexão são recusados pelo simulador e permanecem auditáveis como expirados/rejeitados. O piloto não usa comandos MQTT retidos para atuadores. **Verificar e registrar:** guardar pedido, `command_id`, autor disponível no piloto, validação, publicação, confirmação de recebimento, resposta, consulta de auditoria e captura dos estados. Testar setpoint e ligar/desligar de cada bomba separadamente, além de comando expirado durante desconexão. Espera-se correlação pelo mesmo ID e nenhuma execução do expirado (A7 do T01). Semântica de retentativa e timeouts continuam pendentes.

## Decisões registradas e decisões pendentes

### Base adotada para o desenho

**Escopo incluído:**

- Uma máquina local, com os componentes externos do piloto.
- Simulador Python e valores mockados como origem/destino de telemetria e comandos; nenhuma ação tem efeito físico.
- Mosquitto/MQTT para transporte no protótipo simulado.
- Ingestão e API em Python; PostgreSQL + TimescaleDB como persistência central; interface web.
- Fila durável no produtor, ACK de aplicação após commit, deduplicação por identidade estável e histórico que aceita dados atrasados.
- Separação entre temperatura medida e setpoint; entre publicar, receber e executar comando simulado.

### Decidido no T03

- FastAPI, `aiomqtt`/paho-mqtt, Vue 3 + Vite e Chart.js; fila local SQLite no simulador.
- Atualização ao vivo por SSE; aviso ingestão → API por `LISTEN/NOTIFY`, com recarga do estado pelo banco após reconexão.
- Unicidade por `event_id` em tabela de IDs processados, gravada na mesma transação da medição.

### Pendente de decisão técnica/revisão

As tarefas abaixo já estão previstas em outras issues. Permanecem aqui para mostrar o que o desenho ainda não fixa; sua implementação e seus testes não são critérios de conclusão da issue #2.

- Convenção de tópicos e QoS: definir no [contrato #19](https://github.com/KachanChK/eVOLVER-CNPEM/issues/19) e configurar no [broker #5](https://github.com/KachanChK/eVOLVER-CNPEM/issues/5). Autenticação local e ACLs (listas de controle de acesso): [#5](https://github.com/KachanChK/eVOLVER-CNPEM/issues/5) e [#12](https://github.com/KachanChK/eVOLVER-CNPEM/issues/12).
- Esquema e versionamento final das mensagens: [#19](https://github.com/KachanChK/eVOLVER-CNPEM/issues/19). Tabelas e índices: [#9](https://github.com/KachanChK/eVOLVER-CNPEM/issues/9).
- Capacidade da fila SQLite, disco cheio e retentativas: [#6](https://github.com/KachanChK/eVOLVER-CNPEM/issues/6); rejeição e quarentena: [#7](https://github.com/KachanChK/eVOLVER-CNPEM/issues/7), com teste em [#13](https://github.com/KachanChK/eVOLVER-CNPEM/issues/13). O intervalo exato de retentativa ainda não está fixado.
- Validade e estados dos comandos: [#19](https://github.com/KachanChK/eVOLVER-CNPEM/issues/19), [#8](https://github.com/KachanChK/eVOLVER-CNPEM/issues/8) e [#22](https://github.com/KachanChK/eVOLVER-CNPEM/issues/22); exibição do resultado desconhecido: [#23](https://github.com/KachanChK/eVOLVER-CNPEM/issues/23). Timeouts e tratamento manual exatos ainda não estão fixados.
- Procedimento inicial de backup: [#9](https://github.com/KachanChK/eVOLVER-CNPEM/issues/9); backup, restauração e documentação final: [#17](https://github.com/KachanChK/eVOLVER-CNPEM/issues/17). Destino seguro e frequência ainda não estão detalhados nas issues.
- Parâmetros do ensaio: geração configurável em [#4](https://github.com/KachanChK/eVOLVER-CNPEM/issues/4), validação em [#15](https://github.com/KachanChK/eVOLVER-CNPEM/issues/15) e aceite em [#16](https://github.com/KachanChK/eVOLVER-CNPEM/issues/16). Indicação de dado antigo: API [#20](https://github.com/KachanChK/eVOLVER-CNPEM/issues/20), interface [#11](https://github.com/KachanChK/eVOLVER-CNPEM/issues/11) e alerta [#14](https://github.com/KachanChK/eVOLVER-CNPEM/issues/14). Fixar os valores e o limiar antes do ensaio, conforme T01; não são metas de produção.

Essas pendências não alteram a fronteira do piloto nem autorizam comportamento físico. Antes de implementar, revisar qualquer decisão que reduza durabilidade, prevenção de duplicatas, rastreabilidade ou distinção de estados contra os critérios P0 do T01.

## Limite em relação ao hardware físico

**Fora do escopo:** o uso de MQTT/Mosquitto está definido para conectar o simulador externo aos serviços locais do piloto. **Não foi comprovado que o hardware físico eVOLVER ofereça MQTT**, nem que possua uma interface adequada para esses fluxos. O desenho não conecta nem presume protocolo físico. Uma integração futura exige descoberta e validação separadas; se necessário, um adaptador externo deverá ser definido sem introduzir agente embarcado ou disputar a autoridade de controle existente.

## Critérios de conclusão deste documento

Para conferir a entrega da issue #2, a equipe deve localizar neste arquivo: (1) contexto e componentes da máquina local; (2) caminhos separados de telemetria, ACK pós-commit, comandos e respostas simuladas; (3) responsabilidades e fronteiras de falha; (4) comportamento esperado na desconexão, duplicata, dado atrasado, mensagem inválida e comando sem resposta; (5) decisões, pendências e limite do hardware físico. Os diagramas e textos acima registram esse desenho. A conferência deste documento pode ser feita pela equipe, sem exigir indicação individual. Os testes A1–A8 e suas evidências pertencem ao aceite do piloto no T01; não são resultados comprovados por este documento.


