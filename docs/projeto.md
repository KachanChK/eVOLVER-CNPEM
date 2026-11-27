# eVOLVER CNPEM · Comece por aqui

O eVOLVER CNPEM é o software externo ao equipamento. O piloto roda localmente e permite cadastrar experimentos, acompanhar medições simuladas de temperatura, pH e densidade óptica (OD) e consultar o histórico do grupo de bombas simulado.

## O que já funciona

| Área | O que você consegue fazer |
| --- | --- |
| Experimentos | Cadastrar nome, tipo de cultura e limites de OD, além de escolher um dos 12 vials disponíveis. Um vial é a posição onde fica o frasco e comporta um experimento ativo por vez. |
| Medições | Acompanhar temperatura, pH e OD em gráficos e tabelas, selecionar o período e identificar lacunas ou leituras antigas. O simulador descobre os experimentos ativos e passa a gerar dados para eles. |
| Bombas simuladas | Acompanhar o estado e o histórico do grupo fixo `[1, 2, 3]`, acionado pelos limites de OD do experimento. É possível pausar e retomar a automação do grupo. |
| Encerramento | Inativar o experimento e continuar consultando seu histórico, ou excluí-lo da interface mantendo os registros no banco. Quando for necessário confirmar o desligamento do grupo, o vial fica ocupado até a confirmação. |

**Pausar visualização** congela os gráficos enquanto a coleta continua. **Pausar bombas** suspende a automação do grupo e solicita seu desligamento quando necessário.

## Experimente no Windows

Prepare as dependências, os arquivos `.env`, os contêineres e as migrações conforme o [README principal](../README.md#primeira-configuração).

1. Na raiz do repositório, execute `.\scripts\iniciar-local.ps1` para iniciar a API, a ingestão e a interface.
2. Abra [a interface local](http://127.0.0.1:5173), crie um experimento e entre no seu detalhe.
3. Em outro PowerShell, execute `.\scripts\simular.ps1`. As leituras aparecem nos gráficos nas atualizações da tela, que ocorrem a cada cinco segundos. Use **Ctrl+C** na janela do simulador para interromper a geração de leituras.

## O que falta

| Item previsto | Situação atual |
| --- | --- |
| Recuperação de telemetria após falha (*Store and Forward*) | Faltam a fila durável no produtor, o reenvio e a confirmação da aplicação após gravar a leitura. Uma falha pode deixar lacunas no histórico. |
| Temperatura desejada (*setpoint*) | O comando está definido no contrato MQTT. Faltam o fluxo pela interface e pela API, a execução no simulador e o acompanhamento do resultado. O painel mostra a temperatura medida simulada. |
| Aceite de backup e restauração | Há um procedimento manual. Falta evidência do aceite original que compare leituras, comandos e vínculos antes e depois de restaurar em outro banco. [Guia de operação](../operations/README.md#backup-e-restauração) |

## Fora do escopo do piloto

- **Equipamento físico.** Conectar sensores, acionar bombas reais ou desenvolver firmware e software embarcado.
- **Validação científica.** Calibrar sensores, comprovar a precisão das medições ou validar vazão e volume de bombeamento.
- **Rotinas experimentais.** Executar protocolos completos de cultivo, como turbidostato ou quimiostato, ou controlar cada bomba separadamente.
- **Operação em produção.** Implantação remota, controle de acesso à interface, alta disponibilidade e metas de escala e desempenho. Exportação e alertas também ficam para etapas posteriores.

O [escopo original](legacy/escopo-e-aceite.md) registra os critérios de aceite do piloto.

Para entender como os serviços se comunicam e por que o sistema foi organizado assim, siga para a [arquitetura atual](arquitetura-atual.md).
