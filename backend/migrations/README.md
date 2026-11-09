# Migrações do banco

Com o TimescaleDB saudável, na raiz do repositório:

```powershell
uv sync --all-packages --group dev --frozen
uv run --env-file backend/.env --package evolver-cnpem-backend alembic upgrade head
```

Copie `backend/.env.example` para `backend/.env` antes de executar. A migração inicial
`20261027_01` cria o schema antigo; `20261109_01` o substitui pelas tabelas mínimas
`vials` e `temperature_readings`. A segunda revisão **recusa a atualização se houver
dados em qualquer tabela antiga**. Ela não faz migração dos dados antigos nem possui
downgrade automático. Faça backup e planeje a conversão dos dados antes de atualizar
um banco já utilizado.

No banco novo, a extensão TimescaleDB é ativada pelo script em `infra/db/init/` na
primeira inicialização do volume. O Alembic cria a hypertable e seu índice.

## Testes de integração

Use dois bancos **descartáveis**, separados do banco `evolver`, com a extensão
TimescaleDB habilitada. Defina `EVOLVER_TEST_DATABASE_URL` e
`EVOLVER_TEST_GUARD_DATABASE_URL` para esses bancos e execute:

```powershell
uv run --frozen --package evolver-cnpem-backend pytest backend/tests/db
```

O primeiro teste aplica todas as migrações e verifica gravação, duplicata, validação
e consulta. O segundo insere um dado no schema antigo e verifica que a migração se
recusa a apagá-lo. Sem as URLs, os testes de integração são ignorados.
