# Simulador externo

Projeto Python independente do backend. Sua primeira versão publica uma temperatura
de teste no serviço MQTT local usando Paho MQTT.

O simulador não importa `evolver.db` ou `evolver.api` e não acessa o PostgreSQL. Sua
futura fila SQLite ficará sob responsabilidade deste projeto.

Para executar o teste, copie `.env.example` para `.env`, inicie antes o serviço em
`../mqtt/` e rode:

```powershell
uv sync
uv run --env-file .env python -m evolver_simulator
```

O processo publica uma única temperatura e encerra após receber o PUBACK. O roteiro
completo está em `../docs/plano-mqtt-independente.md`. Fila, envio contínuo e comandos
ainda não foram implementados.
