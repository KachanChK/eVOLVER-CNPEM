# Simulador externo

Projeto Python que consulta as alocações ativas no MQTT e publica uma temperatura de
teste por vial com experimento ativo usando Paho MQTT.

O simulador não importa `evolver.db` ou `evolver.api` e não acessa o PostgreSQL. Sua
futura fila SQLite ficará sob responsabilidade deste projeto.

Para executar o teste, copie `.env.example` para `.env`, inicie o broker e a ingestão
e cadastre um experimento pela interface. Na raiz do repositório, rode:

```powershell
uv sync --all-packages --group dev --frozen
uv run --env-file simulator/.env --package evolver-cnpem-simulator python -m evolver_simulator
```

O processo envia uma rodada e encerra. O roteiro completo está no
[README principal](../README.md).
