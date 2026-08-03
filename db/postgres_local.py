"""Controla o Postgres portatil embutido no proprio SistemaChurrasco.

Nao depende de nada instalado no PC: os binarios ficam em tools/postgres
(do lado do executavel, ou na raiz do projeto em dev). Quando este PC e
escolhido como "servidor do evento", chamamos initdb (na primeira vez) e
pg_ctl start para subir uma instancia local, acessivel pelos outros caixas
na mesma rede.
"""

import socket
import subprocess
import sys
import time
from pathlib import Path

PORTA_PADRAO = 5460
SENHA_PADRAO = "churrasco_local"
USUARIO_PADRAO = "churrasco"
NOME_BANCO = "sistemachurrasco"

_PASTA_APP = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
PASTA_POSTGRES = _PASTA_APP / "tools" / "postgres"
PASTA_DADOS = _PASTA_APP / "tools" / "dados_evento"

_BIN = PASTA_POSTGRES / "bin"
_INITDB = _BIN / "initdb.exe"
_PG_CTL = _BIN / "pg_ctl.exe"


class PostgresLocalIndisponivel(Exception):
    """Os binarios do Postgres embutido nao foram encontrados."""


def disponivel() -> bool:
    return _INITDB.exists() and _PG_CTL.exists()


def _ip_local() -> str:
    """IP deste PC na rede local, sem gerar trafego de rede de verdade
    (so consulta o hostname - evita qualquer prompt de firewall do Windows)."""
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if not ip.startswith("127."):
                return ip
    except OSError:
        pass
    return "127.0.0.1"


def _preparar_datadir() -> None:
    if (PASTA_DADOS / "PG_VERSION").exists():
        return
    if not disponivel():
        raise PostgresLocalIndisponivel(f"Binarios do Postgres nao encontrados em {PASTA_POSTGRES}")
    PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    senha_arquivo = PASTA_DADOS.parent / "_senha_tmp.txt"
    senha_arquivo.write_text(SENHA_PADRAO, encoding="utf-8")
    try:
        resultado = subprocess.run(
            [str(_INITDB), "-D", str(PASTA_DADOS), "-U", USUARIO_PADRAO,
             "--pwfile", str(senha_arquivo), "-E", "UTF8", "--locale=C"],
            capture_output=True, text=True,
        )
        if resultado.returncode != 0:
            raise PostgresLocalIndisponivel(f"initdb falhou: {resultado.stderr}")
    finally:
        senha_arquivo.unlink(missing_ok=True)

    # Libera conexao de outros PCs na rede local (nao so localhost) e ajusta a porta.
    conf = PASTA_DADOS / "postgresql.conf"
    texto = conf.read_text(encoding="utf-8")
    texto += f"\nlisten_addresses = '*'\nport = {PORTA_PADRAO}\n"
    conf.write_text(texto, encoding="utf-8")

    hba = PASTA_DADOS / "pg_hba.conf"
    hba.write_text(
        "host all all 0.0.0.0/0 scram-sha-256\n"
        "host all all ::0/0 scram-sha-256\n"
        "local all all trust\n",
        encoding="utf-8",
    )


def status() -> bool:
    """True se a instancia local estiver rodando."""
    if not disponivel() or not (PASTA_DADOS / "PG_VERSION").exists():
        return False
    resultado = subprocess.run(
        [str(_PG_CTL), "-D", str(PASTA_DADOS), "status"],
        capture_output=True, text=True,
    )
    return resultado.returncode == 0


def iniciar() -> dict:
    """Prepara (se preciso) e liga o Postgres local. Retorna os dados de conexao
    (host = IP deste PC na rede local, pra outros caixas digitarem na tela)."""
    _preparar_datadir()
    if not status():
        log = PASTA_DADOS.parent / "postgres.log"
        # NAO usar capture_output aqui: pg_ctl start deixa o postgres.exe (que
        # roda pra sempre) herdar o pipe de saida, e o Python nunca ve o EOF -
        # subprocess.run() trava para sempre esperando o pipe fechar.
        resultado = subprocess.run(
            [str(_PG_CTL), "-D", str(PASTA_DADOS), "-l", str(log), "-w", "start"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if resultado.returncode != 0:
            trecho_log = log.read_text(encoding="utf-8", errors="ignore")[-800:] if log.exists() else ""
            raise PostgresLocalIndisponivel(f"Nao consegui iniciar o Postgres local (codigo {resultado.returncode}): {trecho_log}")
        time.sleep(1)

    return {
        "host": _ip_local(),
        "port": PORTA_PADRAO,
        "dbname": NOME_BANCO,
        "user": USUARIO_PADRAO,
        "password": SENHA_PADRAO,
        "sslmode": "disable",
    }


def parar() -> None:
    if disponivel() and status():
        subprocess.run([str(_PG_CTL), "-D", str(PASTA_DADOS), "stop", "-m", "fast"], capture_output=True)


def criar_banco_se_preciso() -> None:
    import psycopg

    dsn_postgres = (
        f"host=127.0.0.1 port={PORTA_PADRAO} dbname=postgres "
        f"user={USUARIO_PADRAO} password={SENHA_PADRAO} connect_timeout=5"
    )
    with psycopg.connect(dsn_postgres, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (NOME_BANCO,))
            if not cur.fetchone():
                cur.execute(f'CREATE DATABASE "{NOME_BANCO}"')
