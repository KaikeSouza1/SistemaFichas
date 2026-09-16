"""Conexao com o Postgres central.

Decisao de arquitetura: sem pool persistente. Cada operacao abre sua propria
conexao e fecha no final. Numa rede local a cabo isso tem custo desprezivel,
e evita lidar com conexoes "zumbis" depois de uma queda breve de rede/cabo.
"""

import concurrent.futures
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from config import settings


class ConexaoIndisponivel(Exception):
    """O Postgres do servidor nao respondeu (rede caiu, PC servidor fora, etc)."""


def _dsn(pg: dict) -> str:
    # statement_timeout/lock_timeout (bug real, 2026-09-16): connect_timeout
    # so protege o momento de CONECTAR - uma QUERY que fica esperando um lock
    # de linha travado por OUTRO caixa (ex: dois caixas vendendo o mesmo
    # produto quase ao mesmo tempo, ver _consumir_estoque) nao tinha limite
    # nenhum e podia ficar pendurada pra sempre, sem nenhuma excecao (o
    # clique parecia simplesmente "nao fazer nada", item preso no carrinho,
    # nenhum erro pra logar). Agora qualquer query trava no maximo 10s e
    # levanta um erro de verdade (capturado como ConexaoIndisponivel, ver
    # conectar() abaixo).
    return (
        f"host={pg['host']} port={pg['port']} dbname={pg['dbname']} "
        f"user={pg['user']} password={pg['password']} connect_timeout=8 "
        f"sslmode={pg.get('sslmode', 'prefer')} "
        f"options='-c statement_timeout=10000 -c lock_timeout=10000'"
    )


PRAZO_CONEXAO_PADRAO_SEGUNDOS = 8

# Pool dedicado so pra tentativas de conexao (nao pra trabalho normal, ver
# _conectar_com_prazo). max_workers alto o bastante pra nunca ser o motivo de
# uma espera - se estiver todo ocupado e porque ja tem varias tentativas
# penduradas, o que so acontece quando o servidor ja esta mesmo fora do ar.
_EXECUTOR_CONEXAO = concurrent.futures.ThreadPoolExecutor(max_workers=16, thread_name_prefix="pg-connect")


def _conectar_com_prazo(dsn: str, prazo: float = PRAZO_CONEXAO_PADRAO_SEGUNDOS, **kwargs):
    """psycopg.connect(), mas com um limite de tempo garantido pelo PROPRIO
    Python, nao so pelo "connect_timeout" do libpq embutido no dsn.

    Achado em teste de carga (2026-08-07): em certas condicoes de rede/Windows
    (observado depois de muitas conexoes recentes ao mesmo host:porta), uma
    tentativa de conexao pode demorar bem mais que o "connect_timeout"
    configurado pra falhar de verdade - chegou a 130 segundos numa maquina de
    teste, mesmo com connect_timeout=8 no dsn. Pro operador, isso parece o
    app inteiro travado por mais de 2 minutos quando o servidor cai. Rodar a
    tentativa numa thread separada e usar Future.result(timeout=prazo) garante
    que quem chama NUNCA espera mais que `prazo`, seja qual for o motivo do
    atraso do lado do sistema operacional - a tentativa abandonada continua
    rodando sozinha em segundo plano e e descartada (fechada) se um dia
    terminar, sem afetar quem já desistiu de esperar."""
    future = _EXECUTOR_CONEXAO.submit(psycopg.connect, dsn, **kwargs)
    try:
        return future.result(timeout=prazo)
    except concurrent.futures.TimeoutError:
        future.add_done_callback(lambda f: None if f.exception() else f.result().close())
        raise ConexaoIndisponivel(
            f"O servidor nao respondeu em {prazo}s - rede caiu ou o PC principal esta fora do ar."
        ) from None
    except psycopg.OperationalError as exc:
        raise ConexaoIndisponivel(str(exc)) from exc


@contextmanager
def conectar():
    cfg = settings.load()
    conn = _conectar_com_prazo(_dsn(cfg["postgres"]), row_factory=dict_row, autocommit=False)
    try:
        yield conn
        conn.commit()
    except (psycopg.errors.QueryCanceled, psycopg.errors.LockNotAvailable) as exc:
        # statement_timeout/lock_timeout estourou (query travada esperando
        # lock de outro caixa, ver _dsn acima) - mesmo tratamento visivel de
        # ConexaoIndisponivel (dialogo claro), em vez de propagar um erro
        # cru do psycopg que os callers nao esperam.
        conn.rollback()
        raise ConexaoIndisponivel(
            "Uma operação demorou demais (provável disputa com outro caixa vendendo o mesmo "
            "produto ao mesmo tempo) - tente de novo."
        ) from exc
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def testar_conexao(pg: dict) -> tuple[bool, str]:
    try:
        conn = _conectar_com_prazo(_dsn(pg), prazo=5)
    except Exception as exc:
        return False, str(exc)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        return True, "Conexao OK"
    except Exception as exc:
        return False, str(exc)
    finally:
        conn.close()
