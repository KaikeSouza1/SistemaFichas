from datetime import datetime

import flet as ft

from config import settings
from db import repository
from db.connection import ConexaoIndisponivel
from printing import escpos_printer, templates
from ui import componentes, theme


def tela(page: ft.Page, estado, ao_concluir, ao_tentar_de_novo, ao_voltar=None) -> ft.Control:
    try:
        resumo = repository.resumo_sessao(estado.sessao_id)
        evento = repository.obter_evento_aberto()
    except ConexaoIndisponivel:
        return componentes.tela_estado_erro("Não deu para calcular o fechamento.", ao_tentar_de_novo)

    cfg_local = settings.load()

    def _linha_resumo(rotulo, valor, destaque=False):
        return ft.Row(
            [
                ft.Text(rotulo, color=theme.TEXTO_SUAVE if not destaque else theme.TEXTO, size=14 if not destaque else 16,
                         weight=ft.FontWeight.W_700 if destaque else ft.FontWeight.NORMAL),
                ft.Text(_fmt(valor), color=theme.TEXTO, size=14 if not destaque else 18,
                         weight=ft.FontWeight.W_700 if destaque else ft.FontWeight.W_600),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

    tabela_itens = ft.Column(
        [
            ft.Row(
                [
                    ft.Text(item["nome_produto"], color=theme.TEXTO, size=13, expand=True),
                    ft.Text(str(item["quantidade"]), color=theme.TEXTO_SUAVE, size=13, width=40, text_align=ft.TextAlign.RIGHT),
                    ft.Text(_fmt(item["total"]), color=theme.TEXTO, size=13, width=90, text_align=ft.TextAlign.RIGHT),
                ],
            )
            for item in resumo["itens_vendidos"]
        ],
        spacing=6,
    )

    def confirmar_fechamento(e):
        componentes.dialogo_confirmacao(
            page,
            "Fechar caixa",
            "Depois de fechado, essa sessão não pode mais receber vendas. Confirma o fechamento?",
            ao_confirmar=efetivar_fechamento,
            texto_confirmar="Fechar caixa",
        )

    def efetivar_fechamento():
        try:
            dados = templates.fechamento_caixa_bytes(
                nome_evento=evento["nome"],
                caixa_nome=estado.caixa_nome,
                operador_nome=estado.operador_nome,
                data_hora=datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                resumo=resumo,
                rodape=evento["rodape"],
            )
            escpos_printer.imprimir(cfg_local["impressora_windows"], dados)
        except Exception as ex:
            componentes.aviso(page, f"Não deu para imprimir o fechamento: {ex}", cor=theme.ALERTA)

        try:
            repository.fechar_sessao(estado.sessao_id, estado.operador_id)
        except ConexaoIndisponivel:
            componentes.dialogo_erro_conexao(page, tentar_de_novo=None)
            return

        estado.encerrar_sessao_local()
        ao_concluir()

    return ft.Container(
        content=ft.Column(
            [
                ft.Row(
                    ([ft.IconButton(ft.icons.ARROW_BACK, icon_color=theme.TEXTO, on_click=lambda e: ao_voltar())] if ao_voltar else [])
                    + [ft.Icon(ft.icons.RECEIPT_LONG, color=theme.BRASA, size=26),
                       theme.titulo("Fechamento de caixa", tamanho=22)],
                    spacing=10,
                ),
                theme.subtitulo(f"{estado.caixa_nome} · Operador: {estado.operador_nome}"),
                ft.Row(
                    [
                        theme.cartao(
                            ft.Column(
                                [
                                    _linha_resumo("(+) Abertura", resumo["abertura"]),
                                    _linha_resumo("(+) Adicional", resumo["adicional"]),
                                    _linha_resumo("(+) Dinheiro (vendas)", resumo["dinheiro_vendas"]),
                                    _linha_resumo("(-) Sangria", resumo["sangria"]),
                                    _linha_resumo("(+/-) Trocas", resumo["trocas_total"]),
                                    ft.Divider(color=theme.BORDA),
                                    _linha_resumo("(=) Total em dinheiro", resumo["total_dinheiro"], destaque=True),
                                    ft.Divider(color=theme.BORDA),
                                    _linha_resumo("Cartão crédito", resumo["cartao_credito"]),
                                    _linha_resumo("Cartão débito", resumo["cartao_debito"]),
                                    _linha_resumo("Pix", resumo["pix"]),
                                    _linha_resumo("Consumação", resumo["consumacao"]),
                                ],
                                spacing=10,
                            ),
                            expand=1,
                        ),
                        theme.cartao(
                            ft.Column(
                                [
                                    ft.Text("Itens vendidos", color=theme.TEXTO, weight=ft.FontWeight.W_700),
                                    ft.Container(tabela_itens, height=220, ),
                                    ft.Divider(color=theme.BORDA),
                                    _linha_resumo(f"Total geral ({resumo['total_geral_qtd']} itens)", resumo["total_geral_valor"], destaque=True),
                                ],
                                spacing=10,
                            ),
                            expand=1,
                        ),
                    ],
                    spacing=16,
                    expand=True,
                ),
                ft.Row(
                    [theme.botao_primario("Imprimir e fechar caixa", icone=ft.icons.PRINT, on_click=confirmar_fechamento, largura=280, altura=56)],
                    alignment=ft.MainAxisAlignment.END,
                ),
            ],
            spacing=18,
            expand=True,
        ),
        padding=26,
        bgcolor=theme.BG,
        expand=True,
    )


def _fmt(valor) -> str:
    return f"R$ {valor:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")
