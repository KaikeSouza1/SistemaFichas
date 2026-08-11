"""Verifica se tem uma build mais nova publicada no GitHub Releases e, se o
usuario topar, baixa e instala sozinho.

So funciona no .exe empacotado de verdade (rodando com `python main.py` em
dev nao faz sentido se auto-atualizar). Nao depende de git/commit nenhum -
so le o release ja existente via API publica (sem token, o repo e publico).
"""

import json
import os
import re
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

import certifi

from config.versao import URL_INSTALADOR, URL_RELEASE_API, VERSAO_APP

_CONTEXTO_SSL = ssl.create_default_context(cafile=certifi.where())


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
