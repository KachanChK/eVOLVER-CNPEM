# Validação dos alertas do eVOLVER

Validação em 25/11/2026, com a implementação `99c988a` e a migração Alembic
`20261125_01`. O ensaio da interface usou a Central Tkinter no Windows,
Chromium, Vue/Vite, API FastAPI, Mosquitto 2.0.22 e TimescaleDB 2.31.0 sobre
PostgreSQL 17. O ensaio com 12 vials usou simulador e ingestão no Docker Linux.

## Testes automatizados

| Verificação | Resultado |
| --- | --- |
| `pytest backend/tests` com bancos descartáveis | 53 passaram, incluindo migração com dados prévios, rollback, emissão concorrente, paginação, arquivamento e regressão do controle de bombas. |
| `pytest packages/contracts/tests simulator/tests` | 116 passaram, incluindo isolamento entre vials e reentrega de um resultado de falha após o fim do cenário e após reiniciar o simulador. |
| `npm test` no frontend | 33 passaram, incluindo retomada do cursor, empilhamento, duração dos cards e chegada de alerta durante a limpeza. |
| `npm run build` e Ruff | Passaram. O Vite sinalizou o tamanho do pacote da prévia 3D. |

## Operação normal e monitoramento sem MQTT

Com a ingestão conectada, o simulador publicou 1.710 leituras para 12 vials
ativos, de 47 a 48 amostras por métrica e vial. Todas ficaram nas faixas padrão.
O vial 3 confirmou as ações `turn_on` e `turn_off` acionadas pela OD. A API
retornou o histórico de alertas vazio.

| Ação | ID do comando | ID da leitura |
| --- | --- | --- |
| Ligar por OD máxima | `4b4e4fa2-7f27-41de-9926-027161d0361a` | `486ef13a-6932-4505-9c4e-61fab34f6915` |
| Desligar por OD mínima | `d6d46bb6-167f-41ac-b09f-26270a7a4e11` | `f8bf2230-b524-49ad-ab23-c3ee5a982613` |

Em um banco separado, a ingestão iniciou com o broker inacessível e registrou
o alerta 1 para a alocação `455908f4-dc60-40af-b62f-59c2cb43d72b`, com
temperatura, pH e OD em atraso. O teste com relógio controlado verificou a
ausência de alerta até 14,999 s e a abertura aos 15 s.

Em uma rodada de diagnóstico com alocações já ativas durante a conexão da
ingestão, dois comandos de reconciliação expiraram com publicação confirmada.
Cada ocorrência encerrou após um novo `turn_off` confirmado.

## Telemetria e interface

Os alertas abaixo foram emitidos para o vial 1, alocação
`8629f61e-9a27-466f-a80e-d5c17220f664`. A latência vai do horário de
emissão no PostgreSQL até a inserção do card no navegador. A duração vai da
inserção até a remoção do card.

| Cenário | Alerta | ID da leitura | Latência | Duração |
| --- | ---: | --- | ---: | ---: |
| Temperatura de 40,0 °C | 1 | `8ca90b30-1f1f-4406-aad9-7296a1272c4e` | 237 ms | 5.005 ms |
| pH 7,70 | 2 | `d27c531b-d5d8-4ae8-b4fa-a2c709fbdb03` | 241 ms | Fechamento manual |
| OD 0,85 | 3 | `bb9fad38-83f9-4396-bddd-2257045e4ad4` | 275 ms | 5.003 ms |
| pH em atraso | 5 | — | 875 ms | — |

- Os três desvios exibiram cards simultâneos e encerraram com leituras
  subsequentes dentro da faixa. Os testes de integração confirmaram que
  desvios sucessivos e reentregas preservam um registro por ocorrência, e que
  um novo desvio após a recuperação gera outro alerta.
- A recarga preservou o indicador de não lidos e manteve os alertas anteriores
  no histórico. Entrar em **Alertas** marcou os registros como lidos. A
  confirmação de limpeza arquivou até o alerta 3 e preservou o alerta 4, que
  chegou enquanto a requisição ainda aguardava confirmação.
- A pausa de 20 s ampliou o alerta 5 de pH em atraso para **Sem dados do vial**
  com as três métricas. A ingestão reiniciou durante a pausa e manteve o
  mesmo registro. A coleta dos outros vials continuou e a retomada encerrou
  a ocorrência. Entre as leituras retidas, o evento
  `76b4713a-5f59-4394-bfd7-c507a67ee31b` saiu como histórico com o horário
  original.

A revisão de interface cobriu o rótulo acessível dos botões de fechar, o
indicador de não lidos, o anúncio de novos cards e o foco inicial em
**Cancelar** no diálogo de limpeza. [Diretrizes de interface da Vercel](https://github.com/vercel-labs/web-interface-guidelines/blob/main/command.md)

## Bombas e recuperação

| Cenário | Alerta e alocação | Comando e leitura de origem | Card |
| --- | --- | --- | ---: |
| Falha explícita no vial 1 | 1 · `a20c0639-6507-45d3-a9b3-ffae46e97152` | `de92664a-1f47-412b-9662-0e98322578ef` · `d9e694bc-2da3-4c95-8956-50a80decd63a` | 1.035 ms |
| Expiração sem resultado no vial 2 | 2 · `acb568f5-419b-4259-b15a-edfaa09fcc5f` | `50f46d86-1468-4076-ac5e-8cc7264e930c` · `61e04078-3cd7-4c95-aaed-69283c309089` | 519 ms |

- A Central mostrou **Falha aplicada** após a resposta MQTT
  `failed/simulation_error`. Cinco tentativas de desligamento falharam no
  intervalo de 60 s, espaçadas em pelo menos 10 s. A API manteve um alerta
  para o vial. O sexto `turn_off`,
  `01240df3-019c-42df-9157-7f740b7fbe34`, foi executado e encerrou a
  ocorrência 60,67 s após a emissão do alerta.
- No vial 2, o broker confirmou a publicação, mas a execução ficou sem
  resultado para a ingestão. A API retornou o motivo `timeout`. A ocorrência
  encerrou com a confirmação do comando `ea204921-b8bc-41c1-bc69-aa9f2897f7ae`.
  Os testes de integração cobriram também a rejeição explícita por
  `expired`, a reserva sem publicação e os cancelamentos.

## Reuso do vial e ciclo de vida da Central

Após reiniciar a aplicação, o alerta de bombas 1 permaneceu vinculado ao
experimento original. O vial 1 foi liberado e alocado para outro experimento.
O teste de pH gerou o alerta 6 na nova alocação
`1e8db877-fca7-45d4-a549-67502919432d`, com a leitura
`68b962f2-74a5-4e6c-aa30-fdb59a0832f3`. O card apareceu em 764 ms. Em
390 × 844 px, os cards ficaram dentro da largura da tela.

O script `scripts/simular.ps1` abriu a Central e exibiu os vials ativos.
Após reiniciar o PostgreSQL, a API manteve o histórico e a coleta retomou.
A janela foi fechada e o simulador registrou a leitura
`e032dcb8-d30d-4bd6-9a2c-825718d22c71`. O encerramento do processo pelo
sinal de parada concluiu com código 0.
