import base64
import threading
import time
import traceback
from datetime import datetime
from decimal import Decimal, InvalidOperation

import flet as ft

from config import settings
from db import repository
from db.connection import ConexaoIndisponivel
from printing import escpos_printer, templates
from ui import componentes, theme

INTERVALO_VERIFICAR_NOVIDADE_SEGUNDOS = 8


def _logar_erro(contexto: str, ex: Exception) -> None:
    """Mesmo padrao de ui/screens/configuracao.py: sem isso, uma excecao
    "estranha" (que nao seja ConexaoIndisponivel/ValueError) dentro de um
    clique desaparece SEM NENHUM AVISO no .exe empacotado (sem console) -
    bug real visto num video (2026-09-16): "Confirmar" no pagamento fechava
    o dialogo, o item continuava no carrinho, e nenhum erro aparecia na
    tela. Agora qualquer excecao assim fica registrada em
    %LOCALAPPDATA%\\SistemaChurrasco\\ui_errors.log."""
    try:
        caminho = settings.PASTA_DADOS_LOCAIS / "ui_errors.log"
        settings.PASTA_DADOS_LOCAIS.mkdir(parents=True, exist_ok=True)
        with open(caminho, "a", encoding="utf-8") as f:
            f.write(f"\n--- {contexto} ---\n")
            f.write(traceback.format_exc())
    except Exception:
        pass


def _assinatura_catalogo(produtos, categorias, evento):
    """Resumo comparavel do que este terminal tem carregado, pra saber se
    mudou algo desde a ultima vez (produto novo/editado, categoria nova,
    nome/rodape do evento alterado em outro caixa, ou ESTOQUE mudou - inclui
    estoque_atual de proposito, senao um caixa vendendo o ultimo item de um
    produto com estoque controlado nunca avisava os outros caixas que
    acabou, so na proxima vez que alguem clicasse "Atualizar" na mao)."""
    parte_produtos = tuple(sorted(
        (p["id"], p["nome"], str(p["preco"]), p["oculto"], p["categoria_id"], p["estoque_atual"])
        for p in produtos
    ))
    parte_categorias = tuple(sorted((c["id"], c["nome"]) for c in categorias))
    parte_evento = (evento["nome"], evento["rodape"])
    return (parte_produtos, parte_categorias, parte_evento)

FORMAS_PAGAMENTO = [
    ("DINHEIRO", "Dinheiro"),
    ("CARTAO_CREDITO", "Cartão Crédito"),
    ("CARTAO_DEBITO", "Cartão Débito"),
    ("PIX", "Pix"),
    ("CONSUMACAO", "Consumação"),
]
NOME_FORMA_PAGAMENTO = dict(FORMAS_PAGAMENTO)
NOME_FORMA_PAGAMENTO["VARIAS"] = "Pagamento dividido"


def _parse_moeda(texto: str) -> Decimal:
    texto = (texto or "").strip().replace(".", "").replace(",", ".")
    if not texto:
        raise ValueError("valor vazio")
    try:
        return Decimal(texto)
    except InvalidOperation:
        raise ValueError(f"valor invalido: {texto}")


def _fmt_num(valor) -> str:
    """Igual _fmt(), mas sem o prefixo 'R$' - pra preencher campos de texto
    editaveis (o usuario digita so o numero)."""
    return f"{valor:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")


def tela(page: ft.Page, estado, ao_fechar_caixa, ao_deslogar, ao_abrir_configuracao, ao_abrir_relatorios,
         ao_abrir_churrasco, ao_tentar_de_novo, ao_abrir_relatorio_gerencial=None) -> ft.Control:
    try:
        evento = repository.obter_evento_aberto()
        categorias = repository.listar_categorias()
        produtos = repository.listar_produtos(somente_ativos=True, incluir_ocultos=True)
        produtos = [p for p in produtos if not p["oculto"]]
        qtd_pedidos_caixa = {"valor": repository.contar_vendas_caixa_no_evento(estado.caixa_id, evento["id"])}
    except ConexaoIndisponivel:
        return componentes.tela_estado_erro("Não deu para carregar os produtos.", ao_tentar_de_novo)

    cfg_local = settings.load()
    categoria_selecionada = {"id": None}

    total_text = ft.Text("R$ 0,00", size=24, weight=ft.FontWeight.W_800, color=theme.TEXTO)
    texto_qtd_pedidos = ft.Text(
        f"{qtd_pedidos_caixa['valor']} pedido(s) feito(s) neste caixa",
        color=theme.TEXTO_SUAVE, size=12, weight=ft.FontWeight.W_600,
    )
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

    LIMITE_ESTOQUE_BAIXO = 5

    def _aviso_estoque(produto):
        if not produto["estoque_controlado"] or produto["estoque_atual"] is None:
            return None
        estoque = produto["estoque_atual"]
        if estoque <= 0:
            return ft.Text("ESGOTADO", color="#FFFFFF", size=11, weight=ft.FontWeight.W_800,
                            bgcolor=theme.ERRO)
        if estoque <= LIMITE_ESTOQUE_BAIXO:
            return ft.Text(f"Só restam {estoque}!", color="#FFFFFF", size=11, weight=ft.FontWeight.W_800,
                            bgcolor=theme.ALERTA)
        return None

    def _produto_tile(produto):
        conteudo = [
            ft.Text(produto["nome"], color="#FFFFFF", weight=ft.FontWeight.W_700, size=15,
                     max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
            ft.Text(_fmt(produto["preco"]), color="#FFFFFF", size=14, weight=ft.FontWeight.W_500, opacity=0.9),
        ]
        aviso_estoque = _aviso_estoque(produto)
        if aviso_estoque:
            conteudo.append(aviso_estoque)
        return ft.Container(
            content=ft.Column(conteudo, spacing=6),
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

    assinatura_carregada = {"valor": _assinatura_catalogo(produtos, categorias, evento)}
    banner_novidade = ft.Container(visible=False)

    def recarregar_dados(e=None):
        """Produto/categoria/nome do evento alterado em outro caixa nao aparece
        sozinho aqui - essa tela so carrega quando abre. Isso busca de novo."""
        nonlocal produtos, categorias, evento
        try:
            evento = repository.obter_evento_aberto()
            categorias = repository.listar_categorias()
            novos_produtos = repository.listar_produtos(somente_ativos=True, incluir_ocultos=True)
            produtos = [p for p in novos_produtos if not p["oculto"]]
        except ConexaoIndisponivel:
            componentes.aviso(page, "Não deu para atualizar - sem conexão.", cor=theme.ERRO)
            return
        chips_categorias.controls = [_chip("Todos", None)] + [_chip(c["nome"], c["id"]) for c in categorias]
        categoria_selecionada["id"] = None
        texto_nome_evento.value = evento["nome"]
        atualizar_grade()
        texto_nome_evento.update()
        assinatura_carregada["valor"] = _assinatura_catalogo(produtos, categorias, evento)
        banner_novidade.visible = False
        banner_novidade.update()
        if e is not None:
            componentes.aviso(page, "Atualizado.")

    banner_novidade.content = ft.Row(
        [
            ft.Row(
                [ft.Icon(ft.icons.SYNC, color=theme.ALERTA, size=18),
                 ft.Text("Tem novidade no cadastro (produto/evento) que ainda não apareceu aqui.",
                          color=theme.TEXTO, size=13)],
                spacing=8,
            ),
            theme.botao_secundario("Atualizar agora", on_click=recarregar_dados),
        ],
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
    )
    banner_novidade.bgcolor = theme.SURFACE_ALTA
    banner_novidade.padding = ft.padding.symmetric(8, 16)
    banner_novidade.border_radius = theme.RADIUS
    banner_novidade.border = ft.border.all(1, theme.ALERTA)

    # Atualizacao automatica NAO fica nesta tela de proposito: aqui e onde o
    # evento esta rolando de verdade (vendas acontecendo). Baixar/instalar uma
    # atualizacao fecha o app por alguns segundos - isso so e seguro no momento
    # de abrir o app (tela de login, antes de comecar a vender), ver
    # ui/screens/login.py.

    _polling_ativo = {"on": True}

    def _verificar_novidade_em_segundo_plano():
        while _polling_ativo["on"]:
            time.sleep(INTERVALO_VERIFICAR_NOVIDADE_SEGUNDOS)
            if not _polling_ativo["on"]:
                return
            try:
                evento_db = repository.obter_evento_aberto()
                categorias_db = repository.listar_categorias()
                produtos_db = repository.listar_produtos(somente_ativos=True, incluir_ocultos=True)
                produtos_db = [p for p in produtos_db if not p["oculto"]]
            except ConexaoIndisponivel:
                continue
            if not evento_db:
                continue
            assinatura_nova = _assinatura_catalogo(produtos_db, categorias_db, evento_db)
            if assinatura_nova != assinatura_carregada["valor"] and not banner_novidade.visible:
                banner_novidade.visible = True
                try:
                    banner_novidade.update()
                except Exception:
                    return  # tela ja foi trocada/pagina fechou

    def _parar_polling_e_chamar(fn):
        def wrapper(*args, **kwargs):
            _polling_ativo["on"] = False
            return fn(*args, **kwargs)
        return wrapper

    threading.Thread(target=_verificar_novidade_em_segundo_plano, daemon=True).start()

    # ---------- Finalizar venda ----------

    _pagamento_aberto = {"valor": False}

    def abrir_dialogo_pagamento(e):
        if not estado.carrinho:
            componentes.aviso(page, "Carrinho vazio.", cor=theme.ALERTA)
            return
        # Bug real relatado (2026-09-16/17): clicar "Finalizar venda" cria um
        # ft.AlertDialog NOVO a cada chamada - se o clique disparar 2x (ex:
        # duplo clique, ou um primeiro clique que pareceu "nao fazer nada"
        # levando o operador a clicar de novo), o SEGUNDO dialogo substitui
        # page.dialog enquanto o PRIMEIRO ainda esta logicamente aberto -
        # exatamente a mesma classe de bug ja documentada no projeto (ver
        # memoria "feedback_flet_dialog_race"): os botoes do dialogo que o
        # operador ve na tela (o antigo) ficam "mortos" (fechar_dialogo/
        # finalizar acabam agindo sobre o dialogo ERRADO). Trava aqui pra
        # nunca abrir um segundo dialogo de pagamento por cima de outro.
        if _pagamento_aberto["valor"]:
            return
        _pagamento_aberto["valor"] = True

        total = Decimal(str(estado.total_carrinho()))

        def _criar_caixa_troco(tamanho=28):
            """Caixa destacada (fundo + borda verde) pro troco - pedido do
            usuario: o valor precisa "saltar aos olhos" pro operador, na
            pressa do balcao, sem precisar procurar um texto pequeno."""
            valor_texto = ft.Text("", size=tamanho, weight=ft.FontWeight.W_900, color=theme.SUCESSO)
            caixa = ft.Container(
                content=ft.Column(
                    [ft.Text("TROCO", size=12, color=theme.TEXTO_SUAVE, weight=ft.FontWeight.W_700),
                     valor_texto],
                    spacing=0, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                visible=False, bgcolor=theme.SURFACE_ALTA, border=ft.border.all(2, theme.SUCESSO),
                border_radius=theme.RADIUS, padding=ft.padding.symmetric(10, 16),
                alignment=ft.alignment.center,
            )
            return caixa, valor_texto

        # ---------- Modo rapido (padrao - um toque e pronto, como sempre foi) ----------

        campo_pago_rapido = theme.campo_texto("Valor recebido (R$)", width=200)
        caixa_troco_rapido, valor_troco_rapido = _criar_caixa_troco(tamanho=30)
        texto_aviso_pago_rapido = ft.Text("", size=13, color=theme.ERRO, weight=ft.FontWeight.W_600)

        def recalcular_troco_rapido(e=None):
            try:
                pago = _parse_moeda(campo_pago_rapido.value)
            except ValueError:
                caixa_troco_rapido.visible = False
                texto_aviso_pago_rapido.value = ""
                dlg.update()
                return
            troco = pago - total
            if troco >= 0:
                valor_troco_rapido.value = _fmt(troco)
                caixa_troco_rapido.visible = True
                texto_aviso_pago_rapido.value = ""
            else:
                caixa_troco_rapido.visible = False
                texto_aviso_pago_rapido.value = "Valor recebido é menor que o total."
            dlg.update()

        campo_pago_rapido.on_change = recalcular_troco_rapido

        def voltar_dinheiro_rapido(e=None):
            painel_dinheiro_rapido.visible = False
            modo_rapido.visible = True
            dlg.update()

        def confirmar_dinheiro_rapido(e):
            # Valor recebido nao e mais obrigatorio (pedido do usuario apos o
            # 1o evento) - campo vazio assume que recebeu certinho (sem
            # troco), pra nao travar quem so quer confirmar rapido.
            try:
                pago = _parse_moeda(campo_pago_rapido.value)
            except ValueError:
                pago = total
            if pago < total:
                componentes.aviso(page, "Valor recebido é menor que o total.", cor=theme.ERRO)
                return
            _fechar_pagamento()
            finalizar([{"forma": "DINHEIRO", "valor": total}])

        campo_pago_rapido.on_submit = confirmar_dinheiro_rapido

        painel_dinheiro_rapido = ft.Container(
            visible=False,
            content=ft.Column(
                [ft.Text(f"Total em dinheiro: {_fmt(total)}", color=theme.TEXTO, size=15, weight=ft.FontWeight.W_700),
                 campo_pago_rapido, caixa_troco_rapido, texto_aviso_pago_rapido,
                 ft.Row([ft.TextButton("Voltar", on_click=voltar_dinheiro_rapido),
                         theme.botao_primario("Confirmar", on_click=confirmar_dinheiro_rapido)],
                        alignment=ft.MainAxisAlignment.END)],
                spacing=10, tight=True,
            ),
        )

        def escolher_rapido(codigo, nome):
            def handler(e):
                if codigo == "DINHEIRO":
                    campo_pago_rapido.value = ""
                    caixa_troco_rapido.visible = False
                    texto_aviso_pago_rapido.value = ""
                    modo_rapido.visible = False
                    painel_dinheiro_rapido.visible = True
                    dlg.update()
                else:
                    _fechar_pagamento()
                    finalizar([{"forma": codigo, "valor": total}])
            return handler

        def abrir_modo_dividido(e):
            modo_rapido.visible = False
            painel_dividido.visible = True
            dlg.update()

        modo_rapido = ft.Column(
            [theme.botao_primario(nome, on_click=escolher_rapido(codigo, nome), largura=280)
             for codigo, nome in FORMAS_PAGAMENTO]
            + [ft.Divider(color=theme.BORDA),
               theme.botao_secundario("Várias formas", icone=ft.icons.CALL_SPLIT, on_click=abrir_modo_dividido, largura=280)],
            spacing=8,
        )

        # ---------- Modo dividido (várias formas na mesma venda) ----------
        # Um campo de valor por forma, todos visiveis de uma vez - digita o
        # quanto vai em cada forma (o resto fica 0,00) e confirma uma vez so.

        campos_valor_dividido = {
            codigo: theme.campo_texto(nome, value="0,00", width=170)
            for codigo, nome in FORMAS_PAGAMENTO
        }
        campo_pago_dividido = theme.campo_texto("Valor recebido em dinheiro (R$)", width=250, visible=False)
        caixa_troco_dividido, valor_troco_dividido = _criar_caixa_troco(tamanho=22)
        texto_aviso_dividido = ft.Text("", size=12, color=theme.ERRO, weight=ft.FontWeight.W_600)
        texto_restante_dividido = ft.Text(f"Restante: {_fmt(total)}", color=theme.TEXTO_SUAVE, size=14, weight=ft.FontWeight.W_600)
        btn_confirmar_dividido = theme.botao_primario("Confirmar pagamento", icone=ft.icons.CHECK, on_click=lambda e: confirmar_dividido(e))

        def _valor_campo(campo) -> Decimal:
            try:
                return _parse_moeda(campo.value)
            except ValueError:
                return Decimal("0")

        def recalcular_dividido(e=None):
            soma = sum((_valor_campo(c) for c in campos_valor_dividido.values()), Decimal("0"))
            restante = total - soma
            valor_dinheiro = _valor_campo(campos_valor_dividido["DINHEIRO"])
            campo_pago_dividido.visible = valor_dinheiro > 0
            if campo_pago_dividido.visible:
                pago = _valor_campo(campo_pago_dividido)
                troco = pago - valor_dinheiro
                if campo_pago_dividido.value.strip() in ("", "0,00"):
                    caixa_troco_dividido.visible = False
                    texto_aviso_dividido.value = ""
                elif troco >= 0:
                    valor_troco_dividido.value = _fmt(troco)
                    caixa_troco_dividido.visible = True
                    texto_aviso_dividido.value = ""
                else:
                    caixa_troco_dividido.visible = False
                    texto_aviso_dividido.value = "Valor recebido é menor que o valor em dinheiro."
            else:
                caixa_troco_dividido.visible = False
                texto_aviso_dividido.value = ""
            if restante > 0:
                texto_restante_dividido.value = f"Restante: {_fmt(restante)}"
                texto_restante_dividido.color = theme.TEXTO_SUAVE
            elif restante < 0:
                texto_restante_dividido.value = f"Passou {_fmt(-restante)} do total."
                texto_restante_dividido.color = theme.ERRO
            else:
                texto_restante_dividido.value = "Valores completam o total."
                texto_restante_dividido.color = theme.SUCESSO
            btn_confirmar_dividido.disabled = restante != 0
            dlg.update()

        for campo in campos_valor_dividido.values():
            campo.on_change = recalcular_dividido
        campo_pago_dividido.on_change = recalcular_dividido

        def confirmar_dividido(e):
            pagamentos_form = [
                {"forma": codigo, "valor": _valor_campo(campo)}
                for codigo, campo in campos_valor_dividido.items()
                if _valor_campo(campo) > 0
            ]
            if not pagamentos_form:
                componentes.aviso(page, "Informe o valor em pelo menos uma forma.", cor=theme.ALERTA)
                return
            soma = sum(p["valor"] for p in pagamentos_form)
            if abs(soma - total) > Decimal("0.01"):
                componentes.aviso(page, "Os valores não completam o total da venda.", cor=theme.ALERTA)
                return
            valor_dinheiro = _valor_campo(campos_valor_dividido["DINHEIRO"])
            if valor_dinheiro > 0:
                # Vazio = recebeu certinho, sem troco (mesma regra do modo rapido).
                pago = _valor_campo(campo_pago_dividido) if campo_pago_dividido.value.strip() else valor_dinheiro
                if pago < valor_dinheiro:
                    componentes.aviso(page, "Informe um valor recebido em dinheiro válido.", cor=theme.ERRO)
                    return
            _fechar_pagamento()
            finalizar(pagamentos_form)

        campo_pago_dividido.on_submit = confirmar_dividido

        def voltar_modo_rapido(e=None):
            for campo in campos_valor_dividido.values():
                campo.value = "0,00"
            campo_pago_dividido.value = ""
            painel_dividido.visible = False
            modo_rapido.visible = True
            dlg.update()

        btn_confirmar_dividido.disabled = True
        painel_dividido = ft.Container(
            visible=False,
            content=ft.Column(
                [ft.TextButton("< Voltar", on_click=voltar_modo_rapido),
                 theme.subtitulo("Digite o valor de cada forma usada - o restante some conforme completa."),
                 *campos_valor_dividido.values(),
                 campo_pago_dividido, caixa_troco_dividido, texto_aviso_dividido,
                 ft.Divider(color=theme.BORDA),
                 texto_restante_dividido, btn_confirmar_dividido],
                spacing=10, tight=True, scroll=ft.ScrollMode.AUTO,
            ),
        )

        def _fechar_pagamento(e=None):
            componentes.fechar_dialogo(page, dlg)
            _pagamento_aberto["valor"] = False

        dlg = ft.AlertDialog(
            modal=True, bgcolor=theme.SURFACE,
            title=ft.Text(f"Total: {_fmt(total)}", color=theme.TEXTO, size=20),
            content=ft.Column(
                [modo_rapido, painel_dinheiro_rapido, painel_dividido],
                tight=True, spacing=10, scroll=ft.ScrollMode.AUTO, width=320, height=520,
            ),
            actions=[ft.TextButton("Cancelar", on_click=_fechar_pagamento)],
        )
        page.dialog = dlg
        dlg.open = True
        page.update()

    # Impressora Bluetooth 80mm usada pelos vendedores andando pela festa -
    # ligada via app RawBT (ver db/modo_celular.py e memoria do projeto), que
    # recebe os mesmos bytes ESC/POS num link "rawbt:base64,...". 576 pontos
    # e a largura recomendada pra 80mm (a Elgin i9 do PC usa 58mm/384, esse
    # padrao continua em LARGURA_PONTOS dentro de templates.py).
    LARGURA_PONTOS_CELULAR = 576

    def _imprimir_via_rawbt(dados: bytes):
        dados_b64 = base64.b64encode(dados).decode("ascii")
        page.launch_url(f"rawbt:base64,{dados_b64}")

    def finalizar(pagamentos):
        if not estado.carrinho:
            componentes.aviso(page, "Carrinho vazio.", cor=theme.ALERTA)
            return
        itens = [dict(i) for i in estado.carrinho]
        try:
            resultado = repository.registrar_venda(
                estado.sessao_id, estado.caixa_id, estado.operador_id, itens, pagamentos,
            )
        except ConexaoIndisponivel:
            componentes.dialogo_erro_conexao(page, tentar_de_novo=None)
            return
        except ValueError as ex:
            # Estoque acabou de virar insuficiente (provavelmente outro caixa
            # vendeu o resto entre o carrinho ser montado e confirmar o
            # pagamento) - a venda inteira foi cancelada no banco, nada foi
            # descontado. Mantem o carrinho como esta (o operador decide se
            # remove o item ou tenta de novo) e atualiza a grade agora, na
            # hora, pra esse caixa ja ver o estoque certo sem precisar clicar
            # em "Atualizar".
            componentes.aviso(page, str(ex), cor=theme.ERRO)
            recarregar_dados()
            return
        except Exception as ex:
            # Qualquer outro erro (nao previsto) NUNCA pode desaparecer
            # silencioso - antes disso, o item ficava "preso" no carrinho
            # sem nenhum aviso (bug real visto por video, 2026-09-16).
            _logar_erro("finalizar venda - registrar_venda", ex)
            componentes.aviso(
                page, f"Não foi possível registrar a venda: {ex}. Veja ui_errors.log.", cor=theme.ERRO,
            )
            return

        qtd_pedidos_caixa["valor"] += 1
        texto_qtd_pedidos.value = f"{qtd_pedidos_caixa['valor']} pedido(s) feito(s) neste caixa"
        # CAUSA REAL do bug relatado (achado rodando o app de verdade, nao so
        # simulado, 2026-09-17): esse .update() sem guarda podia estourar
        # "Text Control must be added to the page first" (mesma classe de
        # bug ja documentada no projeto - ver memoria "Control.page e None
        # até o Flet montar de verdade"). Como essa linha fica ANTES do
        # try/except da impressao e SEM nenhum try/except proprio, a
        # excecao matava o resto da funcao inteira - a venda JA TINHA sido
        # registrada no banco (linha acima), mas o carrinho nunca esvaziava
        # e a ficha nunca imprimia, sem nenhum erro visivel nem log (essa
        # excecao acontecia ANTES dos pontos que ja tinham _logar_erro).
        # Confirmado ao vivo: rodando o app real (nao so o teste automatizado
        # que chama on_click direto) e clicando Pix, a venda apareceu no
        # banco (repository.vendas_por_caixa) mas a tela nunca atualizou -
        # exatamente "fica no carrinho, nao vai pra frente".
        try:
            if texto_qtd_pedidos.page:
                texto_qtd_pedidos.update()
        except Exception as ex:
            _logar_erro("finalizar venda - texto_qtd_pedidos.update", ex)

        try:
            itens_impressao = repository.expandir_itens_para_impressao(itens)
            if not itens_impressao:
                # Todos os itens do carrinho tem emitir_ficha=False (ex: so
                # doces, que ficam no proprio caixa) - venda ja foi
                # registrada acima, so nao ha nada pra imprimir.
                componentes.aviso(page, f"Pedido #{resultado['numero_pedido']} registrado (sem ficha pra imprimir).")
                estado.limpar_carrinho()
                atualizar_carrinho_ui()
                return
            dados = templates.fichas_venda_bytes(
                nome_evento=evento["nome"],
                numero_pedido=resultado["numero_pedido"],
                data_hora=datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                itens=itens_impressao,
                operador_nome=estado.operador_nome,
                caixa_nome=estado.caixa_nome,
                largura_pontos=LARGURA_PONTOS_CELULAR if page.web else templates.LARGURA_PONTOS,
                cortador_automatico=not page.web,
            )
            if page.web:
                _imprimir_via_rawbt(dados)
            else:
                escpos_printer.imprimir(cfg_local["impressora_windows"], dados)
        except Exception as ex:
            _logar_erro("finalizar venda - impressao", ex)
            componentes.aviso(
                page,
                f"Venda #{resultado['numero_pedido']} registrada, mas a impressão falhou: {ex}. "
                f"Abra \"Vendas recentes\" para tentar imprimir de novo.",
                cor=theme.ALERTA,
            )
        else:
            total_fichas = sum(i["quantidade"] for i in itens_impressao)
            componentes.aviso(page, f"Pedido #{resultado['numero_pedido']}: {total_fichas} ficha(s) impressa(s)!")

        estado.limpar_carrinho()
        atualizar_carrinho_ui()

    # ---------- Vendas recentes (cancelar / reimprimir) ----------

    def reimprimir_ficha(venda_id):
        try:
            detalhes = repository.detalhes_venda(venda_id)
        except ConexaoIndisponivel:
            componentes.dialogo_erro_conexao(page, tentar_de_novo=None)
            return
        venda_info = detalhes["venda"]
        try:
            itens_impressao = repository.expandir_itens_para_impressao(detalhes["itens"])
            dados = templates.fichas_venda_bytes(
                nome_evento=evento["nome"],
                numero_pedido=venda_info["numero_pedido"],
                data_hora=venda_info["criado_em"].strftime("%d/%m/%Y %H:%M:%S"),
                itens=itens_impressao,
                operador_nome=venda_info["operador_nome"],
                caixa_nome=venda_info["caixa_nome"],
                largura_pontos=LARGURA_PONTOS_CELULAR if page.web else templates.LARGURA_PONTOS,
                cortador_automatico=not page.web,
            )
            if page.web:
                _imprimir_via_rawbt(dados)
            else:
                escpos_printer.imprimir(cfg_local["impressora_windows"], dados)
        except Exception as ex:
            componentes.aviso(page, f"Não deu para reimprimir: {ex}", cor=theme.ERRO)
            return
        componentes.aviso(page, f"Pedido #{venda_info['numero_pedido']} reimpresso.")

    def abrir_dialogo_vendas_recentes(e):
        lista_coluna = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO, height=420)

        def carregar():
            try:
                vendas = repository.vendas_recentes(estado.sessao_id, limite=30)
            except ConexaoIndisponivel:
                lista_coluna.controls = [ft.Text("Sem conexão.", color=theme.ERRO)]
                lista_coluna.update()
                return
            lista_coluna.controls = [_linha_venda(v) for v in vendas] or [
                ft.Text("Nenhuma venda ainda nesta sessão.", color=theme.TEXTO_SUAVE)
            ]
            lista_coluna.update()

        def cancelar(venda_id, numero_pedido):
            campo_motivo = theme.campo_texto("Motivo do cancelamento (opcional)", width=320)

            def confirmar(e2):
                try:
                    repository.cancelar_venda(venda_id, campo_motivo.value or None)
                except ConexaoIndisponivel:
                    componentes.dialogo_erro_conexao(page, tentar_de_novo=None)
                    return
                except ValueError as ex:
                    componentes.aviso(page, str(ex), cor=theme.ALERTA)
                    return
                componentes.fechar_dialogo(page, dlg_cancelar)
                componentes.aviso(page, f"Pedido #{numero_pedido} cancelado.")
                carregar()

            dlg_cancelar = ft.AlertDialog(
                modal=True, bgcolor=theme.SURFACE,
                title=ft.Text(f"Cancelar pedido #{numero_pedido}?", color=theme.TEXTO),
                content=ft.Column([
                    ft.Text("Isso desfaz a venda e devolve o estoque controlado, se houver.",
                            color=theme.TEXTO_SUAVE, size=13),
                    campo_motivo,
                ], tight=True, spacing=10),
                actions=[
                    ft.TextButton("Voltar", on_click=lambda e2: componentes.fechar_dialogo(page, dlg_cancelar)),
                    theme.botao_perigo("Cancelar venda", on_click=confirmar),
                ],
            )
            page.dialog = dlg_cancelar
            dlg_cancelar.open = True
            page.update()

        def _linha_venda(v):
            cor_status = theme.ERRO if v["status"] == "CANCELADA" else theme.SUCESSO
            texto_status = "Cancelada" if v["status"] == "CANCELADA" else "Concluída"
            return ft.Container(
                content=ft.Row(
                    [
                        ft.Column(
                            [
                                ft.Text(f"Pedido #{v['numero_pedido']} · {_fmt(v['valor_total'])}",
                                        color=theme.TEXTO, weight=ft.FontWeight.W_600, size=14),
                                ft.Text(f"{v['criado_em'].strftime('%H:%M:%S')} · "
                                        f"{NOME_FORMA_PAGAMENTO.get(v['forma_pagamento'], v['forma_pagamento'])} · {texto_status}",
                                        color=cor_status, size=12),
                            ],
                            expand=True, spacing=2,
                        ),
                        ft.IconButton(ft.icons.PRINT, icon_color=theme.TEXTO_SUAVE, tooltip="Reimprimir ficha",
                                      on_click=lambda e2, vid=v["id"]: reimprimir_ficha(vid)),
                        ft.IconButton(ft.icons.CANCEL_OUTLINED, icon_color=theme.ERRO, tooltip="Cancelar venda",
                                      visible=v["status"] == "CONCLUIDA",
                                      on_click=lambda e2, vid=v["id"], ped=v["numero_pedido"]: cancelar(vid, ped)),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                bgcolor=theme.SURFACE_ALTA, border_radius=theme.RADIUS, padding=ft.padding.symmetric(6, 14),
            )

        dlg = ft.AlertDialog(
            modal=True, bgcolor=theme.SURFACE,
            title=ft.Text("Vendas recentes desta sessão", color=theme.TEXTO),
            content=ft.Container(lista_coluna, width=420),
            actions=[ft.TextButton("Fechar", on_click=lambda e2: componentes.fechar_dialogo(page, dlg))],
        )
        page.dialog = dlg
        dlg.open = True
        page.update()
        carregar()

    # ---------- Troca ----------

    def abrir_dialogo_troca(e):
        produtos_por_id = {p["id"]: p for p in produtos}
        opcoes_produto = [ft.dropdown.Option(str(p["id"]), f"{p['nome']} — {_fmt(p['preco'])}") for p in produtos]

        dropdown_saida = ft.Dropdown(label="Produto que o cliente devolveu", width=320, options=opcoes_produto,
                                      border_color=theme.BORDA, focused_border_color=theme.BRASA, bgcolor=theme.SURFACE_ALTA)
        campo_qtd_saida = theme.campo_texto("Quantidade devolvida", value="1", width=150)
        texto_subtotal_saida = ft.Text("", color=theme.TEXTO_SUAVE, size=12)

        dropdown_entrada = ft.Dropdown(label="Produto novo (opcional)", width=320,
                                        options=[ft.dropdown.Option("nenhum", "Nenhum - só devolver dinheiro")] + opcoes_produto,
                                        value="nenhum",
                                        border_color=theme.BORDA, focused_border_color=theme.BRASA, bgcolor=theme.SURFACE_ALTA)
        campo_qtd_entrada = theme.campo_texto("Quantidade nova", value="1", width=150)
        texto_subtotal_entrada = ft.Text("", color=theme.TEXTO_SUAVE, size=12)

        campo_motivo = theme.campo_texto("Motivo (opcional)", width=320)

        texto_resultado = ft.Text("", size=17, weight=ft.FontWeight.W_800)

        def ler_qtd(campo):
            try:
                valor = int(campo.value)
                return valor if valor > 0 else 1
            except (ValueError, TypeError):
                return 1

        def recalcular(e=None):
            if dropdown_saida.value:
                produto_saida = produtos_por_id[int(dropdown_saida.value)]
                qtd_saida = ler_qtd(campo_qtd_saida)
                subtotal_saida = produto_saida["preco"] * qtd_saida
                texto_subtotal_saida.value = f"{_fmt(produto_saida['preco'])} cada · {qtd_saida}x = {_fmt(subtotal_saida)}"
            else:
                subtotal_saida = None
                texto_subtotal_saida.value = ""

            if dropdown_entrada.value and dropdown_entrada.value != "nenhum":
                produto_entrada = produtos_por_id[int(dropdown_entrada.value)]
                qtd_entrada = ler_qtd(campo_qtd_entrada)
                subtotal_entrada = produto_entrada["preco"] * qtd_entrada
                texto_subtotal_entrada.value = f"{_fmt(produto_entrada['preco'])} cada · {qtd_entrada}x = {_fmt(subtotal_entrada)}"
                campo_qtd_entrada.disabled = False
            else:
                subtotal_entrada = 0
                texto_subtotal_entrada.value = ""
                campo_qtd_entrada.disabled = True

            if subtotal_saida is None:
                texto_resultado.value = ""
            else:
                diferenca = subtotal_entrada - subtotal_saida
                if diferenca < 0:
                    texto_resultado.value = f"Troco pro cliente: {_fmt(-diferenca)}"
                    texto_resultado.color = theme.SUCESSO
                elif diferenca > 0:
                    texto_resultado.value = f"Cliente paga a diferença: {_fmt(diferenca)}"
                    texto_resultado.color = theme.ALERTA
                else:
                    texto_resultado.value = "Sem diferença de valor"
                    texto_resultado.color = theme.TEXTO_SUAVE

            dlg.update()

        dropdown_saida.on_change = recalcular
        campo_qtd_saida.on_change = recalcular
        dropdown_entrada.on_change = recalcular
        campo_qtd_entrada.on_change = recalcular

        def confirmar(e):
            if not dropdown_saida.value:
                return
            produto_saida = produtos_por_id[int(dropdown_saida.value)]
            qtd_saida = ler_qtd(campo_qtd_saida)
            produto_entrada = None
            qtd_entrada = 0
            if dropdown_entrada.value and dropdown_entrada.value != "nenhum":
                produto_entrada = produtos_por_id[int(dropdown_entrada.value)]
                qtd_entrada = ler_qtd(campo_qtd_entrada)
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
                [
                    dropdown_saida, campo_qtd_saida, texto_subtotal_saida,
                    ft.Divider(color=theme.BORDA),
                    dropdown_entrada, campo_qtd_entrada, texto_subtotal_entrada,
                    ft.Divider(color=theme.BORDA),
                    texto_resultado,
                    campo_motivo,
                ],
                tight=True, spacing=10, scroll=ft.ScrollMode.AUTO, width=340,
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda e: componentes.fechar_dialogo(page, dlg)),
                theme.botao_primario("Confirmar", on_click=confirmar),
            ],
        )
        campo_qtd_entrada.disabled = True
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

    texto_nome_evento = ft.Text(evento["nome"], color=theme.TEXTO, size=16, weight=ft.FontWeight.W_700,
                                  max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
    texto_caixa_operador = ft.Text(f"{estado.caixa_nome} · {estado.operador_nome}", color=theme.TEXTO_SUAVE, size=12,
                                     max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)

    # No PC (tela larga) os botoes de acao ficam todos visiveis, como sempre
    # foi. Em telas menores eles somem e entram num menu "..." - nao cabe
    # uma fileira de 9 botoes de texto (Sangria...Trocar operador) + "Fechar
    # caixa" numa tela pequena/notebook. O limiar de 760px foi definido
    # quando essa fileira tinha bem menos botoes - com "Gerencial" e
    # "Relatorio gerencial" adicionados depois, 760px ja nao e largura o
    # suficiente pra caber tudo (bug real relatado, 2026-09-17: "Fechar
    # caixa" ficava sem espaco e desaparecia numa tela pequena, mesmo com o
    # wrap=True). Subido bem pra so usar o modo "completo" em monitor de
    # verdade largo - o modo compacto (icone "..." + Fechar caixa, bem mais
    # estreito) sobra espaco de verdade em qualquer tela menor que isso.
    LARGURA_QUEBRA = 1500

    menu_acoes = ft.PopupMenuButton(
        icon=ft.icons.MORE_VERT,
        icon_color=theme.TEXTO_SUAVE,
        visible=False,
        items=[
            ft.PopupMenuItem(text="Sangria", icon=ft.icons.ARROW_DOWNWARD,
                              on_click=lambda e: abrir_dialogo_movimento("Sangria", "SANGRIA")),
            ft.PopupMenuItem(text="Reforço", icon=ft.icons.ARROW_UPWARD,
                              on_click=lambda e: abrir_dialogo_movimento("Reforço", "REFORCO")),
            ft.PopupMenuItem(text="Troca", icon=ft.icons.SWAP_HORIZ, on_click=abrir_dialogo_troca),
            ft.PopupMenuItem(text="Churrasco", icon=ft.icons.OUTDOOR_GRILL,
                              on_click=lambda e: _parar_polling_e_chamar(ao_abrir_churrasco)()),
            ft.PopupMenuItem(text="Vendas recentes", icon=ft.icons.RECEIPT_LONG, on_click=abrir_dialogo_vendas_recentes),
            ft.PopupMenuItem(text="Relatórios", icon=ft.icons.BAR_CHART,
                              on_click=lambda e: _parar_polling_e_chamar(ao_abrir_relatorios)()),
            ft.PopupMenuItem(text="Relatório gerencial (caixa aberto)", icon=ft.icons.INSIGHTS,
                              on_click=lambda e: _parar_polling_e_chamar(ao_abrir_relatorio_gerencial)()),
            ft.PopupMenuItem(text="Configurações", icon=ft.icons.SETTINGS,
                              on_click=lambda e: _parar_polling_e_chamar(ao_abrir_configuracao)()),
            ft.PopupMenuItem(text="Trocar operador", icon=ft.icons.LOGOUT,
                              on_click=lambda e: _parar_polling_e_chamar(ao_deslogar)()),
        ],
    )

    botoes_completos = ft.Row(
        [
            theme.botao_secundario("Sangria", icone=ft.icons.ARROW_DOWNWARD,
                                    on_click=lambda e: abrir_dialogo_movimento("Sangria", "SANGRIA")),
            theme.botao_secundario("Reforço", icone=ft.icons.ARROW_UPWARD,
                                    on_click=lambda e: abrir_dialogo_movimento("Reforço", "REFORCO")),
            theme.botao_secundario("Troca", icone=ft.icons.SWAP_HORIZ, on_click=abrir_dialogo_troca),
            theme.botao_secundario("Churrasco", icone=ft.icons.OUTDOOR_GRILL,
                                    on_click=lambda e: _parar_polling_e_chamar(ao_abrir_churrasco)()),
            theme.botao_secundario("Vendas recentes", icone=ft.icons.RECEIPT_LONG, on_click=abrir_dialogo_vendas_recentes),
            theme.botao_secundario("Relatórios", icone=ft.icons.BAR_CHART,
                                    on_click=lambda e: _parar_polling_e_chamar(ao_abrir_relatorios)()),
            theme.botao_secundario("Gerencial", icone=ft.icons.INSIGHTS,
                                    on_click=lambda e: _parar_polling_e_chamar(ao_abrir_relatorio_gerencial)()),
            theme.botao_secundario("Configurações", icone=ft.icons.SETTINGS,
                                    on_click=lambda e: _parar_polling_e_chamar(ao_abrir_configuracao)()),
            theme.botao_secundario("Trocar operador", icone=ft.icons.LOGOUT,
                                    on_click=lambda e: _parar_polling_e_chamar(ao_deslogar)()),
        ],
        spacing=6,
        visible=True,
    )

    barra_topo = ft.Container(
        content=ft.Row(
            [
                ft.Row(
                    [
                        ft.Image(src="logo_adk.png", height=26, fit=ft.ImageFit.CONTAIN),
                        ft.Column([texto_nome_evento, texto_caixa_operador], spacing=0),
                    ],
                    spacing=8, expand=True,
                ),
                ft.Row(
                    [
                        ft.IconButton(ft.icons.REFRESH, icon_color=theme.TEXTO_SUAVE, tooltip="Atualizar produtos/evento",
                                      on_click=recarregar_dados),
                        botoes_completos,
                        menu_acoes,
                        theme.botao_secundario("Fechar caixa", icone=ft.icons.POINT_OF_SALE,
                                                on_click=lambda e: _parar_polling_e_chamar(ao_fechar_caixa)()),
                    ],
                    # Rede de seguranca (bug real, 2026-09): "Fechar caixa"
                    # ficava fora da largura visivel em notebook (DPI/
                    # resolucao especifica) e so um resize de verdade
                    # corrigia. Nenhum item aqui usa expand=True, entao
                    # wrap=True e seguro (ver memoria do projeto sobre
                    # Row(wrap=True)+expand quebrar a tela) - se ainda assim
                    # nao couber tudo numa linha, quebra pra 2a linha em vez
                    # de cortar o botao fora da tela sem aviso nenhum.
                    spacing=6, wrap=True,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        ),
        padding=ft.padding.symmetric(8, 16),
        bgcolor=theme.SURFACE,
        border=ft.border.only(bottom=ft.BorderSide(1, theme.BORDA)),
    )

    painel_carrinho = ft.Container(
        content=ft.Column(
            [
                texto_qtd_pedidos,
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

    area_produtos = ft.Stack(
        [
            ft.Container(
                content=ft.Image(src="logo_adk.png", width=360, fit=ft.ImageFit.CONTAIN, opacity=0.05),
                alignment=ft.alignment.center, expand=True,
            ),
            ft.Container(
                content=ft.Column([banner_novidade, chips_categorias, grade_produtos], spacing=14, expand=True),
                padding=18, expand=True,
            ),
        ],
        expand=True,
    )

    corpo = ft.Container(expand=True)

    def _montar_corpo(largo):
        painel_carrinho.width = 340 if largo else None
        if largo:
            return ft.Row([area_produtos, painel_carrinho], expand=True, spacing=0)
        return ft.Column([area_produtos, painel_carrinho], expand=True, spacing=0, scroll=ft.ScrollMode.AUTO)

    # Em tela larga (PC) produtos e carrinho ficam lado a lado, com o
    # carrinho numa largura fixa (340px) - nunca ocupando 1/3 da tela num
    # monitor grande. Em tela estreita (celular) cada um ocupa a largura
    # toda e empilha.
    def _ajustar_layout(e=None):
        largo = (page.width or 1000) >= LARGURA_QUEBRA
        botoes_completos.visible = largo
        menu_acoes.visible = not largo
        corpo.content = _montar_corpo(largo)
        page.update()

    page.on_resized = _ajustar_layout
    _ajustar_layout()
    # Bug real reportado pelo usuario (2026-09): em notebook, "Fechar caixa"
    # ficava sumido (fora da largura visivel) at minimizar/restaurar a
    # janela - so ai o layout recalculava certo. Causa: `page.width` ainda
    # nao esta populado no instante exato em que a tela monta (fica
    # None/0), cai no fallback "or 1000" e assume erroneamente o layout
    # LARGO (todos os botoes + Fechar caixa juntos, sem caber) - so um
    # resize de verdade corrige. Reforca com um recheck curto depois que a
    # janela ja terminou de desenhar (mesmo truque de atraso ja usado no
    # bug do dialogo do combo, ver memoria do projeto).
    threading.Timer(0.3, _ajustar_layout).start()

    atualizar_grade()
    atualizar_carrinho_ui()

    return ft.Column([barra_topo, corpo], spacing=0, expand=True)


def _fmt(valor) -> str:
    return f"R$ {valor:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")
