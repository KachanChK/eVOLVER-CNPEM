# Aceite da Spec 6 · controle de OD

Ensaio com OD simulada, vial 1 e limites de 0,30 e 0,40. O cadastro e as ações de controle foram executados no navegador, com atualização automática da tela. Os dois primeiros ciclos usaram o comando normal do simulador, com semente 42, ruído de OD igual a zero e cadência de 0,5 s. Nos demais cenários, o roteiro forneceu medidas exatas ao publicador real do simulador.

## Matriz

| Cenário | Resultado observado | Captura |
| --- | --- | --- |
| Cadastro e criação | Erros para limites vazios, fora da faixa e invertidos. Apenas um seletor, o do vial. A criação válida inicia em automático e desligada. | [Cadastro](00-cadastro.jpg) · [Criação](01-criacao.jpg) |
| Dois ciclos | Dois pares ligar/desligar confirmados pelo simulador. O gráfico marca limites, períodos ligados e instantes distintos de intenção e resultado. | [Dois ciclos](02-dois-ciclos.jpg) |
| Pausa com bomba ligada | O desligamento vinculado a um `command_id` permanece pendente enquanto a simulação está suspensa. O estado ainda indica ligada; após a execução do desligamento, indica pausada e desligada. | [Pendente](03a-desligamento-pendente.jpg) · [Confirmado](03-pausa-ligada.jpg) |
| Retomada abaixo do máximo | Com OD 0,35, a automação volta e a bomba continua desligada, sem nova intenção. | [Retomada abaixo](04-retomada-abaixo.jpg) |
| Pausa com bomba desligada | A pausa é registrada sem novo comando de desligamento. | [Pausa desligada](05-pausa-desligada.jpg) |
| Retomada no máximo | OD de 0,40 gera intenção `resume` de ligar. O simulador confirma a execução. | [Retomada no máximo](06-retomada-no-maximo.jpg) |
| Leitura atrasada | OD de 0,10 gerada 12 s antes chega ao banco e entra na posição cronológica correta. OD de 0,40 continua como a última leitura, sem desligar a bomba. | [Leitura atrasada](07-leitura-atrasada.jpg) |
| Desconexão e retorno do broker | A interface exibe leitura e resultado antigos. A perda da sessão MQTT deixa o estado da bomba desconhecido até uma nova execução confirmada. | [Desconexão](08-desconexao.jpg) · [Reconexão](09-reconexao-sem-confirmacao.jpg) |
| Reinício do simulador | O mesmo volume do SQLite conserva o estado ligado no início do processo reiniciado. A próxima leitura fresca solicita desligamento de reconciliação e o simulador confirma. | [Reinício](10-reinicio.jpg) |
| Encerramento com bomba ligada | O desligamento executado é persistido antes de o experimento ficar inativo e o vial voltar a ser elegível. | [Encerramento](11-encerramento.jpg) |

[cenarios.json](cenarios.json) relaciona leitura, timestamps, estado do banco, `command_id`, valor da OD que disparou cada comando, resposta da API, transições e os campos exibidos pelo painel. O roteiro compara a OD e seu horário, modo,
estado da bomba, motivo da última mudança, comando pendente e último resultado
com a mesma fotografia da API antes de cada captura e confere a última OD no gráfico. [resultados-mqtt.json](resultados-mqtt.json) guarda as mensagens de recebimento e execução observadas no broker, correlacionadas pelo mesmo `command_id`.

## Topologia testada

Docker Desktop em uma máquina Windows. Simulador em contêiner Linux conectado apenas a uma bridge Docker interna. Mosquitto em duas redes, com DNS `broker:1883` para o simulador e uma porta TCP em loopback para a ingestão do host. API, ingestão e Vite Preview executados como processos no host. TimescaleDB em outro contêiner, com porta publicada em loopback e fora da rede do simulador. O Edge headless acessou o Vue pelo Vite.

O simulador descobriu a alocação por MQTT. As tentativas de conexão direta do contêiner do simulador às portas HTTP da API e TCP do PostgreSQL falharam. O único volume montado no contêiner do simulador continha seu próprio estado SQLite. O roteiro envia valores de teste ao processo do simulador pelo stdin do Docker. As mensagens da aplicação cruzam a fronteira pelo broker. [Dados do ensaio](topologia.json) · [Configuração para máquinas separadas](../../arquitetura-e-fluxos.md)

O ensaio demonstra isolamento de rede e comportamento simulado em um host. A instalação em dois hosts físicos e a validação de bomba, vazão e volume no equipamento têm aceites próprios.

## Como reproduzir

Requer Docker com contêineres Linux, Python 3.12, uv, Node, npm e Edge. Execute estes comandos em PowerShell na raiz do checkout.

```powershell
uv sync --locked --all-packages --group dev
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
uv pip install --python .venv/Scripts/python.exe playwright==1.65.2
.venv/Scripts/python.exe scripts/validar_spec6.py --output .local/spec6-ensaio
```

O [roteiro](../../../scripts/validar_spec6.py) cria recursos temporários com nomes exclusivos, executa as migrações e encerra os processos e contêineres que criou. O diretório de saída contém JPGs, respostas e logs. Use um diretório novo a cada rodada. O argumento `--browser-channel` permite selecionar outro canal Chromium instalado.

## Evidência por tarefa

| Tarefa | Evidência |
| --- | --- |
| S6-T01 | Capturas de cadastro, criação e desligamento pendente/confirmado. Testes do formulário e do contrato de observação da bomba. |
| S6-T02 | Capturas de dois ciclos, pausa e desconexão. A tabela do gráfico permite conferir períodos e correlacionar intenções e resultados. |
| S6-T03 | Matriz acima, arquivo de estados, mensagens MQTT, dados de topologia e roteiro reproduzível. |
| S6-T04 | [Arquitetura e configuração remota](../../arquitetura-e-fluxos.md) · [Ampliação do aceite](../../escopo-e-aceite.md) · [Comportamento do controle](../../controle-od.md) |

A entrega passou em 26 testes do frontend, 146 testes Python com TimescaleDB descartável, no build Vite, no smoke test MQTT e de ACLs com Mosquitto descartável, no Ruff e em `git diff --check`.
