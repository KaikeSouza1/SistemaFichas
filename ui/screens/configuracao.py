import threading
import traceback

import flet as ft

from config import settings
from db import modo_celular, repository
from db.connection import ConexaoIndisponivel
from printing import escpos_printer
from ui import componentes, theme


def _logar_erro(contexto: str, ex: Exception) -> None:
    """Registra em arquivo (nao no console - o .exe empacotado nao tem
    console, o erro simplesmente desaparecia sem isso) qualquer excecao que
    aconteca dentro de um clique, pra dar pra diagnosticar sem precisar
    reproduzir "no escuro"."""
    try:
        caminho = settings.PASTA_DADOS_LOCAIS / "ui_errors.log"
        settings.PASTA_DADOS_LOCAIS.mkdir(parents=True, exist_ok=True)
        with open(caminho, "a", encoding="utf-8") as f:
            f.write(f"\n--- {contexto} ---\n")
            f.write(traceback.format_exc())
    except Exception:
        pass


CORES_PRESET = [
    ("Laranja", "#E2662D"), ("Verde", "#4F9D63"), ("Amarelo", "#D9A82E"),
    ("Vermelho", "#D1483B"), ("Azul", "#3E7CB1"), ("Roxo", "#8B5FBF"),
    ("Marrom", "#8A5A3C"), ("Cinza", "#6B6259"),
]

NOVA_CATEGORIA = "__nova__"


def tela(page: ft.Page, ao_salvar_conexao, ao_voltar=None, administrador=False) -> ft.Control:
    lista_abas = [
        ft.Tab(text="Conexão e impressora", content=_tab_conexao(page, ao_salvar_conexao, ao_voltar)),
        ft.Tab(text="Produtos", content=_tab_produtos(page)),
        ft.Tab(text="Vender pelo celular", content=_tab_celular(page)),
    ]
    # Evento e Operadores tocam em coisas sensiveis (nome/rodape do evento pra
    # todo mundo, PIN e permissao de outros operadores) - so administrador ve.
    if administrador:
        lista_abas.insert(1, ft.Tab(text="Evento", content=_tab_evento(page)))
        lista_abas.append(ft.Tab(text="Operadores", content=_tab_operadores(page)))

    tabs = ft.Tabs(
        selected_index=0,
        expand=True,
        label_color=theme.TEXTO,
        unselected_label_color=theme.TEXTO_SUAVE,
        indicator_color=theme.BRASA,
        tabs=lista_abas,
    )

    cabecalho = [ft.Icon(ft.icons.SETTINGS, color=theme.BRASA, size=24), theme.titulo("Configurações", tamanho=22)]
    if ao_voltar:
        cabecalho = [ft.IconButton(ft.icons.ARROW_BACK, icon_color=theme.TEXTO, on_click=lambda e: ao_voltar())] + cabecalho

    return ft.Container(
        content=ft.Column([ft.Row(cabecalho, spacing=10), tabs], spacing=16, expand=True),
        padding=24, bgcolor=theme.BG, expand=True,
    )


# ---------- Conexão ----------

def _tab_conexao(page, ao_salvar_conexao, ao_voltar=None):
    cfg = settings.load()

    campo_caixa = theme.campo_texto("Nome deste caixa/terminal (ex: Caixa 01)", value=cfg["caixa_nome"], width=320)

    try:
        impressoras = escpos_printer.listar_impressoras_windows()
    except Exception:
        impressoras = []
    dropdown_impressora = ft.Dropdown(
        label="Impressora",
        value=cfg["impressora_windows"] if cfg["impressora_windows"] in impressoras else None,
        options=[ft.dropdown.Option(nome) for nome in impressoras],
        width=320,
        border_color=theme.BORDA, focused_border_color=theme.BRASA, bgcolor=theme.SURFACE_ALTA,
    )

    def salvar(e):
        novo_cfg = {
            **cfg,
            "impressora_windows": dropdown_impressora.value or "",
            "caixa_nome": campo_caixa.value.strip(),
        }
        settings.save(novo_cfg)
        componentes.aviso(page, "Configuração salva.")
        # Se veio de dentro do app (ja logado, ja com caixa aberto), so volta pra
        # la - nao faz sentido reiniciar o fluxo inteiro (que sempre termina no
        # login) so por ter trocado a impressora. O reinicio completo so e usado
        # no primeiro acesso, antes de logar (quando ao_voltar nao existe).
        if ao_voltar:
            ao_voltar()
        else:
            ao_salvar_conexao()

    _ROTULO_PAPEL = {
        "servidor": "Principal do evento (banco local ligado neste PC)",
        "cliente": "Conectado no PC principal de um evento",
    }

    def trocar_papel_rede(e):
        def confirmar():
            novo_cfg = {**settings.load(), "papel_rede": None}
            settings.save(novo_cfg)
            ao_salvar_conexao()

        componentes.dialogo_confirmacao(
            page, "Trocar modo de rede",
            "Isso volta pra tela de escolha: este PC vai ser o principal do evento, ou vai conectar em outro? Continuar?",
            ao_confirmar=confirmar, texto_confirmar="Trocar",
        )

    return ft.Container(
        content=ft.Column(
            [
                theme.cartao(
                    ft.Row(
                        [
                            ft.Column([
                                ft.Text("Modo de rede deste PC", color=theme.TEXTO, weight=ft.FontWeight.W_700, size=13),
                                ft.Text(_ROTULO_PAPEL.get(cfg.get("papel_rede"), "Ainda não escolhido"),
                                        color=theme.TEXTO_SUAVE, size=12),
                            ], spacing=2, expand=True),
                            theme.botao_secundario("Trocar", icone=ft.icons.SWAP_HORIZ, on_click=trocar_papel_rede),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                ),
                theme.subtitulo("Nome deste caixa e impressora usada nele."),
                campo_caixa,
                dropdown_impressora,
                theme.botao_primario("Salvar", icone=ft.icons.SAVE, on_click=salvar),
            ],
            spacing=16, scroll=ft.ScrollMode.AUTO,
        ),
        padding=20,
    )


# ---------- Evento ----------

def _tab_evento(page):
    try:
        evento_aberto = repository.obter_evento_aberto()
        historico = repository.listar_eventos()
    except ConexaoIndisponivel:
        return _aviso_sem_conexao()

    corpo = ft.Column(spacing=16)

    def recarregar():
        corpo.controls = _construir_conteudo()
        corpo.update()

    def _construir_conteudo():
        nonlocal evento_aberto, historico
        evento_aberto = repository.obter_evento_aberto()
        historico = repository.listar_eventos()

        controles = []
        if evento_aberto:
            campo_nome = theme.campo_texto("Nome do evento", value=evento_aberto["nome"], width=420)
            campo_rodape = theme.campo_texto("Rodapé das fichas", value=evento_aberto["rodape"], width=420, multiline=True, min_lines=2)

            def salvar(e):
                try:
                    repository.atualizar_evento(evento_aberto["id"], campo_nome.value.strip(), campo_rodape.value.strip())
                except ConexaoIndisponivel:
                    componentes.dialogo_erro_conexao(page)
                    return
                componentes.aviso(page, "Evento atualizado.")
                recarregar()

            def fechar(e):
                def efetivar():
                    try:
                        repository.fechar_evento(evento_aberto["id"])
                    except ValueError as ex:
                        # listar sessoes abertas e oferecer opcao de forcar fechamento
                        try:
                            sessoes = repository.listar_sessoes_abertas_por_evento(evento_aberto["id"]) or []
                        except Exception:
                            sessoes = []
                        detalhes = "\n".join([f"{s['caixa_nome']} (aberto por: {s.get('operador_abertura') or 'desconhecido'})" for s in sessoes]) or "Nenhuma informacao disponível."

                        def forcar():
                            try:
                                repository.fechar_evento_forcado(evento_aberto["id"])
                            except ConexaoIndisponivel:
                                componentes.dialogo_erro_conexao(page)
                                return
                            componentes.aviso(page, "Evento fechado (forçado).")
                            recarregar()

                        componentes.dialogo_confirmacao(
                            page,
                            "Existem caixas abertos",
                            f"Não é possível fechar: existem caixas abertos:\n{detalhes}\n\nDeseja forçar o fechamento (isso marcará as sessões como fechadas)?",
                            ao_confirmar=forcar,
                            texto_confirmar="Forçar fechamento",
                        )
                        return
                    except ConexaoIndisponivel:
                        componentes.dialogo_erro_conexao(page)
                        return
                    componentes.aviso(page, "Evento fechado.")
                    recarregar()

                componentes.dialogo_confirmacao(
                    page, "Fechar evento",
                    "Isso encerra o evento atual. Todos os caixas precisam estar fechados antes. Confirma?",
                    ao_confirmar=efetivar, texto_confirmar="Fechar evento",
                )

            controles.append(theme.cartao(
                ft.Column(
                    [
                        ft.Row([ft.Icon(ft.icons.CELEBRATION, color=theme.SUCESSO), ft.Text("Evento em andamento", color=theme.TEXTO, weight=ft.FontWeight.W_700)]),
                        campo_nome, campo_rodape,
                        ft.Row([
                            theme.botao_primario("Salvar", icone=ft.icons.SAVE, on_click=salvar),
                            theme.botao_perigo("Fechar evento", icone=ft.icons.STOP_CIRCLE, on_click=fechar),
                        ], spacing=10),
                    ],
                    spacing=14,
                ),
            ))
        else:
            campo_nome_novo = theme.campo_texto("Nome do novo evento", width=420)
            campo_rodape_novo = theme.campo_texto("Rodapé das fichas", width=420)

            def abrir(e):
                if not campo_nome_novo.value.strip():
                    return
                try:
                    repository.criar_evento(campo_nome_novo.value.strip(), campo_rodape_novo.value.strip())
                except ConexaoIndisponivel:
                    componentes.dialogo_erro_conexao(page)
                    return
                componentes.aviso(page, "Evento aberto.")
                recarregar()

            controles.append(theme.cartao(
                ft.Column(
                    [theme.subtitulo("Nenhum evento aberto agora."), campo_nome_novo, campo_rodape_novo,
                     theme.botao_primario("Abrir evento", icone=ft.icons.PLAY_ARROW, on_click=abrir)],
                    spacing=14,
                ),
            ))

        linhas_historico = [
            ft.Row(
                [
                    ft.Text(ev["nome"], color=theme.TEXTO, expand=True),
                    ft.Text("Aberto" if ev["status"] == "ABERTA" else "Fechado",
                             color=theme.SUCESSO if ev["status"] == "ABERTA" else theme.TEXTO_FRACO, size=12, width=70),
                    ft.Text(ev["data_abertura"].strftime("%d/%m/%Y %H:%M"), color=theme.TEXTO_SUAVE, size=12, width=130),
                ],
            )
            for ev in historico
        ] or [ft.Text("Sem eventos no histórico.", color=theme.TEXTO_FRACO)]

        controles.append(theme.cartao(
            ft.Column([ft.Text("Histórico de eventos", color=theme.TEXTO, weight=ft.FontWeight.W_700), ft.Divider(color=theme.BORDA), *linhas_historico], spacing=8),
        ))
        return controles

    corpo.controls = _construir_conteudo()

    return ft.Container(content=ft.Column([corpo], scroll=ft.ScrollMode.AUTO), padding=20)


# ---------- Produtos ----------

def _tab_produtos(page):
    try:
        categorias = repository.listar_categorias()
        produtos = repository.listar_produtos(somente_ativos=False)
    except ConexaoIndisponivel:
        return _aviso_sem_conexao()

    lista = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO, expand=True)

    def recarregar():
        nonlocal produtos
        produtos = repository.listar_produtos(somente_ativos=False)
        lista.controls = [_linha_produto(p) for p in produtos]
        lista.update()

    def excluir_produto(p):
        def confirmar():
            try:
                repository.excluir_produto(p["id"])
            except ValueError as ex:
                componentes.aviso(page, str(ex), cor=theme.ALERTA)
                return
            except ConexaoIndisponivel:
                componentes.dialogo_erro_conexao(page)
                return
            recarregar()
            componentes.aviso(page, "Produto excluído.")

        componentes.dialogo_confirmacao(
            page, "Excluir produto",
            f"Tem certeza que deseja excluir \"{p['nome']}\"? Essa ação não pode ser desfeita.",
            ao_confirmar=confirmar, texto_confirmar="Excluir",
        )

    def _linha_produto(p):
        situacao = "Ativo" if p["ativo"] and not p["oculto"] else ("Oculto" if p["oculto"] else "Inativo")
        cor_situacao = theme.SUCESSO if situacao == "Ativo" else theme.ALERTA
        return ft.Container(
            content=ft.Row(
                [
                    ft.Container(width=14, height=14, bgcolor=p["cor_hex"], border_radius=4),
                    ft.Text(p["nome"] + (" (COMBO)" if p["eh_combo"] else ""), color=theme.TEXTO, weight=ft.FontWeight.W_600, expand=True),
                    ft.Text(p["categoria_nome"] or "-", color=theme.TEXTO_SUAVE, width=120),
                    ft.Text(f"R$ {p['preco']:.2f}".replace(".", ","), color=theme.TEXTO, width=90),
                    ft.Text(situacao, color=cor_situacao, size=12, width=70),
                    ft.IconButton(ft.icons.EDIT, icon_color=theme.TEXTO_SUAVE, icon_size=18,
                                  on_click=lambda e, prod=p: abrir_formulario(prod)),
                    ft.IconButton(ft.icons.DELETE_OUTLINE, icon_color=theme.ERRO, icon_size=18, tooltip="Excluir produto",
                                  on_click=lambda e, prod=p: excluir_produto(prod)),
                ],
                alignment=ft.MainAxisAlignment.START,
            ),
            bgcolor=theme.SURFACE_ALTA, border_radius=theme.RADIUS, padding=ft.padding.symmetric(8, 14),
        )

    def abrir_formulario(produto=None):
        categorias_atuais = repository.listar_categorias()
        campo_nome = theme.campo_texto("Nome", value=produto["nome"] if produto else "", width=460)
        campo_preco = theme.campo_texto("Preço de venda (R$)", value=f"{produto['preco']:.2f}".replace(".", ",") if produto else "0,00", width=220)
        campo_custo = theme.campo_texto("Custo (R$, opcional)", value=f"{produto['custo']:.2f}".replace(".", ",") if produto else "0,00", width=220)
        campo_nova_categoria = theme.campo_texto("Nome da nova categoria", width=460, visible=False)

        opcoes_categoria = [ft.dropdown.Option(str(c["id"]), c["nome"]) for c in categorias_atuais]
        opcoes_categoria.append(ft.dropdown.Option(NOVA_CATEGORIA, "+ Nova categoria..."))
        dropdown_categoria = ft.Dropdown(
            label="Categoria", width=220, options=opcoes_categoria,
            value=str(produto["categoria_id"]) if produto and produto["categoria_id"] else None,
            border_color=theme.BORDA, focused_border_color=theme.BRASA, bgcolor=theme.SURFACE_ALTA,
        )

        def categoria_mudou(e):
            campo_nova_categoria.visible = dropdown_categoria.value == NOVA_CATEGORIA
            campo_nova_categoria.update()
        dropdown_categoria.on_change = categoria_mudou

        dropdown_cor = ft.Dropdown(
            label="Cor do botão", width=220,
            value=(produto["cor_hex"] if produto else CORES_PRESET[0][1]),
            options=[ft.dropdown.Option(hexv, nome) for nome, hexv in CORES_PRESET],
            border_color=theme.BORDA, focused_border_color=theme.BRASA, bgcolor=theme.SURFACE_ALTA,
        )

        switch_ocultar_valor = ft.Switch(
            label="Não mostrar valor na ficha impressa",
            value=bool(produto and produto["ocultar_valor_impressao"]),
        )
        # Pedido real do usuario apos o 1o evento: produto que fica no
        # proprio caixa (ex: doces) nao precisa de ficha nenhuma pra
        # retirar em outro balcao.
        switch_emitir_ficha = ft.Switch(
            label="Emitir ficha ao vender",
            value=bool(produto["emitir_ficha"]) if produto else True,
        )

        switch_estoque = ft.Switch(label="Controlar estoque", value=bool(produto and produto["estoque_controlado"]))
        campo_estoque = theme.campo_texto(
            "Estoque atual", value=str(produto["estoque_atual"]) if produto and produto["estoque_atual"] is not None else "0",
            width=140, visible=switch_estoque.value,
        )
        switch_combo = ft.Switch(label="É um combo (kit de produtos)?", value=bool(produto and produto["eh_combo"]))

        def _criar_produto_basico():
            """Usado quando o usuario marca "combo" num produto NOVO e quer
            escolher os itens antes mesmo de apertar "Salvar" - cria o
            produto com o que ja foi preenchido no formulario, so pra ter
            um id pra associar os itens do combo."""
            if not campo_nome.value.strip():
                componentes.aviso(page, "Informe o nome do produto antes.", cor=theme.ERRO)
                return None
            categoria_id = None
            if dropdown_categoria.value == NOVA_CATEGORIA:
                if campo_nova_categoria.value.strip():
                    categoria_id = repository.criar_categoria(campo_nova_categoria.value.strip())
            elif dropdown_categoria.value:
                categoria_id = int(dropdown_categoria.value)
            try:
                preco = float(campo_preco.value.replace(".", "").replace(",", "."))
                custo = float(campo_custo.value.replace(".", "").replace(",", ".")) if campo_custo.value else 0
            except ValueError:
                componentes.aviso(page, "Preço/custo inválido.", cor=theme.ERRO)
                return None
            return repository.criar_produto(
                campo_nome.value.strip(), preco, categoria_id, custo, dropdown_cor.value, False, None, True,
            )

        def abrir_editor_combo(e):
            nonlocal produto
            try:
                if produto is None:
                    novo_id = _criar_produto_basico()
                    if novo_id is None:
                        return
                    produto = {"id": novo_id, "nome": campo_nome.value.strip()}
                    recarregar()
                # Fechar um AlertDialog e abrir outro imediatamente em
                # seguida (dois page.update() bem proximos) faz o Flet nao
                # trocar de dialogo - ja tentamos e nao resolveu de verdade
                # no app real (so no teste automatizado, que nao renderiza
                # nada de fato). Um pequeno atraso antes de abrir o segundo
                # e o jeito que resolve isso de verdade - ver memoria do
                # projeto sobre esse bug do Flet.
                componentes.fechar_dialogo(page, dlg)
                threading.Timer(0.3, lambda: _abrir_editor_combo_com_erro(produto)).start()
            except Exception as ex:
                _logar_erro("abrir_editor_combo", ex)
                componentes.aviso(page, f"Erro ao abrir itens do combo: {ex}", cor=theme.ERRO)

        def _abrir_editor_combo_com_erro(produto_combo):
            try:
                abrir_dialogo_combo(produto_combo)
            except Exception as ex:
                _logar_erro("abrir_dialogo_combo (via timer)", ex)
                componentes.aviso(page, f"Erro ao abrir itens do combo: {ex}", cor=theme.ERRO)

        botao_editar_combo = theme.botao_secundario(
            "Editar itens do combo", icone=ft.icons.LIST_ALT, largura=280, on_click=abrir_editor_combo,
        )
        botao_editar_combo.visible = switch_combo.value
        switch_ativo = ft.Switch(label="Ativo", value=produto["ativo"] if produto else True)
        switch_oculto = ft.Switch(label="Ocultar da tela de venda", value=bool(produto and produto["oculto"]))

        def estoque_mudou(e):
            campo_estoque.visible = switch_estoque.value
            campo_estoque.update()
        switch_estoque.on_change = estoque_mudou

        def combo_mudou(e):
            # combo e estoque controlado sao mutuamente exclusivos: o "estoque"
            # de um combo e derivado do estoque dos produtos que o compoem.
            if switch_combo.value:
                switch_estoque.value = False
                switch_estoque.disabled = True
                campo_estoque.visible = False
            else:
                switch_estoque.disabled = False
            switch_estoque.update()
            campo_estoque.update()
            botao_editar_combo.visible = switch_combo.value
            botao_editar_combo.update()
        switch_combo.on_change = combo_mudou

        def salvar_produto(e):
            categoria_id = None
            if dropdown_categoria.value == NOVA_CATEGORIA:
                if campo_nova_categoria.value.strip():
                    categoria_id = repository.criar_categoria(campo_nova_categoria.value.strip())
            elif dropdown_categoria.value:
                categoria_id = int(dropdown_categoria.value)

            try:
                preco = float(campo_preco.value.replace(".", "").replace(",", "."))
                custo = float(campo_custo.value.replace(".", "").replace(",", ".")) if campo_custo.value else 0
            except ValueError:
                componentes.aviso(page, "Preço/custo inválido.", cor=theme.ERRO)
                return

            estoque_atual = None
            if switch_estoque.value:
                try:
                    estoque_atual = int(campo_estoque.value)
                except (ValueError, TypeError):
                    estoque_atual = 0

            if produto:
                repository.atualizar_produto(
                    produto["id"], campo_nome.value.strip(), preco, categoria_id, custo, dropdown_cor.value,
                    switch_estoque.value, estoque_atual, switch_combo.value, switch_ativo.value, switch_oculto.value,
                    switch_ocultar_valor.value, switch_emitir_ficha.value,
                )
                componentes.fechar_dialogo(page, dlg)
                recarregar()
                componentes.aviso(page, "Produto salvo.")
            else:
                novo_id = repository.criar_produto(
                    campo_nome.value.strip(), preco, categoria_id, custo, dropdown_cor.value,
                    switch_estoque.value, estoque_atual, switch_combo.value,
                    ocultar_valor_impressao=switch_ocultar_valor.value, emitir_ficha=switch_emitir_ficha.value,
                )
                recarregar()
                componentes.fechar_dialogo(page, dlg)
                if switch_combo.value:
                    novo_produto = {"id": novo_id, "nome": campo_nome.value.strip()}
                    threading.Timer(0.3, lambda: _abrir_editor_combo_com_erro(novo_produto)).start()
                componentes.aviso(page, "Produto salvo.")

        dlg = ft.AlertDialog(
            modal=True, bgcolor=theme.SURFACE,
            title=ft.Text("Editar produto" if produto else "Novo produto", color=theme.TEXTO),
            content=ft.Column(
                [campo_nome, ft.Row([campo_preco, campo_custo]), ft.Row([dropdown_categoria, dropdown_cor]),
                 campo_nova_categoria, switch_ocultar_valor, switch_emitir_ficha,
                 ft.Row([switch_estoque, campo_estoque]), switch_combo,
                 botao_editar_combo, ft.Row([switch_ativo, switch_oculto])],
                tight=True, spacing=14, scroll=ft.ScrollMode.AUTO, width=500, height=560,
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda e: componentes.fechar_dialogo(page, dlg)),
                theme.botao_primario("Salvar", on_click=salvar_produto),
            ],
        )
        page.dialog = dlg
        dlg.open = True
        page.update()

    def abrir_dialogo_combo(produto_combo):
        """produto_combo: dict com pelo menos {"id", "nome"} - deixa escolher
        quais produtos (e quantidade de cada) esse combo imprime quando vendido."""
        try:
            componentes_atuais = repository.listar_itens_combo(produto_combo["id"])
        except ConexaoIndisponivel:
            componentes.dialogo_erro_conexao(page)
            return
        opcoes_produto = [
            ft.dropdown.Option(str(p["id"]), p["nome"])
            for p in produtos if p["id"] != produto_combo["id"] and not p["eh_combo"]
        ]

        linhas_coluna = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO, height=220)
        linhas = []

        def redesenhar():
            linhas_coluna.controls = [l["row"] for l in linhas]
            # As linhas iniciais (itens ja salvos do combo) sao montadas ANTES
            # do dialogo existir na pagina - chamar .update() nesse momento
            # quebra com "Column Control must be added to the page first".
            # So atualiza se a coluna ja estiver mesmo na pagina (cliques de
            # +Adicionar/remover depois que o dialogo abriu).
            if linhas_coluna.page:
                linhas_coluna.update()

        def nova_linha(produto_componente_id=None, quantidade=1):
            dropdown = ft.Dropdown(
                label="Produto", width=200, options=opcoes_produto,
                value=str(produto_componente_id) if produto_componente_id else None,
                border_color=theme.BORDA, focused_border_color=theme.BRASA, bgcolor=theme.SURFACE_ALTA,
            )
            campo_qtd = theme.campo_texto("Qtd", value=str(quantidade), width=70)
            linha = {"dropdown": dropdown, "campo_qtd": campo_qtd}

            def remover(e):
                linhas.remove(linha)
                redesenhar()

            linha["row"] = ft.Row(
                [dropdown, campo_qtd, ft.IconButton(ft.icons.DELETE_OUTLINE, icon_color=theme.ERRO, on_click=remover)],
                spacing=8,
            )
            linhas.append(linha)
            redesenhar()

        for item in componentes_atuais:
            nova_linha(item["produto_componente_id"], item["quantidade"])
        if not componentes_atuais:
            nova_linha()

        def salvar(e):
            itens = []
            for linha in linhas:
                if not linha["dropdown"].value:
                    continue
                try:
                    qtd = max(1, int(linha["campo_qtd"].value))
                except (ValueError, TypeError):
                    qtd = 1
                itens.append({"produto_componente_id": int(linha["dropdown"].value), "quantidade": qtd})
            if not itens:
                componentes.aviso(page, "Adicione ao menos um produto no combo.", cor=theme.ALERTA)
                return
            try:
                repository.definir_itens_combo(produto_combo["id"], itens)
            except ConexaoIndisponivel:
                componentes.dialogo_erro_conexao(page)
                return
            componentes.fechar_dialogo(page, dlg_combo)
            recarregar()
            componentes.aviso(page, "Itens do combo salvos.")

        dlg_combo = ft.AlertDialog(
            modal=True, bgcolor=theme.SURFACE,
            title=ft.Text(f"Itens do combo: {produto_combo['nome']}", color=theme.TEXTO),
            content=ft.Column(
                [theme.subtitulo("Ao vender o combo, imprime uma ficha de cada produto abaixo, na quantidade escolhida."),
                 linhas_coluna,
                 theme.botao_secundario("+ Adicionar produto", icone=ft.icons.ADD, on_click=lambda e: nova_linha())],
                tight=True, spacing=12, scroll=ft.ScrollMode.AUTO, height=380, width=380,
            ),
            actions=[
                ft.TextButton("Fechar sem salvar", on_click=lambda e: componentes.fechar_dialogo(page, dlg_combo)),
                theme.botao_primario("Salvar itens", on_click=salvar),
            ],
        )
        page.dialog = dlg_combo
        dlg_combo.open = True
        page.update()

    lista.controls = [_linha_produto(p) for p in produtos]

    def abrir_organizar_layout(e):
        _dialogo_organizar_layout(page, categorias, recarregar)

    return ft.Container(
        content=ft.Column(
            [
                ft.Row([theme.subtitulo("Produtos/fichas vendidos na tela de venda."),
                        ft.Row([
                            theme.botao_secundario("Organizar layout", icone=ft.icons.GRID_VIEW, on_click=abrir_organizar_layout),
                            theme.botao_primario("Novo produto", icone=ft.icons.ADD, on_click=lambda e: abrir_formulario()),
                        ], spacing=8)],
                       alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                lista,
            ],
            spacing=14, expand=True,
        ),
        padding=20, expand=True,
    )


def _dialogo_organizar_layout(page, categorias, recarregar_lista):
    """Deixa arrastar os produtos pra escolher a ordem deles na grade de
    venda de verdade (mesmas cores/tamanho de tile). Chip "Todos" (igual a
    tela de venda) mostra tudo junto pra organizar de uma vez; os chips de
    categoria continuam disponiveis pra ajustar um grupo por vez. A ordem
    persistida e sempre global (ver repository.listar_produtos), entao
    arrastar entre categorias enquanto em "Todos" reflete na venda real."""

    categoria_atual = {"id": None}  # None = "Todos"

    def _produtos_filtrados():
        todos = repository.listar_produtos(somente_ativos=False, incluir_ocultos=True)
        if categoria_atual["id"] is None:
            return todos
        return [p for p in todos if p["categoria_id"] == categoria_atual["id"]]

    grade = ft.GridView(expand=True, max_extent=150, child_aspect_ratio=1.15, spacing=10, run_spacing=10, padding=4)

    def _tile(produto, produtos_atuais):
        legenda = produto["categoria_nome"] or ""
        if produto["eh_combo"]:
            legenda = (legenda + " · combo") if legenda else "combo"
        visual = ft.Container(
            content=ft.Column(
                [ft.Text(produto["nome"], color="#FFFFFF", weight=ft.FontWeight.W_700, size=13,
                          max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                 ft.Text(f"R$ {produto['preco']:.2f}".replace(".", ","), color="#FFFFFF", size=12, opacity=0.9),
                 ft.Text(legenda, color="#FFFFFF", size=10, opacity=0.7)],
                spacing=4,
            ),
            bgcolor=produto["cor_hex"] or theme.BRASA, border_radius=theme.RADIUS, padding=10,
            alignment=ft.alignment.bottom_left, width=140, height=120,
        )

        def on_will_accept(e):
            e.control.content.content.border = ft.border.all(2, theme.BRASA)
            e.control.content.content.update()

        def on_leave(e):
            e.control.content.content.border = None
            e.control.content.content.update()

        def on_accept(e: ft.DragTargetEvent):
            e.control.content.content.border = None
            origem = page.get_control(e.src_id)
            id_origem = origem.data
            id_destino = produto["id"]
            if id_origem == id_destino:
                e.control.content.content.update()
                return
            ids = [p["id"] for p in produtos_atuais]
            i_origem, i_destino = ids.index(id_origem), ids.index(id_destino)
            ids[i_origem], ids[i_destino] = ids[i_destino], ids[i_origem]
            repository.definir_ordem_produtos(ids)
            carregar()

        return ft.DragTarget(
            group="produto_layout",
            content=ft.Draggable(
                group="produto_layout",
                data=produto["id"],
                content=visual,
                content_feedback=ft.Container(
                    width=90, height=90, bgcolor=produto["cor_hex"] or theme.BRASA, border_radius=theme.RADIUS,
                ),
            ),
            on_will_accept=on_will_accept,
            on_leave=on_leave,
            on_accept=on_accept,
        )

    def carregar(atualizar=True):
        produtos_atuais = _produtos_filtrados()
        grade.controls = [_tile(p, produtos_atuais) for p in produtos_atuais]
        if atualizar:
            grade.update()

    def escolher_categoria(categoria_id):
        def handler(e):
            categoria_atual["id"] = categoria_id
            for chip in chips.controls:
                chip.bgcolor = theme.BRASA if chip.data == categoria_id else theme.SURFACE_ALTA
            chips.update()
            carregar()
        return handler

    def _chip(categoria_id, nome):
        return ft.Container(
            content=ft.Text(nome, color=theme.TEXTO, size=13, weight=ft.FontWeight.W_600),
            data=categoria_id,
            bgcolor=theme.BRASA if categoria_id == categoria_atual["id"] else theme.SURFACE_ALTA,
            border_radius=20, padding=ft.padding.symmetric(6, 14), ink=True,
            on_click=escolher_categoria(categoria_id),
        )

    chips = ft.Row(
        [_chip(None, "Todos")] + [_chip(c["id"], c["nome"]) for c in categorias],
        spacing=8, scroll=ft.ScrollMode.AUTO,
    )
    carregar(atualizar=False)

    def fechar(e):
        componentes.fechar_dialogo(page, dlg)
        recarregar_lista()

    dlg = ft.AlertDialog(
        modal=True, bgcolor=theme.SURFACE,
        title=ft.Text("Organizar layout dos produtos", color=theme.TEXTO),
        content=ft.Column(
            [theme.subtitulo("Arraste um produto por cima de outro pra trocar a posição - é a mesma ordem que vai aparecer na venda."),
             chips, ft.Divider(color=theme.BORDA), grade],
            tight=True, spacing=12, width=900, height=680,
        ),
        actions=[theme.botao_primario("Fechar", on_click=fechar)],
    )
    page.dialog = dlg
    dlg.open = True
    page.update()


# ---------- Vender pelo celular ----------

def _tab_celular(page):
    cfg = settings.load()
    if cfg.get("papel_rede") != "servidor":
        return ft.Container(
            content=ft.Column(
                [
                    ft.Icon(ft.icons.PHONE_ANDROID, color=theme.TEXTO_FRACO, size=48),
                    theme.subtitulo(
                        "Esse recurso só funciona no PC principal do evento (o que guarda o banco de dados)."
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=14,
            ),
            alignment=ft.alignment.center, padding=40,
        )

    url = modo_celular.url_acesso(cfg["postgres"]["host"])
    qr_base64 = modo_celular.qrcode_base64(url)

    return ft.Container(
        content=ft.Column(
            [
                theme.titulo("Vender pelo celular", tamanho=18),
                theme.subtitulo(
                    "Escaneie esse código com a câmera do celular pra vender direto de lá, "
                    "na mesma rede Wi-Fi deste evento.",
                    tamanho=13,
                ),
                ft.Container(
                    content=ft.Image(src_base64=qr_base64, width=220, height=220),
                    bgcolor="#FFFFFF", padding=16, border_radius=theme.RADIUS,
                ),
            ],
            spacing=16, horizontal_alignment=ft.CrossAxisAlignment.CENTER, scroll=ft.ScrollMode.AUTO,
        ),
        alignment=ft.alignment.center, padding=30, expand=True,
    )


# ---------- Operadores ----------

def _tab_operadores(page):
    try:
        operadores = repository.listar_operadores(somente_ativos=False)
    except ConexaoIndisponivel:
        return _aviso_sem_conexao()

    lista = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO, expand=True)

    def recarregar():
        atualizados = repository.listar_operadores(somente_ativos=False)
        lista.controls = [_linha_operador(o) for o in atualizados]
        lista.update()

    def _linha_operador(o):
        def alternar(e):
            repository.definir_ativo_operador(o["id"], not o["ativo"])
            recarregar()

        def excluir(e):
            def efetivar():
                try:
                    repository.excluir_operador(o["id"])
                except ValueError as ex:
                    componentes.aviso(page, str(ex), cor=theme.ALERTA)
                    return
                except ConexaoIndisponivel:
                    componentes.dialogo_erro_conexao(page)
                    return
                recarregar()
                componentes.aviso(page, "Operador excluído.")

            componentes.dialogo_confirmacao(
                page, "Excluir operador",
                f"Excluir \"{o['nome']}\" para sempre? Só funciona se ele nunca vendeu nada "
                f"(senão o histórico quebraria) - nesse caso, é melhor só desativar.",
                ao_confirmar=efetivar, texto_confirmar="Excluir",
            )

        return ft.Container(
            content=ft.Row(
                [
                    ft.Text(o["nome"] + (" (admin)" if o["administrador"] else ""),
                            color=theme.TEXTO, weight=ft.FontWeight.W_600, expand=True),
                    ft.Text("Ativo" if o["ativo"] else "Inativo", color=theme.SUCESSO if o["ativo"] else theme.TEXTO_FRACO, size=12),
                    ft.Switch(value=o["ativo"], on_change=alternar),
                    ft.IconButton(ft.icons.EDIT, icon_color=theme.TEXTO_SUAVE, icon_size=18,
                                  tooltip="Editar", on_click=lambda e: abrir_formulario(o)),
                    ft.IconButton(ft.icons.DELETE_OUTLINE, icon_color=theme.ERRO, icon_size=18,
                                  tooltip="Excluir", on_click=excluir),
                ],
            ),
            bgcolor=theme.SURFACE_ALTA, border_radius=theme.RADIUS, padding=ft.padding.symmetric(8, 14),
        )

    def abrir_formulario(operador=None):
        """`operador=None` cria um novo; passar a linha edita ela (pedido do
        usuario: dava pra criar e ativar/desativar, mas nao editar nome/PIN/
        admin nem excluir de verdade)."""
        campo_nome = theme.campo_texto("Nome", width=280, value=operador["nome"] if operador else "")
        campo_pin = theme.campo_texto("PIN numérico", width=280, value=operador["pin"] if operador else "")
        # Se ainda nao existe nenhum operador, esse vai ser o primeiro -
        # marca administrador por padrao, senao ninguem consegue entrar em
        # Operadores/Evento depois (precisa de um admin pra criar o proximo).
        switch_administrador = ft.Switch(
            label="Administrador",
            value=operador["administrador"] if operador else not operadores,
        )

        def salvar(e):
            if not campo_nome.value.strip() or not campo_pin.value.strip():
                return
            if operador:
                repository.atualizar_operador(
                    operador["id"], campo_nome.value.strip(), campo_pin.value.strip(), switch_administrador.value,
                )
            else:
                repository.criar_operador(campo_nome.value.strip(), campo_pin.value.strip(), switch_administrador.value)
            componentes.fechar_dialogo(page, dlg)
            recarregar()

        dlg = ft.AlertDialog(
            modal=True, bgcolor=theme.SURFACE,
            title=ft.Text("Editar operador" if operador else "Novo operador", color=theme.TEXTO),
            content=ft.Column([campo_nome, campo_pin, switch_administrador], tight=True, spacing=12),
            actions=[ft.TextButton("Cancelar", on_click=lambda e: componentes.fechar_dialogo(page, dlg)),
                     theme.botao_primario("Salvar", on_click=salvar)],
        )
        page.dialog = dlg
        dlg.open = True
        page.update()

    def abrir_formulario_novo(e):
        abrir_formulario(None)

    lista.controls = [_linha_operador(o) for o in operadores]

    return ft.Container(
        content=ft.Column(
            [
                ft.Row([theme.subtitulo("Quem pode operar os caixas."),
                        theme.botao_primario("Novo operador", icone=ft.icons.PERSON_ADD, on_click=abrir_formulario_novo)],
                       alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                lista,
            ],
            spacing=14, expand=True,
        ),
        padding=20, expand=True,
    )


def _aviso_sem_conexao():
    return ft.Container(
        content=ft.Column(
            [ft.Icon(ft.icons.WIFI_OFF, color=theme.ERRO, size=32),
             ft.Text("Configure a conexão com o servidor primeiro.", color=theme.TEXTO_SUAVE)],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10,
        ),
        alignment=ft.alignment.center, padding=40,
    )
