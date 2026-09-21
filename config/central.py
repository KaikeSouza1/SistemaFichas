"""Servidor central fixo: destino de sincronizacao de TODOS os eventos, de
TODOS os PCs, de TODAS as cidades. Fixo de proposito - nao aparece em nenhuma
tela de configuracao, o usuario/operador nunca ve nem edita isso.

So recebe dados DEPOIS que um evento e fechado (ver db/sync.py). Nunca e
usado durante a operacao normal do evento - quem roda o evento e o Postgres
local (embutido) do PC principal daquele evento (ver db/postgres_local.py).

As credenciais reais NAO ficam neste arquivo (que e versionado/publico) - ficam
em config/central.local.json, gitignored, ao lado deste arquivo em dev ou ao
lado do executavel quando empacotado. Sem esse arquivo, o sync so fica sem
efeito (loga e tenta de novo depois) em vez de vazar segredo no codigo-fonte.

O candidato em PASTA_DADOS_LOCAIS (%LOCALAPPDATA%) vem PRIMEIRO de proposito:
e onde db/atualizacao.py:sincronizar_central_config() grava a versao mais
recente buscada do GitHub em tempo de execucao (unico lugar gravavel por um
usuario comum sem admin - "C:/Program Files/..." nao e). Se existir, sempre
vence o bootstrap fixo que veio junto do instalador.
"""

import json
import sys
from pathlib import Path

from config.settings import PASTA_DADOS_LOCAIS

_PASTA_APP = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
_CANDIDATOS = [
    PASTA_DADOS_LOCAIS / "central.local.json",
    Path(__file__).resolve().parent / "central.local.json",
    _PASTA_APP / "config" / "central.local.json",
    _PASTA_APP / "central.local.json",
]


def _carregar() -> dict | None:
    for caminho in _CANDIDATOS:
        if caminho.exists():
            with open(caminho, "r", encoding="utf-8") as f:
                return json.load(f)
    return None


CENTRAL = _carregar()
