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
    (so consulta o hostname - evita qualquer prompt de firewall do Windows).
    Ignora loopback (127.x) e link-local sem DHCP (169.254.x - APIPA, comum em
    adaptador virtual desconectado tipo VPN/VirtualBox) - esses nunca servem
    pra outro PC conectar. Prefere faixas de rede local reais (192.168/10/172.16-31)."""
    try:
        candidatos = [
            ip for ip in socket.gethostbyname_ex(socket.gethostname())[2]
            if not ip.startswith("127.") and not ip.startswith("169.254.")
        ]
    except OSError:
        candidatos = []

    def _prioridade(ip: str) -> int:
        if ip.startswith("192.168.") or ip.startswith("10."):
            return 0
        partes = ip.split(".")
        if ip.startswith("172.") and len(partes) > 1 and 16 <= int(partes[1]) <= 31:
            return 0
        return 1

    candidatos.sort(key=_prioridade)
    return candidatos[0] if candidatos else "127.0.0.1"


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


_NOME_REGRA_FIREWALL = "ADK Fichas - Postgres Local"


def _regra_firewall_existe() -> bool:
    try:
        verificar = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule", f"name={_NOME_REGRA_FIREWALL}"],
            capture_output=True, text=True,
        )
        return verificar.returncode == 0 and "No rules match" not in verificar.stdout
    except Exception:
        return False


def _adicionar_regra_firewall(porta: int) -> bool:
    try:
        resultado = subprocess.run(
            ["netsh", "advfirewall", "firewall", "add", "rule",
             f"name={_NOME_REGRA_FIREWALL}", "dir=in", "action=allow",
             "protocol=TCP", f"localport={porta}"],
            capture_output=True, text=True,
        )
        return resultado.returncode == 0
    except Exception:
        return False


def _adicionar_regra_firewall_elevado(porta: int) -> None:
    """Pede permissao de administrador do Windows so pra esse comando (nao pro
    programa inteiro) - aparece uma unica vez, so quando este PC vira
    'principal' e a tentativa sem elevar falhou. Start-Process -Wait garante
    que so seguimos depois que o usuario responder ao pedido de permissao."""
    comando_netsh = (
        f'advfirewall firewall add rule name=\\"{_NOME_REGRA_FIREWALL}\\" '
        f'dir=in action=allow protocol=TCP localport={porta}'
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command",
             f"Start-Process netsh -ArgumentList '{comando_netsh}' -Verb RunAs -Wait"],
            capture_output=True, text=True, timeout=60,
        )
    except Exception:
        pass


def liberar_firewall(porta: int = PORTA_PADRAO) -> bool:
    """Abre a porta do Postgres local no Firewall do Windows, pra outros caixas
    conseguirem conectar mesmo se a rede da festa cair como 'rede publica'
    (que bloqueia conexao de entrada por padrao). Tenta sem pedir nada primeiro;
    se falhar (processo sem admin), pede permissao so pra esse comando - o
    usuario ve UM pedido do Windows, nao precisa configurar nada no atalho."""
    if _regra_firewall_existe():
        return True
    if _adicionar_regra_firewall(porta) and _regra_firewall_existe():
        return True
    _adicionar_regra_firewall_elevado(porta)
    return _regra_firewall_existe()


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
