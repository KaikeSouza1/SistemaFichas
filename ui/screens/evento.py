import flet as ft

from db import repository
from db.connection import ConexaoIndisponivel
from ui import componentes, theme


def tela_abrir(page: ft.Page, ao_abrir, ao_tentar_de_novo, ao_ver_relatorios=None, ao_abrir_configuracao=None) -> ft.Control:
    """Gate de inicio: sem evento aberto, ninguem vende. Cria o primeiro
    evento (a festa de hoje) antes de liberar login/venda.

    `ao_ver_relatorios` (opcional) e um jeito de sair dessa tela sem criar um
    evento novo - pedido do usuario: fechar um evento sempre volta pra esse
    gate, e antes disso nao tinha NENHUM jeito de so consultar o
    historico/relatorios de eventos ja fechados sem ser obrigado a abrir mais
    um evento primeiro. `relatorios.tela()` ja suporta escolher entre todos
    os eventos (abertos e fechados) - nao depende de operador logado nem de
    evento aberto, so precisava de um caminho pra chegar nela daqui.

    `ao_abrir_configuracao` (opcional, icone de engrenagem no canto) e pela
    MESMA razao: "Modo de rede deste PC" (trocar servidor/cliente) fica em
    Configuracoes, mas Configuracoes so era alcancavel logando - e logar so
    era possivel com evento aberto. Um notebook que foi servidor ontem e
    precisa virar cliente hoje (outro evento, outro PC principal) ficava sem
    nenhum jeito de trocar isso se o evento de ontem ja tinha sido fechado -
    exatamente o cenario relatado pelo usuario."""
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

    conteudo_central = ft.Container(
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
                (theme.botao_secundario("Ver relatórios de eventos anteriores", icone=ft.icons.BAR_CHART,
                                        on_click=lambda e: ao_ver_relatorios(), largura=280)
                 if ao_ver_relatorios else ft.Container()),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=18,
            alignment=ft.MainAxisAlignment.CENTER, expand=True,
        ),
        alignment=ft.alignment.center, bgcolor=theme.BG, expand=True,
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
