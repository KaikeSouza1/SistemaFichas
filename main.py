import flet as ft

from config import settings
from ui.app import main

if __name__ == "__main__":
    ft.app(target=main, assets_dir=str(settings.pasta_assets()))
