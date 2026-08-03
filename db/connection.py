"""Conexao com o Postgres central.

Decisao de arquitetura: sem pool persistente. Cada operacao abre sua propria
conexao e fecha no final. Numa rede local a cabo isso tem custo desprezivel,
e evita lidar com conexoes "zumbis" depois de uma queda breve de rede/cabo.
"""

from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from config import settings


class ConexaoIndisponivel(Exception):
    """O Postgres do servidor nao respondeu (rede caiu, PC servidor fora, etc)."""


def _dsn(pg: dict) -> str:
    return (
        f"host={pg['host']} port={pg['port']} dbname={pg['dbname']} "
        f"user={pg['user']} password={pg['password']} connect_timeout=8 "
        f"sslmode={pg.get('sslmode', 'prefer')}"
    )


@contextmanager
def conectar():
    cfg = settings.load()
    try:
        conn = psycopg.connect(_dsn(cfg["postgres"]), row_factory=dict_row, autocommit=False)
    except psycopg.OperationalError as exc:
        raise ConexaoIndisponivel(str(exc)) from exc
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def testar_conexao(pg: dict) -> tuple[bool, str]:
    try:
        with psycopg.connect(_dsn(pg), connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        return True, "Conexao OK"
    except Exception as exc:
        return False, str(exc)
