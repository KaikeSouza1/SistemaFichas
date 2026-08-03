"""Identidade visual do SistemaChurrasco.

Paleta propria (brasa/churrasco: carvao, terracota, brasa), nao o azul/roxo
padrao de template. Reaproveitada em todas as telas para manter consistencia.
"""

import flet as ft

# ---------- Paleta ----------
BG = "#171412"           # fundo principal (carvao quase preto, bom pra ambiente noturno)
SURFACE = "#221E1A"      # cards/paineis
SURFACE_ALTA = "#2C2621"  # cards elevados/hover
BORDA = "#3A322B"

BRASA = "#E2662D"        # cor de destaque principal (laranja-brasa)
BRASA_ESCURA = "#B84F1F"
BRASA_CLARA = "#F08A4B"

SUCESSO = "#4F9D63"
ALERTA = "#D9A82E"
ERRO = "#D1483B"

TEXTO = "#F3ECE3"        # texto principal (branco quente)
TEXTO_SUAVE = "#B4A99C"  # texto secundario
TEXTO_FRACO = "#7C7268"

RADIUS = 14
RADIUS_GRANDE = 20
ESPACO = 12


def aplicar(page: ft.Page) -> None:
    page.title = "ADK Fichas"
    page.bgcolor = BG
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 0
    page.window_min_width = 1024
    page.window_min_height = 700
    page.window_maximized = True
    # A janela nativa (processo flet.exe) tem seu proprio icone embutido, que
    # NAO e trocado so por passar --icon no PyInstaller (isso so troca o icone
    # do .exe em si, visto no Explorer) - sem isso aqui a barra de tarefas
    # mostra o icone padrao do Flet em vez do logo de fogo.
    page.window.icon = "icon.ico"
    page.theme = ft.Theme(
        color_scheme=ft.ColorScheme(
            primary=BRASA,
            on_primary=TEXTO,
            surface=SURFACE,
            on_surface=TEXTO,
            background=BG,
        ),
        font_family="Segoe UI",
    )


def cartao(*controles, cor_fundo: str = SURFACE, padding: int = 20, radius: int = RADIUS, **kwargs) -> ft.Container:
    return ft.Container(
        content=ft.Column(controles, spacing=ESPACO, tight=True) if len(controles) != 1 else controles[0],
        bgcolor=cor_fundo,
        border_radius=radius,
        padding=padding,
        border=ft.border.all(1, BORDA),
        **kwargs,
    )


def botao_primario(texto: str, on_click=None, icone: str | None = None, largura: int | None = None, altura: int = 52, expand=False) -> ft.ElevatedButton:
    return ft.ElevatedButton(
        text=texto,
        icon=icone,
        on_click=on_click,
        width=largura,
        height=altura,
        expand=expand,
        style=ft.ButtonStyle(
            bgcolor={"": BRASA, "hovered": BRASA_CLARA, "disabled": BORDA},
            color={"": TEXTO, "disabled": TEXTO_FRACO},
            shape=ft.RoundedRectangleBorder(radius=RADIUS),
            elevation={"": 0},
            text_style=ft.TextStyle(size=16, weight=ft.FontWeight.W_600),
        ),
    )


def botao_secundario(texto: str, on_click=None, icone: str | None = None, largura: int | None = None, altura: int = 48, expand=False) -> ft.OutlinedButton:
    return ft.OutlinedButton(
        text=texto,
        icon=icone,
        on_click=on_click,
        width=largura,
        height=altura,
        expand=expand,
        style=ft.ButtonStyle(
            color={"": TEXTO, "hovered": BRASA_CLARA},
            side={"": ft.BorderSide(1, BORDA), "hovered": ft.BorderSide(1, BRASA)},
            shape=ft.RoundedRectangleBorder(radius=RADIUS),
        ),
    )


def botao_perigo(texto: str, on_click=None, icone: str | None = None, expand=False) -> ft.OutlinedButton:
    return ft.OutlinedButton(
        text=texto,
        icon=icone,
        on_click=on_click,
        expand=expand,
        style=ft.ButtonStyle(
            color={"": ERRO},
            side={"": ft.BorderSide(1, ERRO)},
            shape=ft.RoundedRectangleBorder(radius=RADIUS),
        ),
    )


def campo_texto(label: str, **kwargs) -> ft.TextField:
    return ft.TextField(
        label=label,
        border_radius=RADIUS,
        border_color=BORDA,
        focused_border_color=BRASA,
        label_style=ft.TextStyle(color=TEXTO_SUAVE),
        text_style=ft.TextStyle(color=TEXTO),
        cursor_color=BRASA,
        bgcolor=SURFACE_ALTA,
        **kwargs,
    )


def titulo(texto: str, tamanho: int = 22) -> ft.Text:
    return ft.Text(texto, size=tamanho, weight=ft.FontWeight.W_700, color=TEXTO)


def subtitulo(texto: str, tamanho: int = 14) -> ft.Text:
    return ft.Text(texto, size=tamanho, color=TEXTO_SUAVE)
