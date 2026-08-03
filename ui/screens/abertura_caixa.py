import flet as ft

from db import repository
from db.connection import ConexaoIndisponivel
from ui import componentes, theme


def tela(page: ft.Page, estado, ao_abrir, ao_tentar_de_novo) -> ft.Control:
    campo_valor = theme.campo_texto(
        "Valor de abertura (R$)", value="0,00", text_align=ft.TextAlign.CENTER,
        width=220, text_size=24, autofocus=True,
    )
    texto_erro = ft.Text("", color=theme.ERRO, size=13)

    def confirmar(e):
        try:
            valor = float(campo_valor.value.replace(".", "").replace(",", "."))
        except ValueError:
            texto_erro.value = "Valor inválido."
            page.update()
            return
        try:
            sessao_id = repository.abrir_sessao(estado.evento_id, estado.caixa_id, estado.operador_id, valor)
        except ConexaoIndisponivel:
            componentes.dialogo_erro_conexao(page, tentar_de_novo=lambda: ao_tentar_de_novo())
            return
        estado.sessao_id = sessao_id
        ao_abrir()

    return ft.Container(
        content=ft.Column(
            [
                ft.Icon(ft.icons.POINT_OF_SALE, color=theme.BRASA, size=48),
                theme.titulo("Abertura de caixa", tamanho=26),
                theme.subtitulo(f"{estado.caixa_nome} · Operador: {estado.operador_nome}"),
                ft.Container(height=10),
                theme.cartao(
                    ft.Column(
                        [
                            ft.Text("Quanto tem de fundo de caixa (dinheiro) agora?", color=theme.TEXTO_SUAVE),
                            campo_valor,
                            texto_erro,
                            theme.botao_primario("Abrir caixa", icone=ft.icons.LOCK_OPEN, on_click=confirmar, largura=220),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=16,
                    ),
                    padding=30,
                ),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=18,
            alignment=ft.MainAxisAlignment.CENTER,
            expand=True,
        ),
        alignment=ft.alignment.center,
        bgcolor=theme.BG,
        expand=True,
    )
