# Controle automático de OD (simulador)

O backend controla um único grupo por alocação, formado pelas bombas simuladas
`[1, 2, 3]` conforme a [Spec 7](spec-7-bombas-sincronizadas.md). Um experimento novo
começa com o grupo desligado.
Experimentos anteriores à configuração de limites mantêm estado desconhecido e
não entram no controle automático.

- A ingestão associa cada leitura ao UUID da alocação e confere o vial e o
  horário de geração. Leituras antigas sem UUID continuam no histórico pela
  janela de tempo, sem participar do controle automático ou da retomada.
  Para controle, a ingestão aceita OD finita em `[0,10; 0,80]` e usa somente
  a leitura mais recente por `generated_at` e, no mesmo horário e produtor,
  `sequence`. Leituras válidas para a alocação original podem chegar depois
  do seu encerramento e ficar no histórico.
- **Frescor:** uma leitura só pode iniciar comando até **10 segundos** após
  `generated_at`, inclusive, segundo o relógio da ingestão. Leitura do futuro
  não inicia comando. O prazo cobre a cadência atual de 0,5 s e pequenas filas
  locais; não há acionamento com OD antiga após reinício.
- Com estado confirmado desligado, `OD >= od_max` solicita `turn_on`; com estado
  confirmado ligado, `OD <= od_min` solicita `turn_off`. Entre os limites mantém
  estado. Uma transição pendente bloqueia outra decisão.
- O registro de comando guarda experimento, vial, `command_id`, leitura, motivo,
  estado desejado, criação, validade, envio, PUBACK e resultado. PUBACK confirma
  somente transporte. `received` confirma recebimento pelo simulador; somente
  `executed` confirma o novo estado simulado. Sem resultado conclusivo em 10 s,
  o estado fica `unknown` e o controlador não repete o comando.
- A ingestão publica um comando por ação do grupo com QoS 1 e `retain=false`.
  O contrato `1.0` usa `pump_id: 1` para o grupo e o UUID persistido da alocação
  em `experiment_run_id`. O simulador consulta a
  alocação ativa antes de executar ou repetir um resultado e rejeita vínculo
  ausente, encerrado ou incompatível. A telemetria simulada carrega o mesmo UUID.
- O simulador grava o estado único do grupo e a identidade dos comandos concluídos em SQLite antes
  de publicar `executed`. O arquivo padrão é
  `~/.evolver-simulator/pump-state.sqlite3` e pode ser definido por
  `SIMULATOR_PUMP_STATE_PATH`. Preserve esse arquivo entre reinícios do simulador.
  O estado usa o UUID da alocação e o vial. A ordenação e os resultados também
  são separados por UUID, inclusive quando o banco recriado reutiliza IDs
  numéricos. A atualização deixa registros antigos do SQLite no arquivo e
  inicia a reconciliação com a ingestão após reiniciar os serviços.
- A ingestão marca o estado como desconhecido ao iniciar, perder ou
  restabelecer a sessão MQTT.
  Após concluir ou expirar qualquer comando pendente, a próxima OD nova e
  recente solicita um `turn_off` de reconciliação; somente
  o resultado `executed` confirma o estado desligado e libera decisões futuras.
  Para experimento pausado ou em encerramento, o desligamento seguro é enviado
  sem aguardar OD nova. No encerramento, um `turn_on` que a ingestão ainda não
  reservou para envio é cancelado e fica no histórico. Se já houve reserva,
  aguarda-se seu resultado ou expiração antes de solicitar `turn_off`.
  Um `turn_off` já pendente pode ser enviado. Sua execução confirma o
  desligamento e conclui o encerramento.
  A repetição automática fica bloqueada se essa confirmação faltar. Uma queda
  na sequência do produtor também inicia essa reconciliação após reinício do
  simulador. Uma leitura antiga não a inicia.
- Pausa e decisão de OD usam o mesmo bloqueio transacional do experimento. A
  pausa interna persiste, bloqueia novos acionamentos e solicita desligamento
  quando necessário. A retomada só volta a avaliar OD após confirmar o
  desligamento, se necessário. A retomada solicita ligar apenas com uma leitura
  verificada e recente que atinja ou supere o máximo.
  Inativação/exclusão também bloqueia a automação e, se o grupo não estiver
  comprovadamente desligado, conclui o encerramento após resultado `executed`
  do comando de desligar. O vial continua ocupado enquanto a solicitação
  aguarda confirmação. Se o comando falhar ou expirar, a interface permite
  repetir apenas o desligamento, sem criar outro comando enquanto houver um
  pendente. A reconexão da ingestão também pode reconciliar o desligamento.

As rotas POST de inativação e DELETE retornam HTTP 202 enquanto a solicitação
aguarda execução, com a ação registrada. Quando encerram na mesma transação,
retornam respectivamente HTTP 200 com o experimento e HTTP 204. A consulta
GET /api/experiments/{id}/closure informa se o encerramento está pendente,
sem confirmação ou concluído, inclusive após uma exclusão lógica.

## Acompanhamento

O cadastro exige OD mínima e máxima entre 0,10 e 0,80, inclusive, com a máxima
maior que a mínima. Os membros do grupo são fixos para todo experimento.
O detalhe consulta a API a cada 5 s. A última OD é ordenada por geração e ganha o
aviso de leitura antiga após 10 s. O último resultado registrado também é marcado
como antigo após 10 s. A idade desse resultado informa quando houve a última
resposta conclusiva ou desfecho registrado. A perda de confirmação aparece no
campo **Estado das bombas** como **Desconhecido**.

`GET /api/experiments/{id}/pump` expõe o modo, o estado confirmado mais recente e
o identificador do comando pendente. `GET /api/experiments/{id}/pump/history`
expõe solicitações, resultados e transições do grupo em uma fotografia do banco.
A interface consulta `GET /api/experiments/{id}/pump/snapshot`, que lê modo,
estado, histórico, leituras de OD e encerramento na mesma fotografia transacional.
Após uma ação, o painel aguarda a nova fotografia completa e descarta
consultas anteriores à ação. O gráfico de
OD usa os limites cadastrados, marca intenções e resultados separadamente e
mostra faixas distintas para o grupo ligado com confirmação e para a automação
pausada. Uma pausa pode se sobrepor ao trecho ligado enquanto o desligamento
aguarda confirmação. A pausa da visualização congela o gráfico e preserva a
atualização do painel de controle.

A migração inicia o registro de períodos dos experimentos já ativos a partir
do estado observado naquele momento. Os comandos existentes continuam
consultáveis. Dados anteriores à migração podem não ter períodos registrados.

O teste com TimescaleDB descartável é
`backend/tests/db/test_pump_control_integration.py`.

A [matriz de aceite da Spec 7](evidencias-controle-bombas/README.md) registra a validação do
grupo de bombas. As evidências originais da Spec 6 antecedem essa mudança.
