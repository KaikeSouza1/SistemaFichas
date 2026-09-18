"""Credencial pra buscar config/central.local.json atualizado de um repo
GitHub SEPARADO (so esse arquivo, sem codigo-fonte nenhum - ver
db/atualizacao.py:sincronizar_central_config). Permite trocar o servidor
central (host/porta/senha) sem precisar publicar uma build nova do app.

Mesma logica de config/central.py: os dados reais NAO ficam neste arquivo
(versionado/publico) - ficam em config/central_fetch.local.json, gitignored,
ao lado deste arquivo em dev ou ao lado do executavel quando empacotado.
Sem esse arquivo, a busca so fica sem efeito (usa o que ja tiver local).
"""

import json
import sys
from pathlib import Path

_PASTA_APP = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
_CANDIDATOS = [
    Path(__file__).resolve().parent / "central_fetch.local.json",
    _PASTA_APP / "config" / "central_fetch.local.json",
    _PASTA_APP / "central_fetch.local.json",
]


def _carregar() -> dict | None:
    for caminho in _CANDIDATOS:
        if caminho.exists():
            with open(caminho, "r", encoding="utf-8") as f:
                return json.load(f)
    return None


FETCH_CONFIG = _carregar()
