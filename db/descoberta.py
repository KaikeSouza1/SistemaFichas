"""Descoberta automatica do PC "principal" na rede local, via broadcast UDP -
assim quem escolhe "conectar em outro PC" nao precisa digitar IP: o app
procura sozinho e mostra o evento encontrado pra so confirmar.

Protocolo simples, sem dependencia externa: o cliente manda um pacote UDP
("ping") pra 255.255.255.255 na PORTA_DESCOBERTA; todo PC que e "principal"
fica escutando essa porta e responde direto (unicast) pro cliente com seus
dados (ip, porta do Postgres, nome do evento atual).
"""

import json
import socket
import subprocess
import threading
import time

PORTA_DESCOBERTA = 54600
_MENSAGEM_PING = b"ADK_FICHAS_PING"
_NOME_REGRA_FIREWALL = "ADK Fichas - Descoberta"

_thread_responder_iniciada = False


def liberar_firewall() -> bool:
    """Reforco em tempo de execucao (o instalador ja libera isso na instalacao) -
    util pra quem instalou uma versao anterior sem essa regra. So tenta sem
    pedir elevacao - ver db/postgres_local.py.liberar_firewall para o motivo."""
    try:
        verificar = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule", f"name={_NOME_REGRA_FIREWALL}"],
            capture_output=True, text=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if verificar.returncode == 0 and "No rules match" not in verificar.stdout:
            return True
        resultado = subprocess.run(
            ["netsh", "advfirewall", "firewall", "add", "rule",
             f"name={_NOME_REGRA_FIREWALL}", "dir=in", "action=allow",
             "protocol=UDP", f"localport={PORTA_DESCOBERTA}"],
            capture_output=True, text=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return resultado.returncode == 0
    except Exception:
        return False


def informacoes_deste_servidor() -> dict:
    """IP/porta/evento atual deste PC, pra responder quem estiver buscando na
    rede. So faz sentido chamar quando papel_rede == 'servidor'."""
    from config import settings
    from db import repository
    from db.connection import ConexaoIndisponivel

    cfg = settings.load()
    try:
        evento = repository.obter_evento_aberto()
    except ConexaoIndisponivel:
        evento = None
    return {
        "ip": cfg["postgres"]["host"],
        "port": cfg["postgres"]["port"],
        "evento_nome": evento["nome"] if evento else "(evento ainda não aberto)",
    }


def iniciar_responder_em_background(obter_info) -> None:
    """Chamar uma vez, quando este PC vira 'principal'. `obter_info` e uma
    funcao sem argumentos que retorna um dict {ip, port, evento_nome} sempre
    atualizado - chamada a cada ping recebido, pra nunca responder desatualizado.
    Se a porta ja estiver em uso (por uma chamada anterior neste mesmo processo),
    nao faz nada - a thread ja rodando continua respondendo certo."""
    global _thread_responder_iniciada
    if _thread_responder_iniciada:
        return
    _thread_responder_iniciada = True

    def loop():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", PORTA_DESCOBERTA))
        except OSError:
            return
        while True:
            try:
                dados, endereco = sock.recvfrom(1024)
            except OSError:
                return
            if dados != _MENSAGEM_PING:
                continue
            try:
                resposta = json.dumps(obter_info()).encode("utf-8")
                sock.sendto(resposta, endereco)
            except Exception:
                pass

    threading.Thread(target=loop, daemon=True, name="descoberta-responder").start()


def buscar_servidores(timeout: float = 2.5) -> list[dict]:
    """Manda o broadcast e escuta respostas por `timeout` segundos. Retorna
    uma lista de dicts {ip, port, evento_nome}, um por PC principal encontrado
    (sem duplicar o mesmo IP)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(timeout)
    try:
        sock.sendto(_MENSAGEM_PING, ("255.255.255.255", PORTA_DESCOBERTA))
    except OSError:
        sock.close()
        return []

    encontrados = {}
    fim = time.monotonic() + timeout
    while True:
        restante = fim - time.monotonic()
        if restante <= 0:
            break
        sock.settimeout(restante)
        try:
            dados, _endereco = sock.recvfrom(2048)
            info = json.loads(dados.decode("utf-8"))
            encontrados[info["ip"]] = info
        except socket.timeout:
            break
        except Exception:
            continue
    sock.close()
    return list(encontrados.values())
