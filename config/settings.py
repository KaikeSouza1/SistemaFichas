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

# Se existir um "config.default.json" do lado do executavel, ele e usado como
# ponto de partida no primeiro uso desta maquina (pensado pra builds que ja
# saem configuradas com a conexao de um cliente/demonstracao especifico).
_PASTA_EXECUTAVEL = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
CAMINHO_BOOTSTRAP = _PASTA_EXECUTAVEL / "config.default.json"

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
    # embarcado como ponto de partida. Caso nenhum exista, retornar os DEFAULTS.
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged = json.loads(json.dumps(DEFAULTS))
        merged.update(data)
        merged["postgres"] = {**DEFAULTS["postgres"], **data.get("postgres", {})}
        # Migracao unica de configs salvas ANTES da tela de escolha de papel de
        # rede existir: se ja tinha host preenchido manualmente, respeita isso
        # e nao interrompe o fluxo perguntando de novo. So roda uma vez (depois
        # "papel_rede" passa a existir de verdade no arquivo, ainda que None).
        if "papel_rede" not in data and merged["postgres"].get("host"):
            merged["papel_rede"] = "manual"
            save(merged)
        return merged

    if CAMINHO_BOOTSTRAP.exists():
        with open(CAMINHO_BOOTSTRAP, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged = json.loads(json.dumps(DEFAULTS))
        merged.update(data)
        merged["postgres"] = {**DEFAULTS["postgres"], **data.get("postgres", {})}
        if "papel_rede" not in data and merged["postgres"].get("host"):
            merged["papel_rede"] = "manual"
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
