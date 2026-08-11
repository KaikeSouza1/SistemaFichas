"""Sincronizacao em segundo plano: manda o historico de eventos FECHADOS deste
PC pro servidor central fixo (config/central.py), sempre que achar internet.

Nunca bloqueia o app - roda numa thread separada, tenta pra sempre (mesmo que
demore dias pra achar conexao, ex: evento no meio do nada), e nunca escreve
nada de volta no banco local: e so upload de historico, uma via.
"""

import threading
import time
import traceback
import uuid
from decimal import Decimal

import psycopg
from psycopg.types.json import Jsonb

from config.central import CENTRAL
from config.settings import PASTA_DADOS_LOCAIS
from db import repository

INTERVALO_SEGUNDOS = 120

_ARQUIVO_ORIGEM = PASTA_DADOS_LOCAIS / "origem_uuid.txt"


def _origem_uuid() -> str:
    """Identidade fixa deste PC/instalacao - gerada uma unica vez, usada pra
    nao colidir com o historico de outros PCs quando os dados chegam no central."""
    _ARQUIVO_ORIGEM.parent.mkdir(parents=True, exist_ok=True)
    if _ARQUIVO_ORIGEM.exists():
        return _ARQUIVO_ORIGEM.read_text(encoding="utf-8").strip()
    novo = str(uuid.uuid4())
    _ARQUIVO_ORIGEM.write_text(novo, encoding="utf-8")
    return novo


def _serializar(valor):
    if isinstance(valor, dict):
        return {k: _serializar(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_serializar(v) for v in valor]
    if isinstance(valor, Decimal):
        return float(valor)
    if hasattr(valor, "isoformat"):
        return valor.isoformat()
    return valor


def _garantir_schema_central(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """CREATE TABLE IF NOT EXISTS eventos_sincronizados (
                id SERIAL PRIMARY KEY,
                origem_uuid UUID NOT NULL,
                evento_local_id INTEGER NOT NULL,
                nome_evento TEXT NOT NULL,
                data_abertura TIMESTAMPTZ,
                data_fechamento TIMESTAMPTZ,
                dados JSONB NOT NULL,
                sincronizado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (origem_uuid, evento_local_id)
            )"""
        )
    conn.commit()


def _dsn_central() -> str:
    return (
        f"host={CENTRAL['host']} port={CENTRAL['port']} dbname={CENTRAL['dbname']} "
        f"user={CENTRAL['user']} password={CENTRAL['password']} connect_timeout=10 "
        f"sslmode={CENTRAL['sslmode']}"
    )


def _enviar_para_central(origem_uuid: str, evento_id: int, dump: dict) -> None:
    with psycopg.connect(_dsn_central()) as conn:
        _garantir_schema_central(conn)
        evento = dump["evento"]
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO eventos_sincronizados
                   (origem_uuid, evento_local_id, nome_evento, data_abertura, data_fechamento, dados)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (origem_uuid, evento_local_id)
                   DO UPDATE SET dados = EXCLUDED.dados, sincronizado_em = now()""",
                (origem_uuid, evento_id, evento["nome"], evento["data_abertura"], evento["data_fechamento"],
                 Jsonb(_serializar(dump))),
            )
        conn.commit()


def ciclo() -> int:
    """Roda uma passada: tenta mandar todos os eventos fechados pendentes.
    Retorna quantos eventos foram sincronizados com sucesso. Se o central nao
    estiver configurado nesta instalacao (sem config/central.local.json), nao
    faz nada - o evento fica pendente e sera enviado quando/se configurado."""
    if CENTRAL is None:
        return 0
    origem = _origem_uuid()
    pendentes = repository.eventos_fechados_pendentes_sync()
    enviados = 0
    for evento in pendentes:
        dump = repository.dump_evento_completo(evento["id"])
        _enviar_para_central(origem, evento["id"], dump)
        repository.marcar_evento_sincronizado(evento["id"])
        enviados += 1
    return enviados


def iniciar_em_background() -> None:
    """Sobe a thread de sync. Chamar uma vez, no inicio do app. Falhas (sem
    internet, central fora do ar) nunca derrubam a thread - so tenta de novo
    depois de INTERVALO_SEGUNDOS, indefinidamente."""

    def loop():
        while True:
            try:
                enviados = ciclo()
                if enviados:
                    print(f"[sync] {enviados} evento(s) sincronizado(s) com o central.")
            except Exception:
                traceback.print_exc()
            time.sleep(INTERVALO_SEGUNDOS)

    threading.Thread(target=loop, daemon=True, name="sync-central").start()
