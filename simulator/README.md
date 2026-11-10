# Simulador externo

Projeto Python independente do backend. Sua primeira versão publica uma temperatura
de teste no serviço MQTT local usando Paho MQTT.

O simulador não importa `evolver.db` ou `evolver.api` e não acessa o PostgreSQL. Sua
futura fila SQLite ficará sob responsabilidade deste projeto.

Para executar o teste, copie `.env.example` para `.env`, defina `VIAL_ID` com o ID
de um frasco existente e inicie o serviço em `../mqtt/`. Na raiz do repositório, rode:

```powershell
uv sync --all-packages --group dev --frozen
uv run --env-file simulator/.env --package evolver-cnpem-simulator python -m evolver_simulator
```

O processo publica uma única temperatura e encerra após receber o PUBACK. O roteiro
completo, incluindo banco e ingestão, está no [README principal](../README.md).
Fila, envio contínuo e comandos ainda não foram implementados.
