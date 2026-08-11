import os
import subprocess
import sys

# No .exe empacotado sem console (ver setup do PyInstaller), sys.stdout/stderr
# sao None de verdade, nao so "sem terminal" - qualquer biblioteca que tente
# usar eles (ex: uvicorn, usado pelo servidor do modo celular) quebra com
# AttributeError. Precisa vir ANTES de importar flet/uvicorn.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

_FLAG_SERVIDOR_CELULAR = "--modo-celular-servidor"


def _rodar_servidor_celular():
    """So o servidor web do modo celular, sem janela nenhuma - roda como um
    PROCESSO SEPARADO (nao thread) do app principal, pra nunca interferir na
    janela desktop (que continua 100% no fluxo padrao do Flet, sempre
    confiavel)."""
    import asyncio

    from config import settings
    from db import modo_celular
    from ui.app import main as app_main

    async def servir():
        from flet.fastapi.serve_fastapi_web_app import serve_fastapi_web_app

        await serve_fastapi_web_app(
            session_handler=app_main,
            host="0.0.0.0",
            url_host="0.0.0.0",
            port=modo_celular.PORTA_WEB,
            page_name="",
            assets_dir=str(settings.pasta_assets()),
            upload_dir=None,
            web_renderer=None,
            use_color_emoji=False,
            route_url_strategy="path",
            blocking=True,
            on_startup=None,
            log_level="warning",
        )

    asyncio.run(servir())


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == _FLAG_SERVIDOR_CELULAR:
        _rodar_servidor_celular()
        sys.exit(0)

    import flet as ft

    from config import settings
    from db import modo_celular
    from ui.app import main

    cfg = settings.load()
    if cfg.get("papel_rede") == "servidor":
        modo_celular.liberar_firewall()
        # No .exe empacotado, sys.executable JA E o proprio "ADK Fichas.exe"
        # (o main.py fica embutido nele) - so em dev (python main.py) precisa
        # passar o caminho do script tambem, senao o python abriria so um
        # interpretador vazio.
        if getattr(sys, "frozen", False):
            args_servidor = [sys.executable, _FLAG_SERVIDOR_CELULAR]
        else:
            args_servidor = [sys.executable, __file__, _FLAG_SERVIDOR_CELULAR]
        subprocess.Popen(
            args_servidor,
            creationflags=subprocess.CREATE_NO_WINDOW,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
        )

    ft.app(target=main, assets_dir=str(settings.pasta_assets()))
