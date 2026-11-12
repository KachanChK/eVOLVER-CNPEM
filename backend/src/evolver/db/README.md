# Banco de dados nesta etapa

O schema atual contém cinco tabelas principais:

- `vials`: `vial_id` numérico, `equipment_id`, rótulo opcional e data de cadastro.
- `experiments`: nome, vial, início, fim e exclusão lógica da alocação.
- `temperature_readings`: `event_id`, `vial_id`, temperatura em °C, horário de geração
  e horário de recebimento. É uma hypertable TimescaleDB particionada por `generated_at`.
- `ph_readings`: leituras de pH, com a medição na coluna `ph_value`.
- `od_readings`: leituras de OD, com a medição na coluna `od_value`.

O `vial_id` da mensagem precisa existir e pertencer ao `equipment_id` informado. A
chave `(event_id, generated_at)` evita gravar duas vezes a mesma mensagem recebida de
novo. O cadastro de experimentos é feito pela interface. Ainda não há dados de bombas.

O schema é criado pelas migrações Alembic. `get_temperature_history(session, experiment_id)`
retorna as leituras de um experimento. Use a consulta SQL abaixo no DBeaver:

```sql
SELECT v.vial_id, v.label, t.temperature_celsius,
       t.generated_at, t.received_at, t.event_id
FROM temperature_readings AS t
JOIN vials AS v USING (vial_id)
ORDER BY t.generated_at DESC
LIMIT 100;
```

O volume `postgres_data` preserva os dados ao parar os contêineres. A opção
`docker compose down -v` apaga esse volume.
