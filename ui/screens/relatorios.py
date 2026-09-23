from datetime import datetime

import flet as ft

from config import settings
from db import repository
from db.connection import ConexaoIndisponivel
from printing import escpos_printer, templates
from ui import componentes, theme
from ui.screens.churrasco import _rotulo_churrasqueira


def tela(page: ft.Page, ao_voltar) -> ft.Control:
    try:
        eventos = repository.listar_eventos()
    except ConexaoIndisponivel:
        return componentes.tela_estado_erro("Não deu para carregar os eventos.", lambda: None)

    corpo = ft.Column(spacing=16, expand=True, scroll=ft.ScrollMode.AUTO)

    def carregar(evento_id, atualizar_pagina=True):
        try:
            mais_vendidos = repository.produtos_mais_vendidos(evento_id)
            excluidos = repository.itens_excluidos_por_evento(evento_id)
            fichas_churrasco = repository.listar_fichas_churrasco_relatorio(evento_id)
            churrasco_por_cor = repository.resumo_churrasco_por_cor(evento_id)
        except ConexaoIndisponivel:
            corpo.controls = [componentes.tela_estado_erro("Não deu para carregar os relatórios.", lambda: carregar(evento_id))]
            if atualizar_pagina:
                corpo.update()
            return

        # "Vendas por operador" foi removido (pedido do usuario, 2026-09): com
        # 1 operador por caixa/sessao, esse relatorio sempre dava o MESMO
        # numero que "Vendas por caixa" - redundante.
        # "Vendas por caixa" (listagem separada por caixa) tambem foi tirado
        # (pedido do usuario, 2026-09-23) - quando o evento roda em rede
        # (todos os caixas no mesmo banco), o que o responsavel do evento
        # quer e UM fechamento total somando tudo, nao um numero por caixa.
        # So faz sentido pra 1 evento especifico (nao pra "Todos os eventos",
        # que misturaria eventos diferentes num total so sem sentido).
        evento_atual = next((ev for ev in eventos if ev["id"] == evento_id), None) if evento_id is not None else None
        nome_evento = evento_atual["nome"] if evento_atual else "Todos os eventos"

        corpo.controls = [
            ft.Row(
                [
                    _cartao_ranking(page, "Produtos mais vendidos", mais_vendidos, "nome_produto", "quantidade", "total"),
                    _cartao_ranking(page, "Itens excluídos do carrinho", excluidos, "nome_produto", "quantidade", "total"),
                ]
                + ([_cartao_fechamento_total(page, evento_atual)] if evento_atual else []),
                spacing=16, expand=True, vertical_alignment=ft.CrossAxisAlignment.START,
            ),
            ft.Row(
                [_cartao_churrasco(page, nome_evento, fichas_churrasco, churrasco_por_cor)],
                spacing=16, expand=True, vertical_alignment=ft.CrossAxisAlignment.START,
            ),
        ]
        if atualizar_pagina:
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

    carregar(None if valor_inicial == "todos" else int(valor_inicial), atualizar_pagina=False)

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

    def imprimir(e):
        try:
            cfg_local = settings.load()
            dados = templates.relatorio_ranking_bytes(titulo, linhas, campo_nome, campo_qtd, campo_total)
            escpos_printer.imprimir(cfg_local["impressora_windows"], dados)
            componentes.aviso(page, "Relatório enviado para a impressora.")
        except Exception as ex:
            componentes.aviso(page, f"Não deu para imprimir: {ex}", cor=theme.ALERTA)

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
        ft.Column(
            [
                ft.Row(
                    [
                        ft.Text(titulo, color=theme.TEXTO, weight=ft.FontWeight.W_700, expand=True),
                        ft.IconButton(ft.icons.PRINT, icon_color=theme.TEXTO_SUAVE, icon_size=18, tooltip="Imprimir", on_click=imprimir),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                ft.Divider(color=theme.BORDA),
                *itens,
            ],
            spacing=8,
        ),
        expand=1,
    )


def _cartao_fechamento_total(page, evento):
    """Fechamento somando TODOS os caixas/sessoes do evento (pedido real do
    usuario, 2026-09-23) - MESMO formato/template do fechamento normal de 1
    caixa, so que a fonte dos dados e resumo_evento (evento inteiro) em vez
    de resumo_sessao (1 sessao). Substitui a antiga listagem "Vendas por
    caixa" - so faz sentido quando os caixas do evento rodaram todos na
    MESMA rede/banco; se rodaram cada um com seu proprio banco separado, o
    responsavel ja pega um fechamento por PC na hora (fora daqui)."""
    try:
        resumo = repository.resumo_evento(evento["id"])
    except ConexaoIndisponivel:
        return theme.cartao(componentes.tela_estado_erro("Não deu para calcular o fechamento total.", lambda: None), expand=1)

    def imprimir(e):
        try:
            cfg_local = settings.load()
            dados = templates.fechamento_caixa_bytes(
                nome_evento=evento["nome"],
                caixa_nome="Todos os caixas",
                operador_nome="-",
                data_hora=_agora(),
                resumo=resumo,
                rodape=evento.get("rodape") or "",
            )
            escpos_printer.imprimir(cfg_local["impressora_windows"], dados)
            componentes.aviso(page, "Fechamento total do evento enviado para a impressora.")
        except Exception as ex:
            componentes.aviso(page, f"Não deu para imprimir: {ex}", cor=theme.ALERTA)

    def _linha(rotulo, valor, destaque=False):
        return ft.Row(
            [
                ft.Text(rotulo, color=theme.TEXTO_SUAVE if not destaque else theme.TEXTO,
                         size=13, weight=ft.FontWeight.W_700 if destaque else ft.FontWeight.NORMAL),
                ft.Text(_fmt(valor), color=theme.TEXTO if not destaque else theme.BRASA_CLARA,
                         size=13, weight=ft.FontWeight.W_700 if destaque else ft.FontWeight.NORMAL),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

    return theme.cartao(
        ft.Column(
            [
                ft.Row(
                    [
                        ft.Text("Fechamento total do evento", color=theme.TEXTO, weight=ft.FontWeight.W_700, expand=True),
                        ft.IconButton(ft.icons.PRINT, icon_color=theme.TEXTO_SUAVE, icon_size=18,
                                      tooltip="Imprimir", on_click=imprimir),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                theme.subtitulo("Soma de todos os caixas deste evento (so faz sentido se rodaram na mesma rede).", tamanho=11),
                ft.Divider(color=theme.BORDA),
                _linha("Total em dinheiro", resumo["total_dinheiro"], destaque=True),
                _linha("Cartão crédito", resumo["cartao_credito"]),
                _linha("Cartão débito", resumo["cartao_debito"]),
                _linha("Pix", resumo["pix"]),
                _linha("Consumação", resumo["consumacao"]),
                ft.Divider(color=theme.BORDA),
                _linha(f"Total geral ({resumo['total_geral_qtd']} itens)", resumo["total_geral_valor"], destaque=True),
            ],
            spacing=8,
        ),
        expand=1,
    )


def _agora() -> str:
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")


def _cartao_churrasco(page, nome_evento, fichas, por_cor):
    """Relatorio final do churrasco (pedido do usuario, 2026-09): substitui o
    ranking "por carne" agrupado por uma listagem achatada (Nº do pedido +
    carne + valor, sem selecionar carne nenhuma) com total de quantidade e
    valor no fim. "Por churrasqueira (cor)" continua existindo, mas agora
    NA MESMA impressao - antes era um botao separado que o usuario relatou
    nao sair no fim do relatorio."""
    total_valor = sum((f["valor"] for f in fichas), start=type(fichas[0]["valor"])(0)) if fichas else 0

    def imprimir(e):
        try:
            cfg_local = settings.load()
            # Resolve o nome bonito da cor ANTES de imprimir (templates.py
            # nao conhece CORES_PRESET de proposito) - senao o impresso
            # mostra o cor_hex cru quando a churrasqueira nao tem nome
            # livre digitado (bug real, 2026-09-21).
            por_cor_resolvido = [{**linha, "nome_churrasqueira": _rotulo_churrasqueira(linha["nome_churrasqueira"], linha["cor_hex"])}
                                  for linha in por_cor]
            dados = templates.relatorio_churrasco_bytes(nome_evento, fichas, por_cor_resolvido)
            escpos_printer.imprimir(cfg_local["impressora_windows"], dados)
            componentes.aviso(page, "Relatório do churrasco enviado para a impressora.")
        except Exception as ex:
            componentes.aviso(page, f"Não deu para imprimir: {ex}", cor=theme.ALERTA)

    linhas = [
        ft.Row(
            [
                ft.Text(f"Nº {f['numero_ficha']}", color=theme.TEXTO_SUAVE, size=12, width=55),
                ft.Text(str(f["nome_cliente"]), color=theme.TEXTO, size=13, expand=True, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(str(f["nome_carne"]), color=theme.TEXTO_SUAVE, size=12, expand=True, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(_fmt(f["valor"]), color=theme.BRASA_CLARA, size=13, width=90, text_align=ft.TextAlign.RIGHT),
            ],
        )
        for f in fichas
    ] or [ft.Text("Sem dados.", color=theme.TEXTO_FRACO, size=13)]

    linhas_cor = [
        ft.Row(
            [
                ft.Container(width=10, height=10, bgcolor=linha["cor_hex"], border_radius=3),
                ft.Text(str(linha["nome_churrasqueira"] or linha["cor_hex"]), color=theme.TEXTO, size=13, expand=True),
                ft.Text(str(linha["qtd"]), color=theme.TEXTO_SUAVE, size=12, width=40, text_align=ft.TextAlign.RIGHT),
                ft.Text(_fmt(linha["total"]), color=theme.BRASA_CLARA, size=13, width=90, text_align=ft.TextAlign.RIGHT),
            ],
            spacing=8,
        )
        for linha in por_cor
    ] or [ft.Text("Sem dados.", color=theme.TEXTO_FRACO, size=13)]

    return theme.cartao(
        ft.Column(
            [
                ft.Row(
                    [
                        ft.Text("Churrasco - relatório final", color=theme.TEXTO, weight=ft.FontWeight.W_700, expand=True),
                        ft.IconButton(ft.icons.PRINT, icon_color=theme.TEXTO_SUAVE, icon_size=18,
                                      tooltip="Imprimir", on_click=imprimir),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                ft.Divider(color=theme.BORDA),
                *linhas,
                ft.Divider(color=theme.BORDA),
                ft.Row(
                    [ft.Text(f"TOTAL: {len(fichas)} ficha(s)", color=theme.TEXTO, weight=ft.FontWeight.W_700),
                     ft.Text(_fmt(total_valor), color=theme.BRASA_CLARA, weight=ft.FontWeight.W_700)],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                ft.Divider(color=theme.BORDA),
                ft.Text("Por churrasqueira", color=theme.TEXTO, weight=ft.FontWeight.W_700),
                *linhas_cor,
            ],
            spacing=8,
        ),
        expand=1,
    )


def _fmt(valor) -> str:
    return f"R$ {valor:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")
