import flet as ft

from db import repository
from db.connection import ConexaoIndisponivel
from ui import componentes, theme


def tela(page: ft.Page, estado, ao_abrir, ao_tentar_de_novo, ao_abrir_configuracao=None) -> ft.Control:
    """`ao_abrir_configuracao` (opcional, icone de engrenagem no canto) - o
    operador ja autenticou (PIN) pra chegar aqui, mas antes so dava pra
    alcancar Configuracoes (Evento/Operadores incluidos) abrindo um caixa
    novo primeiro e so depois clicando no botao de dentro da tela de venda.
    Pedido real do usuario (2026-08-19, audio): ele queria só FECHAR o
    evento (Configuracoes > Evento) sem precisar abrir um caixa novo so pra
    chegar la - mesma logica do atalho ja usado em evento.tela_abrir()."""
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

    conteudo_central = ft.Container(
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
    if not ao_abrir_configuracao:
        return conteudo_central

    return ft.Stack(
        [
            conteudo_central,
            ft.Container(
                content=ft.IconButton(ft.icons.SETTINGS, icon_color=theme.TEXTO_SUAVE, tooltip="Configurações",
                                       on_click=lambda e: ao_abrir_configuracao()),
                top=16, right=16,
            ),
        ],
        expand=True,
    )
