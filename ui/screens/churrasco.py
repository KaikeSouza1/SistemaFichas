"""Modulo Churrasco: venda por ficha nomeada (uma unidade por vez, com nome
do cliente obrigatorio) - substitui o bloco de papel fisico com via+canhoto
usado hoje (ver memoria do projeto). Vive dentro do MESMO evento/caixa/
sessao/operador do resto do sistema - nao tem abertura/fechamento propria,
fecha e sincroniza junto com o evento (ver db.repository.registrar_ficha_churrasco_do_bloco
e dump_evento_completo).

Nao ha cadastro/catalogo de carnes - o operador digita a carne e o valor na
hora de emitir a ficha (pedido explicito do usuario). A cor (churrasqueira)
vem de qual BLOCO de numeracao (faixa) o operador escolhe vender no momento -
cada bloco tem numeracao PROPRIA e INDEPENDENTE, o operador troca livremente
entre eles a qualquer momento (pedido explicito do usuario, 2026-08-11).

Deliberadamente AUTOCONTIDO: configuracao de faixas e busca de fichas ficam
aqui dentro (dialogos abertos a partir desta tela), não misturados nas abas
de Configurações gerais (pedido do usuário - "deixa esse módulo mais separado").
"""
import base64
import threading
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation

import flet as ft

from config import settings
from db import repository
from db.connection import ConexaoIndisponivel
from printing import escpos_printer, templates
from ui import componentes, theme
from ui.screens.configuracao import CORES_PRESET

INTERVALO_ATUALIZAR_TOTAIS_SEGUNDOS = 8
LARGURA_PONTOS_CELULAR = 576

FORMAS_PAGAMENTO = [
    ("DINHEIRO", "Dinheiro"),
    ("CARTAO_CREDITO", "Cartão Crédito"),
    ("CARTAO_DEBITO", "Cartão Débito"),
    ("PIX", "Pix"),
    ("CONSUMACAO", "Consumação"),
]

NOME_FORMA_PAGAMENTO = dict(FORMAS_PAGAMENTO)

_NOME_COR = dict((hexv, nome) for nome, hexv in CORES_PRESET)


def _nome_cor(cor_hex: str) -> str:
    return _NOME_COR.get(cor_hex, cor_hex)


def _fmt(valor) -> str:
    return f"R$ {valor:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")


def _parse_moeda(texto: str) -> Decimal:
    texto = (texto or "").strip().replace(".", "").replace(",", ".")
    if not texto:
        raise ValueError("valor vazio")
    try:
        return Decimal(texto)
    except InvalidOperation:
        raise ValueError(f"valor invalido: {texto}")


def _criar_caixa_troco(tamanho=28):
    """Caixa de troco destacada (fundo + borda verde, valor grande) - mesmo
    componente visual pedido pra tela de venda normal, reaproveitado aqui."""
    valor_texto = ft.Text("", size=tamanho, weight=ft.FontWeight.W_900, color=theme.SUCESSO)
    caixa = ft.Container(
        content=ft.Column(
            [ft.Text("TROCO", size=12, color=theme.TEXTO_SUAVE, weight=ft.FontWeight.W_700), valor_texto],
            spacing=0, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        visible=False, bgcolor=theme.SURFACE_ALTA, border=ft.border.all(2, theme.SUCESSO),
        border_radius=theme.RADIUS, padding=ft.padding.symmetric(10, 16), alignment=ft.alignment.center,
    )
    return caixa, valor_texto


def tela(page: ft.Page, estado, ao_voltar) -> ft.Control:
    try:
        evento = repository.obter_evento_aberto()
    except ConexaoIndisponivel:
        return componentes.tela_estado_erro("Não deu para carregar o módulo Churrasco.", ao_voltar)

    cfg_local = settings.load()
    _polling_ativo = {"on": True}

    def _imprimir_via_rawbt(dados: bytes):
        dados_b64 = base64.b64encode(dados).decode("ascii")
        page.launch_url(f"rawbt:base64,{dados_b64}")

    # ---------- Painel de totais por churrasqueira (tempo real) ----------

    painel_totais = ft.Row(spacing=10, wrap=True)

    # ---------- Blocos de numeração (independentes, escolhidos na hora) ----------
    # Pedido explicito do usuario (2026-08-11): cada bloco/faixa configurado
    # tem sua PROPRIA numeracao, e o operador escolhe livremente qual esta
    # vendendo a qualquer momento (sem ordem obrigatoria) - substitui o
    # modelo anterior de um contador unico global que so cruzava de bloco em
    # bloco automaticamente. `bloco_ativo`/`blocos_cache` sao estado local
    # desta tela (nao persistem entre aberturas - reabrir o modulo volta a
    # escolher o primeiro bloco disponivel).
    bloco_ativo = {"id": None}
    blocos_cache = {"lista": []}
    linha_blocos = ft.Row(spacing=10, wrap=True)

    def _bloco_por_id(faixa_id):
        return next((b for b in blocos_cache["lista"] if b["id"] == faixa_id), None)

    def selecionar_bloco(faixa_id):
        def handler(e):
            bloco = _bloco_por_id(faixa_id)
            if not bloco or bloco["esgotado"]:
                componentes.aviso(page, "Esse bloco está esgotado - escolha outro.", cor=theme.ALERTA)
                return
            bloco_ativo["id"] = faixa_id
            atualizar_blocos()
        return handler

    def _cartao_bloco(b):
        selecionado = b["id"] == bloco_ativo["id"]
        return ft.Container(
            content=ft.Column(
                [
                    ft.Container(width=96, height=7, bgcolor=b["cor_hex"], border_radius=4),
                    ft.Text(_nome_cor(b["cor_hex"]), color=theme.TEXTO, size=15, weight=ft.FontWeight.W_800),
                    ft.Text(f"Faixa: {b['numero_inicio']}-{b['numero_fim']}", color=theme.TEXTO_SUAVE, size=12),
                    (ft.Text("ESGOTADO", color=theme.ERRO, size=13, weight=ft.FontWeight.W_800) if b["esgotado"] else
                     ft.Text(f"Próxima: Nº {b['proximo_numero']}",
                             color=theme.SUCESSO if selecionado else theme.TEXTO_SUAVE, size=13, weight=ft.FontWeight.W_600)),
                ],
                spacing=6, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=theme.SURFACE if selecionado else theme.SURFACE_ALTA,
            border=ft.border.all(2 if selecionado else 1, theme.BRASA if selecionado else theme.BORDA),
            border_radius=theme.RADIUS, padding=ft.padding.symmetric(14, 16), width=152,
            opacity=0.45 if b["esgotado"] else 1,
            ink=not b["esgotado"], on_click=None if b["esgotado"] else selecionar_bloco(b["id"]),
        )

    def atualizar_blocos(atualizar_pagina=True):
        try:
            blocos_cache["lista"] = repository.listar_blocos_numeracao_churrasco(evento["id"])
        except ConexaoIndisponivel:
            return
        disponiveis = [b for b in blocos_cache["lista"] if not b["esgotado"]]
        if not any(b["id"] == bloco_ativo["id"] for b in disponiveis):
            bloco_ativo["id"] = disponiveis[0]["id"] if disponiveis else None
        linha_blocos.controls = [_cartao_bloco(b) for b in blocos_cache["lista"]] or [
            ft.Text("Nenhum bloco configurado ainda.", color=theme.TEXTO_FRACO, size=13)
        ]
        if atualizar_pagina:
            try:
                linha_blocos.update()
            except Exception:
                pass
        recarregar_area_acao(atualizar_pagina=atualizar_pagina)

    def atualizar_totais():
        atualizar_blocos()
        try:
            totais = repository.resumo_churrasco_por_cor(evento["id"])
        except ConexaoIndisponivel:
            return
        painel_totais.controls = [
            ft.Container(
                content=ft.Column(
                    [
                        ft.Container(width=96, height=7, bgcolor=t["cor_hex"], border_radius=4),
                        ft.Text(f"{t['qtd']} ficha(s)", color=theme.TEXTO, size=16, weight=ft.FontWeight.W_700),
                        ft.Text(_nome_cor(t["cor_hex"]), color=theme.TEXTO_SUAVE, size=12),
                        ft.Text(f"R$ {t['total']:.2f}".replace(".", ","), color=theme.TEXTO_SUAVE, size=13, weight=ft.FontWeight.W_600),
                    ],
                    spacing=6, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                bgcolor=theme.SURFACE_ALTA, border_radius=theme.RADIUS,
                border=ft.border.all(1, theme.BORDA),
                padding=ft.padding.symmetric(14, 18), width=150,
            )
            for t in totais
        ]
        try:
            painel_totais.update()
        except Exception:
            pass  # tela ja foi trocada/pagina fechou

    def _atualizar_totais_em_segundo_plano():
        while _polling_ativo["on"]:
            atualizar_totais()
            time.sleep(INTERVALO_ATUALIZAR_TOTAIS_SEGUNDOS)

    # ---------- Configurar faixas de numeração -> cor (dialogo proprio) ----------

    def abrir_configuracao_faixas(e=None):
        try:
            faixas_salvas = repository.listar_faixas_numeracao_churrasco(evento["id"])
        except ConexaoIndisponivel:
            componentes.dialogo_erro_conexao(page)
            return

        coluna_linhas = ft.Column(spacing=8)
        linhas_estado = []

        def _nova_linha_estado(numero_inicio="", numero_fim="", cor_hex=None):
            return {
                "inicio": theme.campo_texto("Nº inicial", value=str(numero_inicio), width=110),
                "fim": theme.campo_texto("Nº final", value=str(numero_fim), width=110),
                "cor": ft.Dropdown(
                    label="Churrasqueira", width=190, value=cor_hex or CORES_PRESET[0][1],
                    options=[ft.dropdown.Option(hexv, nome) for nome, hexv in CORES_PRESET],
                    border_color=theme.BORDA, focused_border_color=theme.BRASA, bgcolor=theme.SURFACE_ALTA,
                ),
            }

        def redesenhar_linhas(atualizar_pagina=True):
            def _linha(linha):
                def remover(ev):
                    linhas_estado.remove(linha)
                    redesenhar_linhas()

                return ft.Row(
                    [linha["inicio"], ft.Text("até", color=theme.TEXTO_SUAVE), linha["fim"], linha["cor"],
                     ft.IconButton(ft.icons.DELETE_OUTLINE, icon_color=theme.ERRO, icon_size=18,
                                   tooltip="Remover faixa", on_click=remover)],
                    spacing=8,
                )

            coluna_linhas.controls = [_linha(l) for l in linhas_estado] or [
                ft.Text("Nenhuma faixa configurada ainda.", color=theme.TEXTO_FRACO, size=13)
            ]
            if atualizar_pagina:
                coluna_linhas.update()

        def adicionar_linha(ev=None):
            try:
                sugestao_inicio = max((int(l["fim"].value) for l in linhas_estado if l["fim"].value.strip()), default=0) + 1
            except ValueError:
                sugestao_inicio = ""
            cor_usada = {l["cor"].value for l in linhas_estado}
            proxima_cor = next((hexv for _, hexv in CORES_PRESET if hexv not in cor_usada), CORES_PRESET[0][1])
            linhas_estado.append(_nova_linha_estado(sugestao_inicio, "", proxima_cor))
            redesenhar_linhas()

        for f in faixas_salvas:
            linhas_estado.append(_nova_linha_estado(f["numero_inicio"], f["numero_fim"], f["cor_hex"]))
        redesenhar_linhas(atualizar_pagina=False)

        def salvar_faixas(ev=None):
            faixas = []
            for linha in linhas_estado:
                try:
                    inicio = int(linha["inicio"].value)
                    fim = int(linha["fim"].value)
                except ValueError:
                    componentes.aviso(page, "Preencha o número inicial e final de cada faixa.", cor=theme.ERRO)
                    return
                faixas.append((inicio, fim, linha["cor"].value))
            try:
                repository.definir_faixas_numeracao_churrasco(evento["id"], faixas)
            except ValueError as ex:
                componentes.aviso(page, str(ex), cor=theme.ERRO)
                return
            except ConexaoIndisponivel:
                componentes.dialogo_erro_conexao(page)
                return
            componentes.fechar_dialogo(page, dlg)
            atualizar_totais()
            componentes.aviso(page, "Faixas de numeração salvas.")

        dlg = ft.AlertDialog(
            modal=True, bgcolor=theme.SURFACE,
            title=ft.Text("Faixas de numeração", color=theme.TEXTO),
            content=ft.Column(
                [
                    theme.subtitulo(
                        "Defina do número X até o número Y qual churrasqueira (cor) é responsável. "
                        "A ficha sai com o número seguinte da sequência e a cor é atribuída automaticamente - "
                        "vale só para este evento.",
                    ),
                    coluna_linhas,
                    theme.botao_secundario("Adicionar faixa", icone=ft.icons.ADD, on_click=adicionar_linha),
                ],
                tight=True, spacing=14, width=460, scroll=ft.ScrollMode.AUTO, height=380,
            ),
            actions=[
                ft.TextButton("Fechar", on_click=lambda e: componentes.fechar_dialogo(page, dlg)),
                theme.botao_primario("Salvar", on_click=salvar_faixas),
            ],
        )
        page.dialog = dlg
        dlg.open = True
        page.update()

    # ---------- Vender (dialogo "Nova ficha") ----------

    def abrir_dialogo_venda(e=None):
        bloco = _bloco_por_id(bloco_ativo["id"])
        if not bloco or bloco["esgotado"]:
            componentes.aviso(page, "Escolha um bloco de numeração disponível antes de vender.", cor=theme.ERRO)
            return

        campo_nome_cliente = theme.campo_texto("Nome do cliente", width=320, autofocus=True)
        campo_nome_carne = theme.campo_texto("Carne (ex: Costela, Frango...)", width=320)
        campo_valor_unitario = theme.campo_texto("Valor por ficha (R$)", width=200)
        venda_atual = {"nome_carne": "", "valor_unitario": Decimal("0")}

        texto_bloco_atual = ft.Row(
            [ft.Container(width=14, height=14, bgcolor=bloco["cor_hex"], border_radius=4),
             ft.Text(f"Bloco {_nome_cor(bloco['cor_hex'])} — próxima ficha Nº {bloco['proximo_numero']}",
                     color=theme.TEXTO_SUAVE, size=12, weight=ft.FontWeight.W_600)],
            spacing=8,
        )

        def _valor_unitario_digitado():
            try:
                return _parse_moeda(campo_valor_unitario.value)
            except ValueError:
                return Decimal("0")

        def atualizar_total(e=None):
            texto_total.value = _fmt(_valor_unitario_digitado())
            try:
                dlg.update()
            except Exception:
                pass

        def _finalizar(forma_pagamento, pago=True):
            nome_cliente = campo_nome_cliente.value.strip()
            try:
                ficha = repository.registrar_ficha_churrasco_do_bloco(
                    estado.sessao_id, estado.caixa_id, estado.operador_id, bloco["id"],
                    venda_atual["nome_carne"], venda_atual["valor_unitario"], nome_cliente,
                    forma_pagamento, pago=pago,
                )
            except ConexaoIndisponivel:
                componentes.dialogo_erro_conexao(page, tentar_de_novo=None)
                return
            except ValueError as ex:
                componentes.aviso(page, str(ex), cor=theme.ERRO)
                return
            componentes.fechar_dialogo(page, dlg)

            erro_impressao = None
            try:
                dados = templates.ficha_churrasco_bytes(
                    nome_evento=evento["nome"], numero_ficha=ficha["numero_ficha"],
                    nome_carne=ficha["nome_carne"], nome_cliente=ficha["nome_cliente"],
                    valor=ficha["valor"], data_hora=datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                    operador_nome=estado.operador_nome, caixa_nome=estado.caixa_nome,
                    nome_churrasqueira=_nome_cor(ficha["cor_hex"]),
                    largura_pontos=LARGURA_PONTOS_CELULAR if page.web else templates.LARGURA_PONTOS,
                    cortador_automatico=not page.web,
                )
                if page.web:
                    _imprimir_via_rawbt(dados)
                else:
                    escpos_printer.imprimir(cfg_local["impressora_windows"], dados)
            except Exception as ex:
                erro_impressao = ex

            rotulo_cor = _nome_cor(ficha["cor_hex"])
            rotulo_pendente = " - PENDENTE DE PAGAMENTO, finalize em \"Buscar fichas\"" if not pago else ""
            if erro_impressao:
                componentes.aviso(
                    page,
                    f"Nº {ficha['numero_ficha']} registrada, mas falhou ao imprimir. "
                    f"Use \"Buscar fichas\" para conferir.{rotulo_pendente}",
                    cor=theme.ALERTA,
                )
            else:
                componentes.aviso(
                    page,
                    f"Nº {ficha['numero_ficha']} de {venda_atual['nome_carne']} impressa para {nome_cliente}! "
                    f"({rotulo_cor}){rotulo_pendente}",
                    cor=theme.ALERTA if not pago else theme.SUCESSO,
                )
            atualizar_totais()

        # ---------- Passo 1: carne, valor e nome do cliente ----------

        def ir_para_pagamento(e=None):
            nome_cliente = campo_nome_cliente.value.strip()
            nome_carne = campo_nome_carne.value.strip()
            if not nome_cliente:
                componentes.aviso(page, "Informe o nome do cliente.", cor=theme.ERRO)
                return
            if not nome_carne:
                componentes.aviso(page, "Informe a carne.", cor=theme.ERRO)
                return
            valor_unitario = _valor_unitario_digitado()
            if valor_unitario <= 0:
                componentes.aviso(page, "Informe o valor da ficha.", cor=theme.ERRO)
                return
            venda_atual["nome_carne"] = nome_carne
            venda_atual["valor_unitario"] = valor_unitario
            painel_dados.visible = False
            painel_pagamento.visible = True
            dlg.update()

        def abrir_preview(e=None):
            # Pedido do usuario (bug real, 2026-08-11): mostrar a pre-visualizacao
            # como um SEGUNDO ft.AlertDialog (reatribuindo page.dialog e depois
            # tentando restaurar o de venda) deixava todos os botoes mortos ao
            # voltar - trocar page.dialog pra outro objeto e trocar de volta nao
            # remonta os manipuladores de clique de forma confiavel no Flet.
            # Em vez disso, a pre-visualizacao e so mais um painel (como
            # painel_dados/painel_pagamento) DENTRO do MESMO dialogo - nunca
            # troca page.dialog, so alterna visible=True/False, exatamente o
            # padrao ja usado (e testado) pra ir do passo 1 pro passo 2.
            png = templates.ficha_churrasco_preview_png(
                nome_evento=evento["nome"], numero_ficha=bloco["proximo_numero"],
                nome_carne=campo_nome_carne.value.strip() or "(carne)",
                nome_cliente=campo_nome_cliente.value.strip() or "(nome do cliente)",
                valor=_valor_unitario_digitado(), data_hora=datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                operador_nome=estado.operador_nome, caixa_nome=estado.caixa_nome,
                nome_churrasqueira=_nome_cor(bloco["cor_hex"]),
            )
            imagem_preview.src_base64 = base64.b64encode(png).decode("ascii")
            painel_dados.visible = False
            painel_preview.visible = True
            # Pedido do usuario (2026-08-11): o botao "Cancelar" do dialogo
            # (em `dlg.actions`) fica visivel em TODOS os paineis, inclusive
            # a pre-visualizacao - clicar nele ali fechava o dialogo inteiro
            # e cancelava a venda, algo que parecia acontecer "so por olhar a
            # pre-visualizacao". Escondido enquanto o preview esta aberto -
            # a unica volta dali e "Fechar pré-visualização", que NAO cancela.
            botao_cancelar_venda.visible = False
            dlg.update()

        def fechar_preview(e=None):
            painel_preview.visible = False
            painel_dados.visible = True
            botao_cancelar_venda.visible = True
            dlg.update()

        imagem_preview = ft.Image(fit=ft.ImageFit.CONTAIN)
        painel_preview = ft.Column(
            [
                ft.Container(
                    content=imagem_preview, bgcolor="#FFFFFF", padding=8, border_radius=theme.RADIUS,
                ),
                ft.Row([ft.TextButton("Fechar pré-visualização", icon=ft.icons.ARROW_BACK, on_click=fechar_preview)],
                       alignment=ft.MainAxisAlignment.CENTER),
            ],
            tight=True, spacing=10, visible=False,
        )

        campo_valor_unitario.on_change = atualizar_total
        texto_total = ft.Text(_fmt(Decimal("0")), size=15, color=theme.TEXTO, weight=ft.FontWeight.W_700)
        painel_dados = ft.Column(
            [
                texto_bloco_atual,
                campo_nome_carne,
                campo_valor_unitario,
                campo_nome_cliente,
                ft.Row([ft.Text("Total:", color=theme.TEXTO_SUAVE), texto_total], alignment=ft.MainAxisAlignment.CENTER, spacing=8),
                ft.Row(
                    [ft.TextButton("Pré-visualizar ficha", icon=ft.icons.VISIBILITY, on_click=abrir_preview)],
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
                theme.botao_primario("Continuar", icone=ft.icons.ARROW_FORWARD, on_click=lambda e: ir_para_pagamento(e)),
            ],
            tight=True, spacing=14, visible=True,
        )

        # ---------- Passo 2: foi pago? -> forma de pagamento (igual a ficha normal) ----------

        campo_pago = theme.campo_texto("Valor recebido (R$)", width=200)
        caixa_troco, valor_troco = _criar_caixa_troco()
        texto_aviso_pago = ft.Text("", size=13, color=theme.ERRO, weight=ft.FontWeight.W_600)
        painel_dinheiro = ft.Container(visible=False)

        def recalcular_troco(e=None):
            total = venda_atual["valor_unitario"]
            try:
                pago = _parse_moeda(campo_pago.value)
            except ValueError:
                caixa_troco.visible = False
                texto_aviso_pago.value = ""
                dlg.update()
                return
            troco = pago - total
            if troco >= 0:
                valor_troco.value = _fmt(troco)
                caixa_troco.visible = True
                texto_aviso_pago.value = ""
            else:
                caixa_troco.visible = False
                texto_aviso_pago.value = "Valor recebido é menor que o total."
            dlg.update()

        campo_pago.on_change = recalcular_troco

        def confirmar_dinheiro(e=None):
            total = venda_atual["valor_unitario"]
            try:
                pago = _parse_moeda(campo_pago.value)
            except ValueError:
                componentes.aviso(page, "Informe o valor recebido.", cor=theme.ERRO)
                return
            if pago < total:
                componentes.aviso(page, "Valor recebido é menor que o total.", cor=theme.ERRO)
                return
            _finalizar("DINHEIRO")

        painel_dinheiro.content = ft.Column(
            [campo_pago, caixa_troco, texto_aviso_pago,
             ft.Row([theme.botao_primario("Confirmar", icone=ft.icons.CHECK, on_click=confirmar_dinheiro)],
                    alignment=ft.MainAxisAlignment.END)],
            spacing=10, tight=True,
        )

        def escolher_forma(codigo):
            def handler(e):
                if codigo == "DINHEIRO":
                    campo_pago.value = ""
                    caixa_troco.visible = False
                    texto_aviso_pago.value = ""
                    botoes_forma.visible = False
                    painel_dinheiro.visible = True
                    dlg.update()
                else:
                    _finalizar(codigo)
            return handler

        botoes_forma = ft.Column(
            [theme.botao_primario(nome, on_click=escolher_forma(codigo), largura=280)
             for codigo, nome in FORMAS_PAGAMENTO],
            spacing=8, visible=False,
        )

        # Pedido explicito do usuario: "foi pago" e a PRIMEIRA pergunta - só
        # mostra as formas de pagamento depois de responder "Sim". Responder
        # "Não" registra e imprime a ficha na hora mesmo assim, só sem forma
        # de pagamento definida ainda ("no fio") - fica pendente até alguém
        # finalizar o pagamento de verdade em "Buscar fichas".
        def mostrar_formas_pagamento(e=None):
            pergunta_pago.visible = False
            botoes_forma.visible = True
            dlg.update()

        pergunta_pago = ft.Column(
            [
                ft.Text("Essa ficha foi paga agora?", color=theme.TEXTO, size=15, weight=ft.FontWeight.W_700),
                ft.Row(
                    [
                        theme.botao_primario("Sim, foi pago", icone=ft.icons.CHECK, on_click=mostrar_formas_pagamento),
                        theme.botao_secundario("Não, fica pendente", icone=ft.icons.SCHEDULE,
                                               on_click=lambda e: _finalizar(None, pago=False)),
                    ],
                    spacing=10, wrap=True,
                ),
            ],
            spacing=12, visible=True,
        )

        def voltar_para_dados(e=None):
            painel_pagamento.visible = False
            pergunta_pago.visible = True
            botoes_forma.visible = False
            painel_dinheiro.visible = False
            painel_dados.visible = True
            dlg.update()

        painel_pagamento = ft.Column(
            [
                ft.TextButton("< Voltar", on_click=voltar_para_dados),
                pergunta_pago,
                botoes_forma,
                painel_dinheiro,
            ],
            tight=True, spacing=14, visible=False,
        )

        botao_cancelar_venda = ft.TextButton("Cancelar", on_click=lambda e: componentes.fechar_dialogo(page, dlg))
        dlg = ft.AlertDialog(
            modal=True, bgcolor=theme.SURFACE,
            title=ft.Text("Nova ficha", color=theme.TEXTO),
            content=ft.Column(
                [painel_dados, painel_pagamento, painel_preview],
                tight=True, spacing=16, width=320, scroll=ft.ScrollMode.AUTO,
            ),
            actions=[botao_cancelar_venda],
        )
        page.dialog = dlg
        dlg.open = True
        page.update()

    # `area_acao` e o elemento MAIS IMPORTANTE da tela (pedido explicito do
    # usuario, 2026-08-11) - fica com expand=True pra ocupar toda a altura
    # que sobra depois da linha de topo (blocos+resumo) e centraliza o card
    # grande dentro desse espaco, tanto na horizontal quanto na vertical.
    area_acao = ft.Container(alignment=ft.alignment.center, expand=True)

    def _cartao_central(conteudo):
        largura_disponivel = (page.width or 900) - 40
        return ft.Container(
            content=conteudo,
            bgcolor=theme.SURFACE, border=ft.border.all(1, theme.BORDA), border_radius=theme.RADIUS * 2,
            padding=ft.padding.symmetric(56, 64), width=min(600, largura_disponivel),
            shadow=ft.BoxShadow(blur_radius=32, color="#00000055", offset=ft.Offset(0, 10)),
        )

    def _botao_nova_ficha_grande():
        # Botao de destaque MAIOR so pra essa acao (a principal da tela) -
        # reaproveita as mesmas cores/forma/estilo de `theme.botao_primario`
        # (mesmo `text=`/`icon=`, pra continuar identificavel como sempre),
        # só com escala bem maior via `width`/`height`/`text_style`.
        return ft.ElevatedButton(
            text="Nova ficha", icon=ft.icons.ADD, on_click=abrir_dialogo_venda,
            width=320, height=76,
            style=ft.ButtonStyle(
                bgcolor={"": theme.BRASA, "hovered": theme.BRASA_CLARA, "disabled": theme.BORDA},
                color={"": theme.TEXTO, "disabled": theme.TEXTO_FRACO},
                shape=ft.RoundedRectangleBorder(radius=theme.RADIUS),
                elevation={"": 0},
                text_style=ft.TextStyle(size=22, weight=ft.FontWeight.W_700),
            ),
        )

    def recarregar_area_acao(atualizar_pagina=True):
        if not blocos_cache["lista"]:
            area_acao.content = _cartao_central(
                ft.Column(
                    [
                        ft.Container(
                            content=ft.Icon(ft.icons.PALETTE, color=theme.TEXTO_FRACO, size=40),
                            width=92, height=92, border_radius=46, bgcolor=theme.SURFACE_ALTA,
                            alignment=ft.alignment.center,
                        ),
                        ft.Text("Configure os blocos de numeração", color=theme.TEXTO, size=19,
                                weight=ft.FontWeight.W_700, text_align=ft.TextAlign.CENTER),
                        theme.subtitulo("Defina de qual número até qual outro cada churrasqueira é responsável.", tamanho=15),
                        theme.botao_primario("Configurar faixas de numeração", icone=ft.icons.SETTINGS,
                                             on_click=abrir_configuracao_faixas, largura=300),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=16,
                ),
            )
        elif bloco_ativo["id"] is None:
            area_acao.content = _cartao_central(
                ft.Column(
                    [
                        ft.Container(
                            content=ft.Icon(ft.icons.BLOCK, color=theme.ERRO, size=40),
                            width=92, height=92, border_radius=46, bgcolor=theme.SURFACE_ALTA,
                            alignment=ft.alignment.center,
                        ),
                        ft.Text("Todos os blocos estão esgotados", color=theme.TEXTO, size=19,
                                weight=ft.FontWeight.W_700, text_align=ft.TextAlign.CENTER),
                        theme.subtitulo("Aumente o intervalo de um bloco ou adicione um novo pra continuar vendendo.", tamanho=15),
                        theme.botao_primario("Configurar faixas de numeração", icone=ft.icons.SETTINGS,
                                             on_click=abrir_configuracao_faixas, largura=300),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=16,
                ),
            )
        else:
            bloco = _bloco_por_id(bloco_ativo["id"])
            area_acao.content = _cartao_central(
                ft.Column(
                    [
                        ft.Container(
                            content=ft.Icon(ft.icons.OUTDOOR_GRILL, color=theme.BRASA_CLARA, size=58),
                            width=124, height=124, border_radius=62, bgcolor=theme.SURFACE_ALTA,
                            alignment=ft.alignment.center, border=ft.border.all(3, bloco["cor_hex"]),
                        ),
                        ft.Text("Pronto pra vender", color=theme.TEXTO, size=26, weight=ft.FontWeight.W_800),
                        theme.subtitulo(
                            f"Bloco atual: {_nome_cor(bloco['cor_hex'])} — próxima ficha Nº {bloco['proximo_numero']}",
                            tamanho=16,
                        ),
                        _botao_nova_ficha_grande(),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=20,
                ),
            )
        if atualizar_pagina:
            try:
                area_acao.update()
            except Exception:
                pass

    atualizar_blocos(atualizar_pagina=False)

    # ---------- Buscar fichas (nome, numero, churrasqueira, data/hora) ----------

    def abrir_busca_fichas(e=None):
        campo_nome = theme.campo_texto("Nome do cliente", width=220)
        campo_numero = theme.campo_texto("Nº da ficha", width=110)
        try:
            cores_disponiveis = [f["cor_hex"] for f in repository.listar_faixas_numeracao_churrasco(evento["id"])]
        except ConexaoIndisponivel:
            cores_disponiveis = []
        dropdown_cor = ft.Dropdown(
            label="Churrasqueira", width=200, value="",
            options=[ft.dropdown.Option("", "Todas")] + [ft.dropdown.Option(cor, _nome_cor(cor)) for cor in cores_disponiveis],
            border_color=theme.BORDA, focused_border_color=theme.BRASA, bgcolor=theme.SURFACE_ALTA,
        )
        # Bug real reportado pelo usuario/cliente (2026-08-11, telas menores):
        # `lista_resultados` tinha altura FIXA (380px) e o dialogo em volta
        # nao tinha altura nem scroll proprio - numa tela mais baixa o
        # dialogo passava da altura disponivel e o botao "Fechar" (fixo nas
        # `actions` do AlertDialog) acabava sobrepondo o final da lista de
        # resultados (ex: "Fechar" por cima de "Finalizar pagamento" da
        # ultima ficha visivel). Corrigido dando scroll+altura ao dialogo
        # INTEIRO (ver `dlg` mais abaixo) - so uma area de rolagem, sem
        # `lista_resultados` competir com o dialogo por scroll/altura proprios.
        lista_resultados = ft.Column(spacing=8)

        # Pedido do usuario (bug real, 2026-08-11): confirmar cancelamento e
        # finalizar pagamento eram dialogos SEPARADOS abertos por CIMA deste -
        # reatribuir page.dialog pra outro objeto e tentar restaurar depois
        # deixava os botoes mortos ao voltar (mesma causa do bug da
        # pre-visualizacao de ficha, ver abrir_dialogo_venda). Em vez disso,
        # sao mais 2 paineis alternando visible=True/False DENTRO do MESMO
        # dialogo de busca - nunca troca page.dialog.

        def _voltar_para_busca(e=None):
            painel_confirmar_cancelamento.visible = False
            painel_pagamento_pendente.visible = False
            painel_busca.visible = True
            dlg.update()

        ficha_selecionada = {"valor": None}
        texto_confirmar_cancelamento = ft.Text("", color=theme.TEXTO, size=14)

        def _executar_cancelamento(e=None):
            ficha = ficha_selecionada["valor"]
            try:
                repository.cancelar_ficha_churrasco(ficha["id"], "Cancelada pelo operador")
            except ValueError as ex:
                componentes.aviso(page, str(ex), cor=theme.ALERTA)
                return
            except ConexaoIndisponivel:
                componentes.dialogo_erro_conexao(page)
                return
            _voltar_para_busca()
            buscar()
            atualizar_totais()
            componentes.aviso(page, "Ficha cancelada.")

        def cancelar(ficha):
            ficha_selecionada["valor"] = ficha
            texto_confirmar_cancelamento.value = (
                f"Cancelar a ficha Nº {ficha['numero_ficha']} ({ficha['nome_carne']} - {ficha['nome_cliente']})?"
            )
            painel_busca.visible = False
            painel_confirmar_cancelamento.visible = True
            dlg.update()

        painel_confirmar_cancelamento = ft.Column(
            [
                theme.subtitulo("Cancelar ficha"),
                texto_confirmar_cancelamento,
                ft.Row(
                    [ft.TextButton("Voltar", on_click=_voltar_para_busca),
                     theme.botao_primario("Cancelar ficha", icone=ft.icons.CANCEL, on_click=_executar_cancelamento)],
                    alignment=ft.MainAxisAlignment.END, spacing=10,
                ),
            ],
            spacing=16, tight=True, visible=False,
        )

        def alternar_entregue(ficha, checkbox):
            def handler(e):
                try:
                    repository.marcar_ficha_entregue(ficha["id"], checkbox.value)
                except ValueError as ex:
                    componentes.aviso(page, str(ex), cor=theme.ALERTA)
                    checkbox.value = not checkbox.value
                except ConexaoIndisponivel:
                    componentes.dialogo_erro_conexao(page)
                    checkbox.value = not checkbox.value
                checkbox.update()
            return handler

        texto_finalizar_pagamento = ft.Text("", color=theme.TEXTO, size=15, weight=ft.FontWeight.W_700)

        def _escolher_forma_pendente(codigo):
            def handler(e):
                ficha = ficha_selecionada["valor"]
                try:
                    repository.finalizar_pagamento_ficha(ficha["id"], codigo)
                except ValueError as ex:
                    componentes.aviso(page, str(ex), cor=theme.ALERTA)
                    return
                except ConexaoIndisponivel:
                    componentes.dialogo_erro_conexao(page)
                    return
                _voltar_para_busca()
                buscar()
                atualizar_totais()
                componentes.aviso(page, f"Pagamento da ficha Nº {ficha['numero_ficha']} confirmado.")
            return handler

        botoes_forma_pendente = ft.Column(
            [theme.botao_primario(nome, on_click=_escolher_forma_pendente(codigo), largura=280)
             for codigo, nome in FORMAS_PAGAMENTO],
            spacing=8, tight=True,
        )
        painel_pagamento_pendente = ft.Column(
            [
                ft.TextButton("< Voltar", on_click=_voltar_para_busca),
                texto_finalizar_pagamento,
                botoes_forma_pendente,
            ],
            spacing=10, tight=True, visible=False,
        )

        def abrir_finalizar_pagamento(ficha):
            ficha_selecionada["valor"] = ficha
            texto_finalizar_pagamento.value = f"Finalizar pagamento - Nº {ficha['numero_ficha']}"
            painel_busca.visible = False
            painel_pagamento_pendente.visible = True
            dlg.update()

        def _linha_resultado(f):
            cancelada = f["status"] == "CANCELADA"
            data_hora = f["criado_em"].strftime("%d/%m/%Y %H:%M")
            checkbox_entregue = ft.Checkbox(label="Entregue", value=f["entregue"], label_style=ft.TextStyle(color=theme.TEXTO_SUAVE, size=12))
            checkbox_entregue.on_change = alternar_entregue(f, checkbox_entregue)
            linhas = [
                ft.Row(
                    [
                        ft.Text(f"Nº {f['numero_ficha']}", color=theme.TEXTO, weight=ft.FontWeight.W_700, width=55),
                        ft.Container(width=12, height=12, bgcolor=f["cor_hex"], border_radius=3),
                        ft.Column(
                            [
                                ft.Text(f"{f['nome_cliente']} - {f['nome_carne']}", color=theme.TEXTO, size=13),
                                ft.Text(f"{data_hora} - {f['operador_nome']} - {f['caixa_nome']}",
                                        color=theme.TEXTO_SUAVE, size=11),
                            ], spacing=0, expand=True,
                        ),
                        ft.Text(f"R$ {f['valor']:.2f}".replace(".", ","), color=theme.TEXTO, width=75),
                        (ft.Text("Cancelada", color=theme.ERRO, size=12, width=80) if cancelada else
                         ft.IconButton(ft.icons.CANCEL_OUTLINED, icon_color=theme.ERRO, icon_size=18,
                                       tooltip="Cancelar ficha", on_click=lambda e, ficha=f: cancelar(ficha))),
                    ],
                ),
            ]
            if not cancelada:
                linhas.append(
                    ft.Row(
                        [
                            checkbox_entregue,
                            (ft.Container(
                                content=ft.Row(
                                    [ft.Icon(ft.icons.WARNING_AMBER, color=theme.ALERTA, size=14),
                                     ft.Text("NÃO PAGA", color=theme.ALERTA, size=12, weight=ft.FontWeight.W_700)],
                                    spacing=4, tight=True,
                                ),
                                bgcolor=theme.SURFACE, border=ft.border.all(1, theme.ALERTA),
                                border_radius=12, padding=ft.padding.symmetric(3, 10),
                            ) if not f["pago"] else
                             ft.Text(NOME_FORMA_PAGAMENTO.get(f["forma_pagamento"], f["forma_pagamento"] or ""),
                                     color=theme.TEXTO_SUAVE, size=12)),
                            (theme.botao_secundario("Finalizar pagamento", icone=ft.icons.PAYMENTS, altura=32,
                                                     on_click=lambda e, ficha=f: abrir_finalizar_pagamento(ficha))
                             if not f["pago"] else ft.Container()),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN, spacing=8,
                    ),
                )
            return ft.Container(
                content=ft.Column(linhas, spacing=8, tight=True),
                bgcolor=theme.SURFACE_ALTA, border_radius=theme.RADIUS, padding=ft.padding.symmetric(8, 12),
                opacity=0.5 if cancelada else 1,
                border=ft.border.all(1, theme.ALERTA) if (not cancelada and not f["pago"]) else None,
            )

        def buscar(e=None, atualizar_pagina=True):
            # atualizar_pagina=False na 1a chamada (linha abaixo, antes do
            # dialogo existir de verdade) - chamar lista_resultados.update()
            # com o controle ainda fora da pagina lanca excecao (mesma classe
            # de bug do editor de combo, ver memoria do projeto) e o clique
            # em "Buscar fichas" parecia simplesmente nao fazer nada.
            try:
                numero = int(campo_numero.value) if campo_numero.value.strip() else None
            except ValueError:
                numero = None
            try:
                resultados = repository.buscar_fichas_churrasco(
                    evento["id"],
                    nome_cliente=campo_nome.value.strip() or None,
                    numero_ficha=numero,
                    cor_hex=dropdown_cor.value or None,
                )
            except ConexaoIndisponivel:
                if atualizar_pagina:
                    componentes.dialogo_erro_conexao(page)
                return
            lista_resultados.controls = [_linha_resultado(f) for f in resultados] or [
                ft.Text("Nenhuma ficha encontrada.", color=theme.TEXTO_FRACO, size=13)
            ]
            if atualizar_pagina:
                lista_resultados.update()

        campo_nome.on_submit = buscar
        campo_numero.on_submit = buscar
        dropdown_cor.on_change = buscar

        buscar(atualizar_pagina=False)

        painel_busca = ft.Column(
            [
                ft.Row([campo_nome, campo_numero, dropdown_cor], spacing=10, wrap=True),
                theme.botao_secundario("Buscar", icone=ft.icons.SEARCH, on_click=buscar),
                ft.Divider(color=theme.BORDA),
                lista_resultados,
            ],
            tight=True, spacing=12, visible=True,
        )

        altura_dialogo = max(300, min(560, (page.height or 760) - 200))
        dlg = ft.AlertDialog(
            modal=True, bgcolor=theme.SURFACE,
            title=ft.Text("Buscar fichas", color=theme.TEXTO),
            content=ft.Column(
                [painel_busca, painel_confirmar_cancelamento, painel_pagamento_pendente],
                tight=True, spacing=12, width=460, height=altura_dialogo, scroll=ft.ScrollMode.AUTO,
            ),
            actions=[ft.TextButton("Fechar", on_click=lambda e: componentes.fechar_dialogo(page, dlg))],
        )
        page.dialog = dlg
        dlg.open = True
        page.update()

    def _voltar(e=None):
        _polling_ativo["on"] = False
        ao_voltar()

    barra_topo = ft.Container(
        content=ft.Row(
            [
                ft.Row(
                    [
                        ft.IconButton(ft.icons.ARROW_BACK, icon_color=theme.TEXTO, on_click=_voltar),
                        ft.Text("Módulo Churrasco", color=theme.TEXTO, size=18, weight=ft.FontWeight.W_700),
                    ],
                    spacing=8,
                ),
                ft.Row(
                    [
                        theme.botao_secundario("Faixas de numeração", icone=ft.icons.PALETTE, on_click=abrir_configuracao_faixas),
                        theme.botao_secundario("Buscar fichas", icone=ft.icons.SEARCH, on_click=abrir_busca_fichas),
                    ],
                    spacing=8,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        ),
        padding=ft.padding.symmetric(8, 16), bgcolor=theme.SURFACE,
        border=ft.border.only(bottom=ft.BorderSide(1, theme.BORDA)),
    )

    # Pedido explicito do usuario (2026-08-11): manter a MESMA estrutura de
    # sempre - "Escolha o bloco" no canto superior ESQUERDO, "Total vendido"
    # no canto superior DIREITO, e o card "Pronto pra vender" grande e
    # centralizado no espaco que sobra. So refinamento visual (espacamento/
    # hierarquia), sem mudar posicoes nem inventar layout novo.
    secao_resumo = ft.Container(
        content=ft.Column(
            [
                theme.subtitulo("Total vendido por churrasqueira (atualiza automaticamente):", tamanho=13),
                painel_totais,
            ],
            spacing=14,
        ),
        bgcolor=theme.SURFACE, border=ft.border.all(1, theme.BORDA), border_radius=theme.RADIUS,
        padding=20,
    )

    secao_blocos = ft.Container(
        content=ft.Column(
            [
                theme.subtitulo("Escolha o bloco que está vendendo agora (clique pra trocar):", tamanho=13),
                linha_blocos,
            ],
            spacing=14,
        ),
        bgcolor=theme.SURFACE, border=ft.border.all(1, theme.BORDA), border_radius=theme.RADIUS,
        padding=20,
    )

    LARGURA_QUEBRA_CHURRASCO = 900

    def _linha_topo(largo):
        if largo:
            # Row por padrao CENTRALIZA os filhos no eixo vertical (cross
            # axis) em vez de alinhar no topo - sem `vertical_alignment`
            # explicito os paineis "flutuam" fora do lugar. Mesmo fix ja
            # usado em relatorios.py pra esse exato problema.
            return ft.Row(
                [secao_blocos, secao_resumo],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.START,
                spacing=18,
            )
        # Tela estreita: sem espaco pra ficarem lado a lado sem apertar - os
        # 2 paineis empilham (bloco continua vindo primeiro), o card de
        # vender continua sempre depois deles, nunca escondido.
        return ft.Column([secao_blocos, secao_resumo], spacing=18)

    def _montar_corpo(largo):
        return ft.Column([_linha_topo(largo), area_acao], spacing=18, expand=True)

    corpo = ft.Container(padding=18, expand=True)

    def _ajustar_layout(e=None):
        recarregar_area_acao(atualizar_pagina=False)
        largo = (page.width or 1000) >= LARGURA_QUEBRA_CHURRASCO
        corpo.content = _montar_corpo(largo)
        try:
            corpo.update()
        except Exception:
            pass

    page.on_resized = _ajustar_layout
    _ajustar_layout()

    threading.Thread(target=_atualizar_totais_em_segundo_plano, daemon=True).start()

    return ft.Container(
        content=ft.Column([barra_topo, corpo], spacing=0, expand=True),
        expand=True, bgcolor=theme.BG,
    )
