"""Configuracao local de cada PC (nao fica no banco, cada terminal tem a sua).

Guardada em %APPDATA%/SistemaChurrasco/config.json. Contem apenas o que e
especifico desta maquina: como achar o Postgres do servidor, qual impressora
Windows usar, e qual "caixa" este PC representa.
"""

import json
import os
import sys
from pathlib import Path

CONFIG_DIR = Path(os.getenv("APPDATA", str(Path.home()))) / "SistemaChurrasco"
CONFIG_PATH = CONFIG_DIR / "config.json"

# Pasta pra dados que o programa precisa GRAVAR em tempo de execucao (banco
# Postgres embutido, log, etc) - nunca pode ser dentro da pasta de instalacao
# (ex: "C:\Program Files\..."), porque o Windows bloqueia escrita ali pra
# usuario comum (so o instalador, rodando como admin, consegue escrever lá).
# %LOCALAPPDATA% e sempre gravavel pelo usuario atual, sem precisar elevar.
PASTA_DADOS_LOCAIS = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "SistemaChurrasco"

# Se existir um "config.default.json" do lado do executavel, ele e usado como
# ponto de partida no primeiro uso desta maquina (pensado pra builds que ja
# saem configuradas com a conexao de um cliente/demonstracao especifico).
_PASTA_EXECUTAVEL = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
CAMINHO_BOOTSTRAP = _PASTA_EXECUTAVEL / "config.default.json"


def pasta_assets() -> Path:
    """Onde ficam logo/icone: direto do lado do executavel em dev, ou dentro de
    _internal/ quando empacotado com PyInstaller (onde --add-data guarda os
    dados embutidos nas versoes mais recentes)."""
    for candidato in (_PASTA_EXECUTAVEL / "assets", _PASTA_EXECUTAVEL / "_internal" / "assets"):
        if candidato.exists():
            return candidato
    return _PASTA_EXECUTAVEL / "assets"

DEFAULTS = {
    "postgres": {
        "host": "",
        "port": 5432,
        "dbname": "sistemachurrasco",
        "user": "postgres",
        "password": "",
        # "disable" (rede local sem internet), "prefer" (tenta SSL, aceita sem) ou
        # "require" (provedores de Postgres na nuvem geralmente exigem isso)
        "sslmode": "prefer",
    },
    "impressora_windows": "",
    "caixa_nome": "",
    # "servidor": este PC sobe o Postgres embutido e os outros caixas conectam nele.
    # "cliente": este PC so conecta no IP de outro PC que esta como servidor.
    # None: ainda nao escolhido (pergunta na tela de abrir evento).
    "papel_rede": None,
}


def load() -> dict:
    # Preferir o config salvo pelo usuario em %APPDATA% quando existir (mesmo
    # em executavel empacotado). Se nao existir, usar o config.default.json
    # embarcado como ponto de partida (normalmente so nome do caixa/impressora
    # pre-preenchidos). Caso nenhum exista, retornar os DEFAULTS. A conexao com
    # o Postgres NUNCA vem daqui - e sempre resolvida pela escolha de papel de
    # rede (ver ui/screens/papel_rede.py e db/postgres_local.py).
    # "utf-8-sig" em vez de "utf-8": le normal se nao tiver BOM, e tambem
    # aceita se tiver (ex: alguem abriu o config.json no Notepad pra editar a
    # mao e salvou de novo - o Notepad grava BOM por padrao no Windows; com
    # "utf-8" simples isso quebrava o json.load com "Unexpected UTF-8 BOM" e
    # o app nem chegava a abrir a janela).
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        merged = json.loads(json.dumps(DEFAULTS))
        merged.update(data)
        merged["postgres"] = {**DEFAULTS["postgres"], **data.get("postgres", {})}
        return merged

    if CAMINHO_BOOTSTRAP.exists():
        with open(CAMINHO_BOOTSTRAP, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        merged = json.loads(json.dumps(DEFAULTS))
        merged.update(data)
        merged["postgres"] = {**DEFAULTS["postgres"], **data.get("postgres", {})}
        return merged

    return json.loads(json.dumps(DEFAULTS))


def save(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_configured(data: dict | None = None) -> bool:
    data = data or load()
    pg = data.get("postgres", {})
    return bool(pg.get("host")) and bool(data.get("caixa_nome"))
