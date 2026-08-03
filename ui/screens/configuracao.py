import flet as ft

from config import settings
from db import repository
from db.connection import ConexaoIndisponivel
from printing import escpos_printer
from ui import componentes, theme

CORES_PRESET = [
    ("Laranja", "#E2662D"), ("Verde", "#4F9D63"), ("Amarelo", "#D9A82E"),
    ("Vermelho", "#D1483B"), ("Azul", "#3E7CB1"), ("Roxo", "#8B5FBF"),
    ("Marrom", "#8A5A3C"), ("Cinza", "#6B6259"),
]

NOVA_CATEGORIA = "__nova__"


def tela(page: ft.Page, ao_salvar_conexao, ao_voltar=None) -> ft.Control:
    tabs = ft.Tabs(
        selected_index=0,
        expand=True,
        label_color=theme.TEXTO,
        unselected_label_color=theme.TEXTO_SUAVE,
        indicator_color=theme.BRASA,
        tabs=[
            ft.Tab(text="Conexão e impressora", content=_tab_conexao(page, ao_salvar_conexao)),
            ft.Tab(text="Evento", content=_tab_evento(page)),
            ft.Tab(text="Produtos", content=_tab_produtos(page)),
            ft.Tab(text="Operadores", content=_tab_operadores(page)),
        ],
    )

    cabecalho = [ft.Icon(ft.icons.SETTINGS, color=theme.BRASA, size=24), theme.titulo("Configurações", tamanho=22)]
    if ao_voltar:
        cabecalho = [ft.IconButton(ft.icons.ARROW_BACK, icon_color=theme.TEXTO, on_click=lambda e: ao_voltar())] + cabecalho

    return ft.Container(
        content=ft.Column([ft.Row(cabecalho, spacing=10), tabs], spacing=16, expand=True),
        padding=24, bgcolor=theme.BG, expand=True,
    )


# ---------- Conexão ----------

def _tab_conexao(page, ao_salvar_conexao):
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

    def _linha_produto(p):
        situacao = "Ativo" if p["ativo"] and not p["oculto"] else ("Oculto" if p["oculto"] else "Inativo")
        cor_situacao = theme.SUCESSO if situacao == "Ativo" else theme.ALERTA
        return ft.Container(
            content=ft.Row(
                [
                    ft.Container(width=14, height=14, bgcolor=p["cor_hex"], border_radius=4),
                    ft.Text(p["nome"], color=theme.TEXTO, weight=ft.FontWeight.W_600, expand=True),
                    ft.Text(p["categoria_nome"] or "-", color=theme.TEXTO_SUAVE, width=120),
                    ft.Text(f"R$ {p['preco']:.2f}".replace(".", ","), color=theme.TEXTO, width=90),
                    ft.Text(situacao, color=cor_situacao, size=12, width=70),
                    ft.IconButton(ft.icons.EDIT, icon_color=theme.TEXTO_SUAVE, icon_size=18,
                                  on_click=lambda e, prod=p: abrir_formulario(prod)),
                ],
                alignment=ft.MainAxisAlignment.START,
            ),
            bgcolor=theme.SURFACE_ALTA, border_radius=theme.RADIUS, padding=ft.padding.symmetric(8, 14),
        )

    def abrir_formulario(produto=None):
        categorias_atuais = repository.listar_categorias()
        campo_nome = theme.campo_texto("Nome", value=produto["nome"] if produto else "", width=280)
        campo_preco = theme.campo_texto("Preço de venda (R$)", value=f"{produto['preco']:.2f}".replace(".", ",") if produto else "0,00", width=160)
        campo_custo = theme.campo_texto("Custo (R$, opcional)", value=f"{produto['custo']:.2f}".replace(".", ",") if produto else "0,00", width=160)
        campo_nova_categoria = theme.campo_texto("Nome da nova categoria", width=280, visible=False)

        opcoes_categoria = [ft.dropdown.Option(str(c["id"]), c["nome"]) for c in categorias_atuais]
        opcoes_categoria.append(ft.dropdown.Option(NOVA_CATEGORIA, "+ Nova categoria..."))
        dropdown_categoria = ft.Dropdown(
            label="Categoria", width=280, options=opcoes_categoria,
            value=str(produto["categoria_id"]) if produto and produto["categoria_id"] else None,
            border_color=theme.BORDA, focused_border_color=theme.BRASA, bgcolor=theme.SURFACE_ALTA,
        )

        def categoria_mudou(e):
            campo_nova_categoria.visible = dropdown_categoria.value == NOVA_CATEGORIA
            campo_nova_categoria.update()
        dropdown_categoria.on_change = categoria_mudou

        dropdown_cor = ft.Dropdown(
            label="Cor do botão", width=280,
            value=(produto["cor_hex"] if produto else CORES_PRESET[0][1]),
            options=[ft.dropdown.Option(hexv, nome) for nome, hexv in CORES_PRESET],
            border_color=theme.BORDA, focused_border_color=theme.BRASA, bgcolor=theme.SURFACE_ALTA,
        )

        switch_estoque = ft.Switch(label="Controlar estoque", value=bool(produto and produto["estoque_controlado"]))
        campo_estoque = theme.campo_texto("Estoque atual", value=str(produto["estoque_atual"]) if produto and produto["estoque_atual"] is not None else "0", width=140)
        switch_ativo = ft.Switch(label="Ativo", value=produto["ativo"] if produto else True)
        switch_oculto = ft.Switch(label="Ocultar da tela de venda", value=bool(produto and produto["oculto"]))

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

            estoque_atual = int(campo_estoque.value) if switch_estoque.value and campo_estoque.value else None

            if produto:
                repository.atualizar_produto(
                    produto["id"], campo_nome.value.strip(), preco, categoria_id, custo, dropdown_cor.value,
                    switch_estoque.value, estoque_atual, False, switch_ativo.value, switch_oculto.value,
                )
            else:
                repository.criar_produto(
                    campo_nome.value.strip(), preco, categoria_id, custo, dropdown_cor.value,
                    switch_estoque.value, estoque_atual, False,
                )
            componentes.fechar_dialogo(page, dlg)
            recarregar()
            componentes.aviso(page, "Produto salvo.")

        dlg = ft.AlertDialog(
            modal=True, bgcolor=theme.SURFACE,
            title=ft.Text("Editar produto" if produto else "Novo produto", color=theme.TEXTO),
            content=ft.Column(
                [campo_nome, ft.Row([campo_preco, campo_custo]), dropdown_categoria, campo_nova_categoria,
                 dropdown_cor, ft.Row([switch_estoque, campo_estoque]), ft.Row([switch_ativo, switch_oculto])],
                tight=True, spacing=12, scroll=ft.ScrollMode.AUTO, height=420,
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda e: componentes.fechar_dialogo(page, dlg)),
                theme.botao_primario("Salvar", on_click=salvar_produto),
            ],
        )
        page.dialog = dlg
        dlg.open = True
        page.update()

    lista.controls = [_linha_produto(p) for p in produtos]

    return ft.Container(
        content=ft.Column(
            [
                ft.Row([theme.subtitulo("Produtos/fichas vendidos na tela de venda."),
                        theme.botao_primario("Novo produto", icone=ft.icons.ADD, on_click=lambda e: abrir_formulario())],
                       alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                lista,
            ],
            spacing=14, expand=True,
        ),
        padding=20, expand=True,
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

        return ft.Container(
            content=ft.Row(
                [
                    ft.Text(o["nome"], color=theme.TEXTO, weight=ft.FontWeight.W_600, expand=True),
                    ft.Text("Ativo" if o["ativo"] else "Inativo", color=theme.SUCESSO if o["ativo"] else theme.TEXTO_FRACO, size=12),
                    ft.Switch(value=o["ativo"], on_change=alternar),
                ],
            ),
            bgcolor=theme.SURFACE_ALTA, border_radius=theme.RADIUS, padding=ft.padding.symmetric(8, 14),
        )

    def abrir_formulario_novo(e):
        campo_nome = theme.campo_texto("Nome", width=280)
        campo_pin = theme.campo_texto("PIN numérico", width=280)

        def salvar(e):
            if not campo_nome.value.strip() or not campo_pin.value.strip():
                return
            repository.criar_operador(campo_nome.value.strip(), campo_pin.value.strip())
            componentes.fechar_dialogo(page, dlg)
            recarregar()

        dlg = ft.AlertDialog(
            modal=True, bgcolor=theme.SURFACE,
            title=ft.Text("Novo operador", color=theme.TEXTO),
            content=ft.Column([campo_nome, campo_pin], tight=True, spacing=12),
            actions=[ft.TextButton("Cancelar", on_click=lambda e: componentes.fechar_dialogo(page, dlg)),
                     theme.botao_primario("Salvar", on_click=salvar)],
        )
        page.dialog = dlg
        dlg.open = True
        page.update()

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
