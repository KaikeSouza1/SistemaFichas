"""Pecas de UI reaproveitadas entre telas: dialogos de erro/confirmacao e
teclado numerico (pensado pra uso touch, sem precisar de teclado fisico)."""

import flet as ft

from ui import theme


def fechar_dialogo(page: ft.Page, dlg: ft.AlertDialog):
    """Fecha `dlg`. NUNCA abrir um `ft.AlertDialog` novo por CIMA de outro já
    aberto reatribuindo `page.dialog` (e tentar "restaurar" o de baixo depois
    trocando `page.dialog` de volta) - no Flet isso "solta" o dialogo de
    baixo de um jeito que reatribuir de volta NÃO remonta os manipuladores de
    clique corretamente: os botões ficam mortos (nenhum clique faz nada) -
    bug real reportado pelo usuário (2026-08-11) depois de usar "Pré-visualizar
    ficha" no módulo Churrasco. Se precisar mostrar algo "por cima" de um
    dialogo que já está aberto, use um painel alternando `visible=True/False`
    DENTRO do mesmo `ft.AlertDialog` (ver `ui/screens/churrasco.py`,
    `abrir_dialogo_venda`/`abrir_busca_fichas` - nenhum dos dois reatribui
    `page.dialog` mais de uma vez)."""
    dlg.open = False
    page.update()


def dialogo_erro_conexao(page: ft.Page, tentar_de_novo=None):
    acoes = []
    if tentar_de_novo:
        acoes.append(
            ft.ElevatedButton(
                "Tentar novamente",
                on_click=lambda e: (fechar_dialogo(page, dlg), tentar_de_novo()),
                style=ft.ButtonStyle(bgcolor=theme.BRASA, color=theme.TEXTO),
            )
        )
    else:
        acoes.append(ft.TextButton("Fechar", on_click=lambda e: fechar_dialogo(page, dlg)))

    dlg = ft.AlertDialog(
        modal=True,
        bgcolor=theme.SURFACE,
        icon=ft.Icon(ft.icons.WIFI_OFF, color=theme.ERRO, size=40),
        title=ft.Text("Sem conexão com o servidor", color=theme.TEXTO),
        content=ft.Text(
            "Não foi possível falar com o Postgres do caixa servidor.\n"
            "Confira o cabo de rede e o PC servidor, depois tente de novo.",
            color=theme.TEXTO_SUAVE,
        ),
        actions=acoes,
    )
    page.dialog = dlg
    dlg.open = True
    page.update()


def dialogo_confirmacao(page: ft.Page, titulo: str, mensagem: str, ao_confirmar, texto_confirmar="Confirmar"):
    def confirmar(e):
        fechar_dialogo(page, dlg)
        ao_confirmar()

    dlg = ft.AlertDialog(
        modal=True,
        bgcolor=theme.SURFACE,
        title=ft.Text(titulo, color=theme.TEXTO),
        content=ft.Text(mensagem, color=theme.TEXTO_SUAVE),
        actions=[
            ft.TextButton("Cancelar", on_click=lambda e: fechar_dialogo(page, dlg)),
            ft.ElevatedButton(
                texto_confirmar, on_click=confirmar,
                style=ft.ButtonStyle(bgcolor=theme.BRASA, color=theme.TEXTO),
            ),
        ],
    )
    page.dialog = dlg
    dlg.open = True
    page.update()


def tela_estado_erro(mensagem: str, ao_tentar_de_novo) -> ft.Control:
    """Tela cheia usada quando o carregamento inicial de uma tela falha por
    falta de conexao com o servidor (nao e um dialogo, e a tela toda)."""
    return ft.Container(
        content=ft.Column(
            [
                ft.Icon(ft.icons.WIFI_OFF, color=theme.ERRO, size=64),
                ft.Text("Sem conexão com o servidor", size=20, weight=ft.FontWeight.W_700, color=theme.TEXTO),
                ft.Text(mensagem, size=14, color=theme.TEXTO_SUAVE, text_align=ft.TextAlign.CENTER),
                ft.Container(height=12),
                theme.botao_primario("Tentar novamente", icone=ft.icons.REFRESH, on_click=lambda e: ao_tentar_de_novo()),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=10,
        ),
        alignment=ft.alignment.center,
        expand=True,
        bgcolor=theme.BG,
    )


def aviso(page: ft.Page, mensagem: str, cor=theme.SUCESSO):
    page.snack_bar = ft.SnackBar(
        content=ft.Text(mensagem, color=theme.TEXTO),
        bgcolor=cor,
        duration=2500,
    )
    page.snack_bar.open = True
    page.update()


def teclado_numerico(campo: ft.TextField, page: ft.Page, on_enter=None, max_len: int = 6) -> ft.Control:
    def digitar(valor):
        def handler(e):
            if len(campo.value or "") < max_len:
                campo.value = (campo.value or "") + valor
                campo.update()
        return handler

    def apagar(e):
        campo.value = (campo.value or "")[:-1]
        campo.update()

    def limpar(e):
        campo.value = ""
        campo.update()

    def botao(txt, on_click, cor_fundo=theme.SURFACE_ALTA, cor_texto=theme.TEXTO):
        return ft.Container(
            content=ft.Text(txt, size=22, weight=ft.FontWeight.W_600, color=cor_texto),
            width=72,
            height=64,
            bgcolor=cor_fundo,
            border_radius=theme.RADIUS,
            alignment=ft.alignment.center,
            ink=True,
            on_click=on_click,
        )

    linhas = [
        ["1", "2", "3"],
        ["4", "5", "6"],
        ["7", "8", "9"],
    ]
    grade = ft.Column(
        [ft.Row([botao(d, digitar(d)) for d in linha], spacing=10) for linha in linhas]
        + [
            ft.Row(
                [
                    botao("C", limpar, cor_fundo=theme.SURFACE, cor_texto=theme.ERRO),
                    botao("0", digitar("0")),
                    botao("⌫", apagar, cor_fundo=theme.SURFACE, cor_texto=theme.ALERTA),
                ],
                spacing=10,
            )
        ],
        spacing=10,
    )
    return grade
