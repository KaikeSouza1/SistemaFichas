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

from config.settings import PASTA_DADOS_LOCAIS

# Sem isso, cada initdb/pg_ctl/netsh chamado a partir do app empacotado (que
# nao tem console nenhum) faz o Windows abrir uma janela de prompt nova pra
# cada um - e a do postgres.exe (que fica rodando pra sempre) nunca fecha
# sozinha, porque o processo continua vivo.
_SEM_JANELA = subprocess.CREATE_NO_WINDOW

PORTA_PADRAO = 5460
SENHA_PADRAO = "churrasco_local"
USUARIO_PADRAO = "churrasco"
NOME_BANCO = "sistemachurrasco"

# Os binarios (so leitura) ficam do lado do executavel, dentro da pasta de
# instalacao - tudo bem, so sao executados, nunca gravados. Os DADOS (que o
# initdb cria e o postgres.exe fica escrevendo sem parar) tem que ficar numa
# pasta gravavel sem admin (ver config.settings.PASTA_DADOS_LOCAIS) - nunca
# dentro de "C:\Program Files\...", ou a primeira tentativa de iniciar o banco
# local ja quebra com WinError 5 (Acesso negado).
_PASTA_APP = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
PASTA_POSTGRES = _PASTA_APP / "tools" / "postgres"
PASTA_DADOS = PASTA_DADOS_LOCAIS / "dados_evento"

_BIN = PASTA_POSTGRES / "bin"
_INITDB = _BIN / "initdb.exe"
_PG_CTL = _BIN / "pg_ctl.exe"
_POSTGRES = _BIN / "postgres.exe"


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
        try:
            resultado = subprocess.run(
                [str(_INITDB), "-D", str(PASTA_DADOS), "-U", USUARIO_PADRAO,
                 "--pwfile", str(senha_arquivo), "-E", "UTF8", "--locale=C"],
                capture_output=True, text=True, timeout=30, creationflags=_SEM_JANELA,
            )
        except subprocess.TimeoutExpired:
            raise PostgresLocalIndisponivel("initdb demorou demais (mais de 30s) e foi interrompido.")
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
    try:
        resultado = subprocess.run(
            [str(_PG_CTL), "-D", str(PASTA_DADOS), "status"],
            capture_output=True, text=True, timeout=10, creationflags=_SEM_JANELA,
        )
    except subprocess.TimeoutExpired:
        return False
    return resultado.returncode == 0


def _aguardar_pronto(prazo_segundos: float) -> bool:
    """Espera o Postgres aceitar conexao de verdade (poll de conexao real, nao
    so o arquivo de PID) - troca o "-w" do pg_ctl, que no Windows depende do
    mesmo mecanismo de cmd.exe que causa o bug da janela."""
    import psycopg

    dsn_postgres = (
        f"host=127.0.0.1 port={PORTA_PADRAO} dbname=postgres "
        f"user={USUARIO_PADRAO} password={SENHA_PADRAO} connect_timeout=2"
    )
    prazo = time.monotonic() + prazo_segundos
    while time.monotonic() < prazo:
        try:
            with psycopg.connect(dsn_postgres):
                return True
        except Exception:
            time.sleep(0.5)
    return False


def _rodando_como_administrador() -> bool:
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def iniciar() -> dict:
    """Prepara (se preciso) e liga o Postgres local. Retorna os dados de conexao
    (host = IP deste PC na rede local, pra outros caixas digitarem na tela)."""
    if _rodando_como_administrador():
        # O Postgres se RECUSA a rodar como administrador (protecao de
        # seguranca dele mesmo, sem exceção) - isso acontece tanto se o
        # usuario clicou "Executar como administrador" quanto se a conta do
        # Windows e administradora com o Controle de Conta de Usuario (UAC)
        # desativado/baixo (nesse caso TODO programa roda com permissao
        # total sem avisar nada, mesmo com clique duplo normal). Avisamos
        # direto em vez de deixar tentar por 30s e mostrar um erro tecnico.
        raise PostgresLocalIndisponivel(
            "Este programa esta rodando como Administrador, e o banco de dados nao "
            "permite isso por seguranca. Se voce nao clicou em \"Executar como "
            "administrador\", a conta do Windows deste PC deve estar configurada como "
            "administradora com o Controle de Conta de Usuario (UAC) desligado - nesse "
            "caso, ou reative o UAC (pesquise por \"Alterar configuracoes de Controle de "
            "Conta de Usuario\" no Windows e suba o controle deslizante), ou use uma "
            "conta de usuario padrao (nao administradora) para abrir o ADK Fichas."
        )
    _preparar_datadir()
    if not status():
        log = PASTA_DADOS.parent / "postgres.log"
        # Chamamos o postgres.exe DIRETO (nao "pg_ctl start") - no Windows,
        # pg_ctl start precisa desacoplar o processo e faz isso passando por um
        # cmd.exe escondido; fechar essa janela (ou qualquer instabilidade nela)
        # mata o postgres.exe junto, e a espera do "-w" fica sujeita ao mesmo
        # mecanismo. Lancando direto com Popen (sem esperar o processo, ele
        # roda pra sempre) e sem console, esse problema nao existe.
        with open(log, "a", encoding="utf-8", errors="ignore") as log_handle:
            subprocess.Popen(
                [str(_POSTGRES), "-D", str(PASTA_DADOS)],
                stdout=log_handle, stderr=log_handle, stdin=subprocess.DEVNULL,
                creationflags=_SEM_JANELA,
            )
        if not _aguardar_pronto(30):
            trecho_log = log.read_text(encoding="utf-8", errors="ignore")[-800:] if log.exists() else ""
            raise PostgresLocalIndisponivel(f"O banco local nao ficou pronto em 30s: {trecho_log}")

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
        try:
            subprocess.run([str(_PG_CTL), "-D", str(PASTA_DADOS), "stop", "-m", "fast"], capture_output=True, timeout=15, creationflags=_SEM_JANELA)
        except subprocess.TimeoutExpired:
            pass


_NOME_REGRA_FIREWALL = "ADK Fichas - Postgres Local"


def liberar_firewall(porta: int = PORTA_PADRAO) -> bool:
    """Abre a porta do Postgres local no Firewall do Windows, pra outros caixas
    conseguirem conectar mesmo se a rede da festa cair como 'rede publica'
    (que bloqueia conexao de entrada por padrao). So tenta SEM pedir elevacao -
    um pedido de permissao do Windows (UAC) pode abrir atras da janela do app
    e travar tudo esperando um clique que o usuario nunca ve. Se falhar (sem
    admin), quem chamou avisa o usuario a rodar como administrador manualmente."""
    try:
        verificar = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule", f"name={_NOME_REGRA_FIREWALL}"],
            capture_output=True, text=True, timeout=10, creationflags=_SEM_JANELA,
        )
        if verificar.returncode == 0 and "No rules match" not in verificar.stdout:
            return True

        resultado = subprocess.run(
            ["netsh", "advfirewall", "firewall", "add", "rule",
             f"name={_NOME_REGRA_FIREWALL}", "dir=in", "action=allow",
             "protocol=TCP", f"localport={porta}"],
            capture_output=True, text=True, timeout=10, creationflags=_SEM_JANELA,
        )
        return resultado.returncode == 0
    except Exception:
        return False


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
