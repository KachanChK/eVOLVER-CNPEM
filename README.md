# eVOLVER-CNPEM
Repositório do projeto de monitoramento de células eVOLVER. Parceria PUCC e CNPEM

Agentes de IA que trabalham neste repositório devem ler [AGENTS.md](AGENTS.md).

## Contratos MQTT do piloto

O contrato versionado do piloto simulado — tópicos, QoS, regras de confirmação,
modelos Pydantic, schemas JSON e exemplos de mensagens — está em
[backend/src/evolver/contracts/README.md](backend/src/evolver/contracts/README.md).
Simulador, ingestão e API usam os mesmos modelos antes da implementação dos
serviços.
