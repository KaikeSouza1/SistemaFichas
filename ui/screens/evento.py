import flet as ft

from db import repository
from db.connection import ConexaoIndisponivel
from ui import componentes, theme


def tela_abrir(page: ft.Page, ao_abrir, ao_tentar_de_novo) -> ft.Control:
    """Gate de inicio: sem evento aberto, ninguem vende. Cria o primeiro
    evento (a festa de hoje) antes de liberar login/venda."""
    campo_nome = theme.campo_texto("Nome do evento (ex: Festa Junina 2026)", width=360, autofocus=True)
    campo_rodape = theme.campo_texto("Rodapé das fichas (opcional)", width=360)
    texto_erro = ft.Text("", color=theme.ERRO, size=13)

    def confirmar(e):
        if not campo_nome.value.strip():
            texto_erro.value = "Dá um nome pro evento."
            page.update()
            return
        try:
            repository.criar_evento(campo_nome.value.strip(), campo_rodape.value.strip())
        except ConexaoIndisponivel:
            componentes.dialogo_erro_conexao(page, tentar_de_novo=lambda: ao_tentar_de_novo())
            return
        ao_abrir()

    return ft.Container(
        content=ft.Column(
            [
                ft.Icon(ft.icons.CELEBRATION, color=theme.BRASA, size=48),
                theme.titulo("Nenhum evento aberto", tamanho=26),
                theme.subtitulo("Antes de vender, abra o evento (a festa de hoje)."),
                ft.Container(height=10),
                theme.cartao(
                    ft.Column(
                        [campo_nome, campo_rodape, texto_erro,
                         theme.botao_primario("Abrir evento", icone=ft.icons.PLAY_ARROW, on_click=confirmar, largura=200)],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=16,
                    ),
                    padding=30,
                ),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=18,
            alignment=ft.MainAxisAlignment.CENTER, expand=True,
        ),
        alignment=ft.alignment.center, bgcolor=theme.BG, expand=True,
    )
