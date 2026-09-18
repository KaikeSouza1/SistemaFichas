"""Verifica se tem uma build mais nova publicada no GitHub Releases e, se o
usuario topar, baixa e instala sozinho.

So funciona no .exe empacotado de verdade (rodando com `python main.py` em
dev nao faz sentido se auto-atualizar). Nao depende de git/commit nenhum -
so le o release ja existente via API publica (sem token, o repo e publico).
"""

import base64
import json
import os
import re
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

import certifi

from config.central_fetch import FETCH_CONFIG
from config.versao import URL_INSTALADOR, URL_RELEASE_API, VERSAO_APP

_CONTEXTO_SSL = ssl.create_default_context(cafile=certifi.where())
_PASTA_APP = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent


def verificar_nova_versao(timeout=6) -> str | None:
    """Retorna a versao remota (string) se for diferente da instalada, ou
    None se estiver atualizado ou a checagem falhar (sem internet, GitHub
    fora do ar etc. - nunca trava o app por causa disso)."""
    try:
        req = urllib.request.Request(URL_RELEASE_API, headers={"Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=timeout, context=_CONTEXTO_SSL) as resp:
            dados = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None

    corpo = dados.get("body") or ""
    m = re.search(r"versao=([\w.\-]+)", corpo)
    if not m:
        return None
    versao_remota = m.group(1)
    return versao_remota if versao_remota != VERSAO_APP else None


def sincronizar_central_config(timeout=8) -> bool:
    """Busca a config do servidor central (config/central.local.json) num
    repo GitHub SEPARADO, privado, que so tem esse arquivo (sem codigo-fonte)
    - permite trocar o central (host/porta/senha) sem publicar build nova.

    So faz efeito na PROXIMA vez que o app abrir (config/central.py le o
    arquivo uma vez, no import) - roda aqui, junto da checagem de versao no
    login, porque e o mesmo momento natural de "puxar atualizacao". Sem
    FETCH_CONFIG (dev, ou instalacao antiga sem o arquivo) nao faz nada."""
    if FETCH_CONFIG is None:
        return False
    try:
        url = f"https://api.github.com/repos/{FETCH_CONFIG['repo']}/contents/central.local.json"
        req = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {FETCH_CONFIG['token']}",
        })
        with urllib.request.urlopen(req, timeout=timeout, context=_CONTEXTO_SSL) as resp:
            dados = json.loads(resp.read().decode("utf-8"))
        conteudo = base64.b64decode(dados["content"]).decode("utf-8")
        config_nova = json.loads(conteudo)  # valida que e JSON antes de gravar
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, KeyError, ValueError):
        return False

    destino = _PASTA_APP / "config" / "central.local.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(config_nova, f, indent=2)
    return True


def baixar_instalador(destino: str, timeout=120) -> None:
    req = urllib.request.Request(URL_INSTALADOR)
    with urllib.request.urlopen(req, timeout=timeout, context=_CONTEXTO_SSL) as resp:
        with open(destino, "wb") as f:
            while True:
                pedaco = resp.read(1024 * 256)
                if not pedaco:
                    break
                f.write(pedaco)


def instalar_e_sair() -> None:
    """Baixa o instalador mais novo pra uma pasta temporaria e o executa em
    modo silencioso, depois encerra o processo atual imediatamente.

    Antes de sair, para o Postgres embutido de forma limpa (pg_ctl stop) -
    senao o arquivo dele fica travado e o instalador falha, exatamente como
    aconteceu varias vezes hoje testando manualmente. Se este PC tambem
    estiver servindo o "modo celular" (processo separado, ver main.py), o
    proprio instalador (CloseApplications=force no setup.iss) cuida de
    fechar esse processo tambem - esse processo aqui nao tem como saber o
    PID dele."""
    caminho = os.path.join(tempfile.gettempdir(), "ADK_Fichas_Setup_update.exe")
    baixar_instalador(caminho)
    try:
        from db import postgres_local
        postgres_local.parar()
    except Exception:
        pass
    subprocess.Popen(
        [caminho, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
        creationflags=subprocess.CREATE_NO_WINDOW,
        close_fds=True,
    )
    os._exit(0)
