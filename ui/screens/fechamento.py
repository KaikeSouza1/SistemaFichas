from datetime import datetime

import flet as ft

from config import settings
from db import postgres_local, repository
from db.connection import ConexaoIndisponivel
from printing import escpos_printer, templates
from ui import componentes, theme


def tela(page: ft.Page, estado, ao_concluir, ao_tentar_de_novo, ao_voltar=None, somente_consulta=False) -> ft.Control:
    """`somente_consulta=True` (pedido do usuario, 2026-09) e o "relatório
    gerencial de caixa aberto" - MESMA tela/calculo do fechamento normal
    (resumo_sessao), so pra CONSULTAR o que ja foi vendido e o estoque atual
    no meio do evento, sem fechar sessão nenhuma - so imprime, nunca chama
    fechar_sessao."""
    try:
        resumo = repository.resumo_sessao(estado.sessao_id)
        evento = repository.obter_evento_aberto()
        produtos_estoque = [p for p in repository.listar_produtos(somente_ativos=True) if p["estoque_controlado"]] \
            if somente_consulta else []
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

    # Pedido real do usuario apos o 1o evento: emitir mais de 1 via do
    # relatorio final (ex: uma pro caixa, uma pro responsavel do evento).
    campo_vias = theme.campo_texto("Vias", value="1", width=70, text_align=ft.TextAlign.CENTER)

    def _vias() -> int:
        try:
            n = int(campo_vias.value)
        except (ValueError, TypeError):
            n = 1
        return max(1, min(n, 10))

    def confirmar_fechamento(e):
        componentes.dialogo_confirmacao(
            page,
            "Fechar caixa",
            "Depois de fechado, essa sessão não pode mais receber vendas. Confirma o fechamento?",
            ao_confirmar=efetivar_fechamento,
            texto_confirmar="Fechar caixa",
        )

    def fechar_de_verdade():
        try:
            repository.fechar_sessao(estado.sessao_id, estado.operador_id)
        except ConexaoIndisponivel:
            componentes.dialogo_erro_conexao(page, tentar_de_novo=None)
            return
        try:
            postgres_local.fazer_backup()
        except Exception:
            pass  # backup e so uma rede de seguranca extra, nunca deve travar o fechamento
        estado.encerrar_sessao_local()
        ao_concluir()

    def mostrar_erro_impressao(ex):
        def tentar_de_novo_impressao(e2):
            componentes.fechar_dialogo(page, dlg_erro)
            efetivar_fechamento()

        def fechar_sem_imprimir(e2):
            componentes.fechar_dialogo(page, dlg_erro)
            fechar_de_verdade()

        dlg_erro = ft.AlertDialog(
            modal=True, bgcolor=theme.SURFACE,
            title=ft.Text("Erro ao imprimir o fechamento", color=theme.ERRO),
            content=ft.Text(
                f"{ex}\n\nO caixa AINDA NÃO foi fechado. Pode ajeitar a impressora "
                f"(recolocar papel, etc.) e tentar de novo, ou fechar sem imprimir.",
                color=theme.TEXTO_SUAVE,
            ),
            actions=[
                ft.TextButton("Fechar sem imprimir", on_click=fechar_sem_imprimir),
                theme.botao_primario("Tentar imprimir de novo", on_click=tentar_de_novo_impressao),
            ],
        )
        page.dialog = dlg_erro
        dlg_erro.open = True
        page.update()

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
            for _ in range(_vias()):
                escpos_printer.imprimir(cfg_local["impressora_windows"], dados)
        except Exception as ex:
            mostrar_erro_impressao(ex)
            return

        fechar_de_verdade()

    def imprimir_gerencial(e):
        try:
            dados = templates.fechamento_caixa_bytes(
                nome_evento=f"{evento['nome']} (CAIXA AINDA ABERTO)",
                caixa_nome=estado.caixa_nome,
                operador_nome=estado.operador_nome,
                data_hora=datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                resumo=resumo,
                rodape=evento["rodape"],
            )
            for _ in range(_vias()):
                escpos_printer.imprimir(cfg_local["impressora_windows"], dados)
            componentes.aviso(page, "Relatório gerencial enviado para a impressora.")
        except Exception as ex:
            componentes.aviso(page, f"Não deu para imprimir: {ex}", cor=theme.ALERTA)

    cartao_estoque = theme.cartao(
        ft.Column(
            [
                ft.Text("Estoque atual", color=theme.TEXTO, weight=ft.FontWeight.W_700),
                ft.Column(
                    [
                        ft.Row(
                            [ft.Text(p["nome"], color=theme.TEXTO, size=13, expand=True),
                             ft.Text(str(p["estoque_atual"]), color=theme.BRASA_CLARA, size=13, width=60,
                                     text_align=ft.TextAlign.RIGHT)],
                        )
                        for p in produtos_estoque
                    ] or [ft.Text("Nenhum produto com estoque controlado.", color=theme.TEXTO_FRACO, size=13)],
                    spacing=6, scroll=ft.ScrollMode.AUTO, height=180,
                ),
            ],
            spacing=10,
        ),
        expand=1,
    ) if somente_consulta else None

    return ft.Container(
        content=ft.Column(
            [
                ft.Row(
                    ([ft.IconButton(ft.icons.ARROW_BACK, icon_color=theme.TEXTO, on_click=lambda e: ao_voltar())] if ao_voltar else [])
                    + [ft.Icon(ft.icons.RECEIPT_LONG, color=theme.BRASA, size=26),
                       theme.titulo("Relatório gerencial (caixa aberto)" if somente_consulta else "Fechamento de caixa", tamanho=22)],
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
                    ] + ([cartao_estoque] if cartao_estoque else []),
                    spacing=16,
                    expand=True,
                ),
                ft.Row(
                    [campo_vias,
                     theme.botao_primario(
                        "Imprimir relatório" if somente_consulta else "Imprimir e fechar caixa",
                        icone=ft.icons.PRINT,
                        on_click=imprimir_gerencial if somente_consulta else confirmar_fechamento,
                        largura=280, altura=56,
                    )],
                    alignment=ft.MainAxisAlignment.END, spacing=10,
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
