"""Servidor central fixo: destino de sincronizacao de TODOS os eventos, de
TODOS os PCs, de TODAS as cidades. Fixo no codigo de proposito - nao aparece
em nenhuma tela de configuracao, o usuario/operador nunca ve nem edita isso.

So recebe dados DEPOIS que um evento e fechado (ver db/sync.py). Nunca e
usado durante a operacao normal do evento - quem roda o evento e o Postgres
local (embutido) do PC principal daquele evento (ver db/postgres_local.py).
"""

CENTRAL = {
    "host": "177.73.253.55",
    "port": 19844,
    "dbname": "dev_fichas",
    "user": "pedroso",
    "password": "***REMOVIDO***",
    "sslmode": "require",
}
