import flet as ft

from db import repository
from db.connection import ConexaoIndisponivel
from ui import componentes, theme


def tela(page: ft.Page, estado, ao_autenticar, ao_tentar_de_novo, ao_abrir_configuracao) -> ft.Control:
    try:
        operadores = repository.listar_operadores()
    except ConexaoIndisponivel:
        return componentes.tela_estado_erro(
            "Não deu para carregar a lista de operadores.", ao_tentar_de_novo
        )

    selecionado = {"id": None, "nome": None}
    campo_pin = ft.TextField(
        value="", password=True, can_reveal_password=True, text_align=ft.TextAlign.CENTER,
        keyboard_type=ft.KeyboardType.NUMBER, autofocus=True, height=56, width=220, text_size=26,
        border_color=theme.BORDA, focused_border_color=theme.BRASA, bgcolor=theme.SURFACE_ALTA,
    )
    area_pin = ft.Container(visible=False)
    texto_erro = ft.Text("", color=theme.ERRO, size=13)

    def escolher_operador(op):
        def handler(e):
            selecionado["id"] = op["id"]
            selecionado["nome"] = op["nome"]
            campo_pin.value = ""
            texto_erro.value = ""
            titulo_pin.value = f"PIN de {op['nome']}"
            area_pin.visible = True
            page.update()
        return handler

    def confirmar_pin(e):
        try:
            resultado = repository.autenticar_operador(selecionado["id"], campo_pin.value)
        except ConexaoIndisponivel:
            componentes.dialogo_erro_conexao(page, tentar_de_novo=lambda: ao_tentar_de_novo())
            return
        if not resultado:
            texto_erro.value = "PIN incorreto."
            campo_pin.value = ""
            page.update()
            return
        estado.operador_id = resultado["id"]
        estado.operador_nome = resultado["nome"]
        ao_autenticar()

    campo_pin.on_submit = confirmar_pin

    titulo_pin = ft.Text("", size=16, weight=ft.FontWeight.W_600, color=theme.TEXTO)
    area_pin.content = theme.cartao(
        ft.Column(
            [
                titulo_pin,
                campo_pin,
                componentes.teclado_numerico(campo_pin, page),
                texto_erro,
                ft.Row(
                    [
                        theme.botao_secundario("Cancelar", on_click=lambda e: cancelar_selecao(e)),
                        theme.botao_primario("Entrar", on_click=confirmar_pin, icone=ft.icons.LOGIN),
                    ],
                    spacing=10,
                ),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=14,
        ),
        padding=28,
    )

    def cancelar_selecao(e):
        selecionado["id"] = None
        area_pin.visible = False
        page.update()

    botoes_operador = ft.Row(
        [
            ft.Container(
                content=ft.Column(
                    [
                        ft.Icon(ft.icons.PERSON, color=theme.BRASA_CLARA, size=30),
                        ft.Text(op["nome"], color=theme.TEXTO, weight=ft.FontWeight.W_600, size=15),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=6,
                ),
                width=140,
                height=110,
                bgcolor=theme.SURFACE,
                border=ft.border.all(1, theme.BORDA),
                border_radius=theme.RADIUS,
                alignment=ft.alignment.center,
                ink=True,
                on_click=escolher_operador(op),
            )
            for op in operadores
        ],
        wrap=True,
        spacing=14,
        run_spacing=14,
        alignment=ft.MainAxisAlignment.CENTER,
    )

    return ft.Container(
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Text(f"Caixa: {estado.caixa_nome}", color=theme.TEXTO_SUAVE, size=13),
                        ft.TextButton(
                            "Configurações", icon=ft.icons.SETTINGS,
                            on_click=lambda e: ao_abrir_configuracao(),
                            style=ft.ButtonStyle(color=theme.TEXTO_SUAVE),
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                ft.Container(expand=True),
                ft.Icon(ft.icons.LOCAL_FIRE_DEPARTMENT, color=theme.BRASA, size=48),
                theme.titulo("Quem está operando?", tamanho=26),
                ft.Container(height=8),
                botoes_operador,
                ft.Container(height=20),
                area_pin,
                ft.Container(expand=True),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=16,
            expand=True,
        ),
        padding=30,
        bgcolor=theme.BG,
        expand=True,
    )
