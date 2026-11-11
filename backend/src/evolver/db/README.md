# Banco de dados nesta etapa

O schema atual contém três tabelas:

- `vials`: `vial_id` numérico, `equipment_id`, rótulo opcional e data de cadastro.
- `experiments`: nome, vial, início e fim da alocação e data de exclusão lógica.
- `temperature_readings`: `event_id`, `experiment_id`, `vial_id`, temperatura em °C, horário de geração
  e horário de recebimento. É uma hypertable TimescaleDB particionada por `generated_at`.

O vial, o equipamento e o experimento precisam corresponder à alocação no horário de
geração. A chave `(event_id, generated_at)` evita gravar duas vezes a mesma mensagem.

O schema é criado pelas migrações Alembic. `get_temperature_history(session, experiment_id)`
retorna as leituras do experimento. Use a consulta SQL abaixo no DBeaver:

```sql
SELECT t.experiment_id, v.vial_id, v.label, t.temperature_celsius,
       t.generated_at, t.received_at, t.event_id
FROM temperature_readings AS t
JOIN vials AS v USING (vial_id)
ORDER BY t.generated_at DESC
LIMIT 100;
```

O volume `postgres_data` preserva os dados ao parar os contêineres. A opção
`docker compose down -v` apaga esse volume.
