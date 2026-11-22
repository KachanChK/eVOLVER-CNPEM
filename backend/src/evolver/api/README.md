# API

API FastAPI do piloto de experimentos. Consulte `http://127.0.0.1:8000/docs` para
ver as rotas de cadastro, vials livres, histórico, inativação e exclusão lógica.
O cadastro exige `od_min` e `od_max` como números JSON. Nas respostas de
experimentos, os limites são strings decimais para preservar todos os dígitos
em clientes JSON, ou `null` quando ainda não há limites configurados.

O [README principal](../../../../README.md) explica como iniciar a API.
