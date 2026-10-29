# Simulador externo

Projeto Python independente do backend, preparado na E2-T03 (#3) para o futuro
processo que produzirá dados simulados e receberá comandos sem efeito físico.
Seu pacote é `evolver_simulator` e sua única dependência de projeto nesta etapa é
`evolver-contracts`, importada como `evolver_contracts`.

Quando implementado, o simulador se comunicará com os serviços centrais por MQTT,
sem importar `evolver.db` ou `evolver.api` e sem acessar o PostgreSQL. Sua futura
fila SQLite ficará sob responsabilidade deste projeto.

Ainda não há ponto de entrada, produtor MQTT, fila ou execução de comandos. Instalar
este pacote no workspace verifica somente sua estrutura e dependências; não inicia
um serviço funcional.
