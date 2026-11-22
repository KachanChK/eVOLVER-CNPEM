# Controle automático de OD (simulador)

O backend decide a bomba lógica única de cada vial. Um experimento novo começa
com a bomba simulada desligada; esse é o estado inicial definido pelo simulador.
Experimentos anteriores à configuração de limites mantêm estado desconhecido e
não entram no controle automático.

- A ingestão associa cada OD ao experimento válido no horário de geração. Para
  controle, aceita OD finita em `[0,10; 0,80]` e usa somente a leitura mais recente
  por `generated_at` e, no mesmo horário e produtor, `sequence`. Duplicatas e
  leituras atrasadas continuam no histórico, sem comandar a bomba.
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
- A ingestão publica comandos com QoS 1 e `retain=false` usando `pump_id: 1` e
  `experiment_run_id`. O simulador consulta a alocação ativa antes de executar
  e rejeita vínculo ausente, encerrado ou incompatível.
- O simulador grava estado e identidade dos comandos concluídos em SQLite antes
  de publicar `executed`. O arquivo padrão é
  `~/.evolver-simulator/pump-state.sqlite3` e pode ser definido por
  `SIMULATOR_PUMP_STATE_PATH`. Preserve esse arquivo entre reinícios do simulador.
  A chave do estado inclui experimento e vial, para não herdar o estado de outro
  experimento no mesmo vial.
- A ingestão marca o estado como desconhecido ao iniciar ou reconectar ao MQTT.
  Após concluir ou expirar qualquer comando pendente, a próxima OD nova e
  recente solicita um `turn_off` de reconciliação; somente
  o resultado `executed` confirma o estado desligado e libera decisões futuras.
  A repetição automática fica bloqueada se essa confirmação faltar. Uma queda
  na sequência do produtor também inicia essa reconciliação após reinício do
  simulador. Uma leitura antiga não a inicia.
- Pausa e decisão de OD usam o mesmo bloqueio transacional do experimento. A
  pausa interna persiste, bloqueia novos acionamentos e solicita desligamento
  quando necessário. A API e a interface de pausar/despausar pertencem à Spec 4.
  Inativação/exclusão também bloqueia a automação e, se a bomba não estiver
  comprovadamente desligada, conclui o encerramento após resultado `executed`
  do comando de desligar. Resultado ausente deixa o encerramento pendente para
  inspeção, sem presumir que a bomba desligou.

O teste com TimescaleDB descartável é
`backend/tests/db/test_pump_control_integration.py`. Ele não valida bomba física.
