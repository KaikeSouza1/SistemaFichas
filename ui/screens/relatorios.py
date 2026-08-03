import flet as ft

from db import repository
from db.connection import ConexaoIndisponivel
from ui import componentes, theme


def tela(page: ft.Page, ao_voltar) -> ft.Control:
    try:
        eventos = repository.listar_eventos()
    except ConexaoIndisponivel:
        return componentes.tela_estado_erro("Não deu para carregar os eventos.", lambda: None)

    corpo = ft.Column(spacing=16, expand=True, scroll=ft.ScrollMode.AUTO)

    def carregar(evento_id):
        try:
            mais_vendidos = repository.produtos_mais_vendidos(evento_id)
            por_operador = repository.vendas_por_operador(evento_id)
            por_caixa = repository.vendas_por_caixa(evento_id)
            excluidos = repository.itens_excluidos_por_evento(evento_id)
        except ConexaoIndisponivel:
            corpo.controls = [componentes.tela_estado_erro("Não deu para carregar os relatórios.", lambda: carregar(evento_id))]
            corpo.update()
            return

        corpo.controls = [
            ft.Row(
                [
                            _cartao_ranking(page, "Produtos mais vendidos", mais_vendidos, "nome_produto", "quantidade", "total"),
                            _cartao_ranking(page, "Vendas por operador", por_operador, "nome", "qtd_vendas", "total"),
                            _cartao_ranking(page, "Vendas por caixa", por_caixa, "nome", "qtd_vendas", "total"),
                ],
                spacing=16, expand=True, vertical_alignment=ft.CrossAxisAlignment.START,
            ),
            ft.Row(
                [_cartao_ranking(page, "Itens excluídos do carrinho", excluidos, "nome_produto", "quantidade", "total")],
                spacing=16, expand=True, vertical_alignment=ft.CrossAxisAlignment.START,
            ),
        ]
        corpo.update()

    def mudar_evento(e):
        valor = dropdown_evento.value
        carregar(None if valor == "todos" else int(valor))

    opcoes = [ft.dropdown.Option("todos", "Todos os eventos")] + [
        ft.dropdown.Option(str(ev["id"]), f"{ev['nome']} ({'aberto' if ev['status'] == 'ABERTA' else 'fechado'})")
        for ev in eventos
    ]
    valor_inicial = str(eventos[0]["id"]) if eventos and eventos[0]["status"] == "ABERTA" else "todos"
    dropdown_evento = ft.Dropdown(
        value=valor_inicial, width=280, options=opcoes,
        border_color=theme.BORDA, focused_border_color=theme.BRASA, bgcolor=theme.SURFACE_ALTA,
        on_change=mudar_evento,
    )

    carregar(None if valor_inicial == "todos" else int(valor_inicial))

    return ft.Container(
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Row([ft.IconButton(ft.icons.ARROW_BACK, icon_color=theme.TEXTO, on_click=lambda e: ao_voltar()),
                                ft.Icon(ft.icons.BAR_CHART, color=theme.BRASA), theme.titulo("Relatórios", tamanho=22)], spacing=8),
                        dropdown_evento,
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                corpo,
            ],
            spacing=18, expand=True,
        ),
        padding=24, bgcolor=theme.BG, expand=True,
    )


def _cartao_ranking(page, titulo, linhas, campo_nome, campo_qtd, campo_total):
    itens = []

    def mostrar_detalle(linha):
        # mostra dialogo simples com informacoes da linha
        conteudo = ft.Column([
            ft.Text(f"{campo_nome}: {linha[campo_nome]}", color=theme.TEXTO),
            ft.Text(f"{campo_qtd}: {linha[campo_qtd]}", color=theme.TEXTO_SUAVE),
            ft.Text(f"{campo_total}: {linha[campo_total]}", color=theme.BRASA_CLARA),
        ], spacing=8)
        dlg = ft.AlertDialog(title=ft.Text("Detalhes", color=theme.TEXTO), content=conteudo, actions=[ft.TextButton("Fechar", on_click=lambda e: componentes.fechar_dialogo(page, dlg))])
        page.dialog = dlg
        dlg.open = True
        page.update()

    for i, linha in enumerate(linhas):
        row = ft.Row(
            [
                ft.Text(str(i + 1), color=theme.TEXTO_SUAVE, size=12, width=20),
                ft.Text(str(linha[campo_nome]), color=theme.TEXTO, size=13, expand=True, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(str(linha[campo_qtd]), color=theme.TEXTO_SUAVE, size=12, width=40, text_align=ft.TextAlign.RIGHT),
                ft.Text(_fmt(linha[campo_total]), color=theme.BRASA_CLARA, size=13, width=90, text_align=ft.TextAlign.RIGHT),
            ],
        )
        # tornar clicavel
        container = ft.Container(content=row, on_click=lambda e, l=linha: mostrar_detalle(l))
        itens.append(container)

    if not itens:
        itens = [ft.Text("Sem dados.", color=theme.TEXTO_FRACO, size=13)]

    return theme.cartao(
        ft.Column([ft.Text(titulo, color=theme.TEXTO, weight=ft.FontWeight.W_700), ft.Divider(color=theme.BORDA), *itens], spacing=8),
        expand=1,
    )


def _fmt(valor) -> str:
    return f"R$ {valor:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")
