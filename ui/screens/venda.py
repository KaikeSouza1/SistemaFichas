from datetime import datetime

import flet as ft

from config import settings
from db import repository
from db.connection import ConexaoIndisponivel
from printing import escpos_printer, templates
from ui import componentes, theme

FORMAS_PAGAMENTO = [
    ("DINHEIRO", "Dinheiro"),
    ("CARTAO_CREDITO", "Cartão Crédito"),
    ("CARTAO_DEBITO", "Cartão Débito"),
    ("PIX", "Pix"),
    ("CONSUMACAO", "Consumação"),
]


def tela(page: ft.Page, estado, ao_fechar_caixa, ao_deslogar, ao_abrir_configuracao, ao_abrir_relatorios, ao_tentar_de_novo) -> ft.Control:
    try:
        evento = repository.obter_evento_aberto()
        categorias = repository.listar_categorias()
        produtos = repository.listar_produtos(somente_ativos=True, incluir_ocultos=True)
        produtos = [p for p in produtos if not p["oculto"]]
    except ConexaoIndisponivel:
        return componentes.tela_estado_erro("Não deu para carregar os produtos.", ao_tentar_de_novo)

    cfg_local = settings.load()
    categoria_selecionada = {"id": None}

    total_text = ft.Text("R$ 0,00", size=24, weight=ft.FontWeight.W_800, color=theme.TEXTO)
    carrinho_coluna = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO, expand=True)
    grade_produtos = ft.GridView(expand=True, max_extent=175, child_aspect_ratio=1.15, spacing=12, run_spacing=12, padding=4)
    chips_categorias = ft.Row(spacing=8, scroll=ft.ScrollMode.AUTO)

    # ---------- Carrinho ----------

    def atualizar_carrinho_ui():
        carrinho_coluna.controls = [_linha_carrinho(item) for item in estado.carrinho]
        total_text.value = _fmt(estado.total_carrinho())
        page.update()

    def adicionar_ao_carrinho(produto):
        for item in estado.carrinho:
            if item["produto_id"] == produto["id"]:
                item["quantidade"] += 1
                atualizar_carrinho_ui()
                return
        estado.carrinho.append({
            "produto_id": produto["id"], "nome": produto["nome"],
            "preco": produto["preco"], "custo": produto["custo"], "quantidade": 1,
        })
        atualizar_carrinho_ui()

    def registrar_exclusao_silenciosa(item, qtd):
        try:
            repository.registrar_item_excluido(
                estado.sessao_id, estado.caixa_id, estado.operador_id,
                item["produto_id"], item["nome"], qtd, item["preco"] * qtd,
            )
        except ConexaoIndisponivel:
            pass

    def decrementar(item):
        if item["quantidade"] > 1:
            item["quantidade"] -= 1
        else:
            estado.carrinho.remove(item)
        registrar_exclusao_silenciosa(item, 1)
        atualizar_carrinho_ui()

    def incrementar(item):
        item["quantidade"] += 1
        atualizar_carrinho_ui()

    def remover_linha(item):
        estado.carrinho.remove(item)
        registrar_exclusao_silenciosa(item, item["quantidade"])
        atualizar_carrinho_ui()

    def _linha_carrinho(item):
        return ft.Container(
            content=ft.Row(
                [
                    ft.Column(
                        [
                            ft.Text(item["nome"], color=theme.TEXTO, weight=ft.FontWeight.W_600, size=14),
                            ft.Text(f"{_fmt(item['preco'])} cada", color=theme.TEXTO_SUAVE, size=11),
                        ],
                        expand=True, spacing=2,
                    ),
                    ft.IconButton(ft.icons.REMOVE_CIRCLE_OUTLINE, icon_color=theme.TEXTO_SUAVE, icon_size=20,
                                  on_click=lambda e, i=item: (decrementar(i))),
                    ft.Text(str(item["quantidade"]), color=theme.TEXTO, size=15, weight=ft.FontWeight.W_700),
                    ft.IconButton(ft.icons.ADD_CIRCLE_OUTLINE, icon_color=theme.BRASA_CLARA, icon_size=20,
                                  on_click=lambda e, i=item: (incrementar(i))),
                    ft.IconButton(ft.icons.DELETE_OUTLINE, icon_color=theme.ERRO, icon_size=20,
                                  on_click=lambda e, i=item: (remover_linha(i))),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            bgcolor=theme.SURFACE_ALTA, border_radius=theme.RADIUS, padding=ft.padding.symmetric(8, 12),
        )

    # ---------- Grade de produtos ----------

    def _produto_tile(produto):
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(produto["nome"], color="#FFFFFF", weight=ft.FontWeight.W_700, size=15,
                             max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(_fmt(produto["preco"]), color="#FFFFFF", size=14, weight=ft.FontWeight.W_500, opacity=0.9),
                ],
                spacing=6,
            ),
            bgcolor=produto["cor_hex"] or theme.BRASA,
            border_radius=theme.RADIUS,
            padding=14,
            ink=True,
            on_click=lambda e, p=produto: adicionar_ao_carrinho(p),
            alignment=ft.alignment.bottom_left,
        )

    def atualizar_grade():
        if categoria_selecionada["id"] is None:
            itens = produtos
        else:
            itens = [p for p in produtos if p["categoria_id"] == categoria_selecionada["id"]]
        grade_produtos.controls = [_produto_tile(p) for p in itens]
        for chip in chips_categorias.controls:
            chip.bgcolor = theme.BRASA if chip.data == categoria_selecionada["id"] else theme.SURFACE_ALTA
        page.update()

    def _chip(nome, categoria_id):
        return ft.Container(
            content=ft.Text(nome, color=theme.TEXTO, size=13, weight=ft.FontWeight.W_600),
            data=categoria_id, bgcolor=theme.SURFACE_ALTA, border_radius=20,
            padding=ft.padding.symmetric(8, 16), ink=True,
            on_click=lambda e, c=categoria_id: (categoria_selecionada.update(id=c), atualizar_grade()),
        )

    chips_categorias.controls = [_chip("Todos", None)] + [_chip(c["nome"], c["id"]) for c in categorias]

    # ---------- Finalizar venda ----------

    def abrir_dialogo_pagamento(e):
        if not estado.carrinho:
            componentes.aviso(page, "Carrinho vazio.", cor=theme.ALERTA)
            return

        def escolher(codigo):
            def handler(e):
                componentes.fechar_dialogo(page, dlg)
                finalizar(codigo)
            return handler

        dlg = ft.AlertDialog(
            modal=True, bgcolor=theme.SURFACE,
            title=ft.Text(f"Total: {_fmt(estado.total_carrinho())}", color=theme.TEXTO, size=20),
            content=ft.Column(
                [theme.botao_primario(nome, on_click=escolher(codigo), largura=280) for codigo, nome in FORMAS_PAGAMENTO],
                tight=True, spacing=10,
            ),
            actions=[ft.TextButton("Cancelar", on_click=lambda e: componentes.fechar_dialogo(page, dlg))],
        )
        page.dialog = dlg
        dlg.open = True
        page.update()

    def finalizar(forma_codigo):
        if not estado.carrinho:
            componentes.aviso(page, "Carrinho vazio.", cor=theme.ALERTA)
            return
        itens = [dict(i) for i in estado.carrinho]
        try:
            resultado = repository.registrar_venda(estado.sessao_id, estado.caixa_id, estado.operador_id, itens, forma_codigo)
        except ConexaoIndisponivel:
            componentes.dialogo_erro_conexao(page, tentar_de_novo=None)
            return

        try:
            dados = templates.fichas_venda_bytes(
                nome_evento=evento["nome"],
                numero_pedido=resultado["numero_pedido"],
                data_hora=datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                itens=itens,
                operador_nome=estado.operador_nome,
                caixa_nome=estado.caixa_nome,
            )
            escpos_printer.imprimir(cfg_local["impressora_windows"], dados)
        except Exception as ex:
            componentes.aviso(page, f"Venda #{resultado['numero_pedido']} registrada, mas a impressão falhou: {ex}", cor=theme.ALERTA)
        else:
            total_fichas = sum(i["quantidade"] for i in itens)
            componentes.aviso(page, f"Pedido #{resultado['numero_pedido']}: {total_fichas} ficha(s) impressa(s)!")

        estado.limpar_carrinho()
        atualizar_carrinho_ui()

    # ---------- Troca ----------

    def abrir_dialogo_troca(e):
        opcoes_produto = [ft.dropdown.Option(str(p["id"]), p["nome"]) for p in produtos]

        dropdown_saida = ft.Dropdown(label="Produto que o cliente devolveu", width=300, options=opcoes_produto,
                                      border_color=theme.BORDA, focused_border_color=theme.BRASA, bgcolor=theme.SURFACE_ALTA)
        campo_qtd_saida = theme.campo_texto("Quantidade devolvida", value="1", width=140)
        dropdown_entrada = ft.Dropdown(label="Produto novo (opcional)", width=300,
                                        options=[ft.dropdown.Option("nenhum", "Nenhum - só devolver dinheiro")] + opcoes_produto,
                                        value="nenhum",
                                        border_color=theme.BORDA, focused_border_color=theme.BRASA, bgcolor=theme.SURFACE_ALTA)
        campo_qtd_entrada = theme.campo_texto("Quantidade nova", value="1", width=140)
        campo_motivo = theme.campo_texto("Motivo (opcional)", width=300)

        def confirmar(e):
            if not dropdown_saida.value:
                return
            produto_saida = next(p for p in produtos if p["id"] == int(dropdown_saida.value))
            try:
                qtd_saida = int(campo_qtd_saida.value)
            except ValueError:
                return
            produto_entrada = None
            qtd_entrada = 0
            if dropdown_entrada.value and dropdown_entrada.value != "nenhum":
                produto_entrada = next(p for p in produtos if p["id"] == int(dropdown_entrada.value))
                try:
                    qtd_entrada = int(campo_qtd_entrada.value)
                except ValueError:
                    return
            try:
                repository.registrar_troca(
                    estado.sessao_id, estado.caixa_id, estado.operador_id,
                    produto_saida, qtd_saida, produto_entrada, qtd_entrada, campo_motivo.value or None,
                )
            except ConexaoIndisponivel:
                componentes.dialogo_erro_conexao(page, tentar_de_novo=None)
                return
            componentes.fechar_dialogo(page, dlg)
            componentes.aviso(page, "Troca registrada.")

        dlg = ft.AlertDialog(
            modal=True, bgcolor=theme.SURFACE,
            title=ft.Text("Troca", color=theme.TEXTO),
            content=ft.Column(
                [dropdown_saida, campo_qtd_saida, ft.Divider(color=theme.BORDA),
                 dropdown_entrada, campo_qtd_entrada, campo_motivo],
                tight=True, spacing=12, scroll=ft.ScrollMode.AUTO, width=320,
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda e: componentes.fechar_dialogo(page, dlg)),
                theme.botao_primario("Confirmar", on_click=confirmar),
            ],
        )
        page.dialog = dlg
        dlg.open = True
        page.update()

    # ---------- Sangria / Reforço ----------

    def abrir_dialogo_movimento(rotulo, tipo_enum):
        campo_valor = theme.campo_texto("Valor (R$)", value="0,00", width=240)
        campo_motivo = theme.campo_texto("Motivo (opcional)", width=240)

        def confirmar(e):
            try:
                valor = float(campo_valor.value.replace(".", "").replace(",", "."))
            except ValueError:
                return
            try:
                repository.registrar_movimento(estado.sessao_id, tipo_enum, valor, campo_motivo.value or None, estado.operador_id)
            except ConexaoIndisponivel:
                componentes.dialogo_erro_conexao(page, tentar_de_novo=None)
                return
            componentes.fechar_dialogo(page, dlg)
            componentes.aviso(page, f"{rotulo} registrada.")

        dlg = ft.AlertDialog(
            modal=True, bgcolor=theme.SURFACE,
            title=ft.Text(rotulo, color=theme.TEXTO),
            content=ft.Column([campo_valor, campo_motivo], tight=True, spacing=12),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda e: componentes.fechar_dialogo(page, dlg)),
                theme.botao_primario("Confirmar", on_click=confirmar),
            ],
        )
        page.dialog = dlg
        dlg.open = True
        page.update()

    # ---------- Layout ----------

    barra_topo = ft.Container(
        content=ft.Row(
            [
                ft.Row(
                    [ft.Icon(ft.icons.LOCAL_FIRE_DEPARTMENT, color=theme.BRASA, size=22),
                     ft.Text(evento["nome"], color=theme.TEXTO, size=16, weight=ft.FontWeight.W_700)],
                    spacing=8,
                ),
                ft.Text(f"{estado.caixa_nome} · {estado.operador_nome}", color=theme.TEXTO_SUAVE, size=13),
                ft.Row(
                    [
                        ft.TextButton("Sangria", icon=ft.icons.ARROW_DOWNWARD,
                                      on_click=lambda e: abrir_dialogo_movimento("Sangria", "SANGRIA"),
                                      style=ft.ButtonStyle(color=theme.TEXTO_SUAVE)),
                        ft.TextButton("Reforço", icon=ft.icons.ARROW_UPWARD,
                                      on_click=lambda e: abrir_dialogo_movimento("Reforço", "REFORCO"),
                                      style=ft.ButtonStyle(color=theme.TEXTO_SUAVE)),
                        ft.TextButton("Troca", icon=ft.icons.SWAP_HORIZ,
                                      on_click=abrir_dialogo_troca,
                                      style=ft.ButtonStyle(color=theme.TEXTO_SUAVE)),
                        ft.TextButton("Relatórios", icon=ft.icons.BAR_CHART,
                                      on_click=lambda e: ao_abrir_relatorios(),
                                      style=ft.ButtonStyle(color=theme.TEXTO_SUAVE)),
                        ft.TextButton("Configurações", icon=ft.icons.SETTINGS,
                                      on_click=lambda e: ao_abrir_configuracao(),
                                      style=ft.ButtonStyle(color=theme.TEXTO_SUAVE)),
                        ft.TextButton("Trocar operador", icon=ft.icons.LOGOUT,
                                      on_click=lambda e: ao_deslogar(),
                                      style=ft.ButtonStyle(color=theme.TEXTO_SUAVE)),
                        theme.botao_secundario("Fechar caixa", icone=ft.icons.POINT_OF_SALE, on_click=lambda e: ao_fechar_caixa()),
                    ],
                    spacing=4,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        ),
        padding=ft.padding.symmetric(10, 20),
        bgcolor=theme.SURFACE,
        border=ft.border.only(bottom=ft.BorderSide(1, theme.BORDA)),
    )

    painel_carrinho = ft.Container(
        content=ft.Column(
            [
                ft.Text("Pedido atual", color=theme.TEXTO, size=16, weight=ft.FontWeight.W_700),
                carrinho_coluna,
                ft.Divider(color=theme.BORDA),
                ft.Row([ft.Text("Total", color=theme.TEXTO_SUAVE, size=15), total_text], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                theme.botao_primario("Finalizar venda", icone=ft.icons.CHECK_CIRCLE, on_click=abrir_dialogo_pagamento, altura=56),
            ],
            spacing=12,
            expand=True,
        ),
        width=340,
        bgcolor=theme.SURFACE,
        padding=18,
        border=ft.border.only(left=ft.BorderSide(1, theme.BORDA)),
    )

    atualizar_grade()

    return ft.Column(
        [
            barra_topo,
            ft.Row(
                [
                    ft.Container(
                        content=ft.Column([chips_categorias, grade_produtos], spacing=14, expand=True),
                        padding=18, expand=True,
                    ),
                    painel_carrinho,
                ],
                expand=True,
                spacing=0,
            ),
        ],
        spacing=0,
        expand=True,
    )


def _fmt(valor) -> str:
    return f"R$ {valor:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")
