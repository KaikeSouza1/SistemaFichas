import threading

import flet as ft

from config.versao import VERSAO_APP
from db import atualizacao, repository
from db.connection import ConexaoIndisponivel
from ui import componentes, theme


def tela(page: ft.Page, estado, ao_autenticar, ao_tentar_de_novo, ao_abrir_configuracao) -> ft.Control:
    try:
        operadores = repository.listar_operadores_disponiveis_para_login()
    except ConexaoIndisponivel:
        return componentes.tela_estado_erro(
            "Não deu para carregar a lista de operadores.", ao_tentar_de_novo
        )

    selecionado = {"id": None, "nome": None}
    campo_pin = ft.TextField(
        value="", password=True, can_reveal_password=True, text_align=ft.TextAlign.CENTER,
        keyboard_type=ft.KeyboardType.NUMBER, autofocus=True, height=56, width=220, text_size=26,
        border_color=theme.BORDA, focused_border_color=theme.BRASA, bgcolor=theme.SURFACE_ALTA,
    )
    area_pin = ft.Container(visible=False)
    texto_erro = ft.Text("", color=theme.ERRO, size=13)

    def escolher_operador(op):
        def handler(e):
            selecionado["id"] = op["id"]
            selecionado["nome"] = op["nome"]
            campo_pin.value = ""
            texto_erro.value = ""
            titulo_pin.value = f"PIN de {op['nome']}"
            area_pin.visible = True
            # Esconde a grade de operadores enquanto digita o PIN - mostrar os
            # dois juntos empilhados era o que fazia o teclado numerico
            # "descer" pra fora da tela em notebook/tela mais baixa.
            area_operadores.visible = False
            page.update()
        return handler

    def confirmar_pin(e):
        try:
            resultado = repository.autenticar_operador(selecionado["id"], campo_pin.value)
        except ConexaoIndisponivel:
            componentes.dialogo_erro_conexao(page, tentar_de_novo=lambda: ao_tentar_de_novo())
            return
        if not resultado:
            texto_erro.value = "PIN incorreto."
            campo_pin.value = ""
            page.update()
            return
        estado.operador_id = resultado["id"]
        estado.operador_nome = resultado["nome"]
        estado.operador_administrador = bool(resultado["administrador"])
        ao_autenticar()

    campo_pin.on_submit = confirmar_pin

    titulo_pin = ft.Text("", size=16, weight=ft.FontWeight.W_600, color=theme.TEXTO)
    area_pin.content = theme.cartao(
        ft.Column(
            [
                titulo_pin,
                campo_pin,
                componentes.teclado_numerico(campo_pin, page),
                texto_erro,
                ft.Row(
                    [
                        theme.botao_secundario("Cancelar", on_click=lambda e: cancelar_selecao(e)),
                        theme.botao_primario("Entrar", on_click=confirmar_pin, icone=ft.icons.LOGIN),
                    ],
                    spacing=10,
                ),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=14,
        ),
        padding=28,
    )

    def cancelar_selecao(e):
        selecionado["id"] = None
        area_pin.visible = False
        area_operadores.visible = True
        page.update()

    area_operadores = ft.Column(
        [
            theme.titulo("Quem está operando?", tamanho=22),
            ft.Container(height=8),
            ft.Row(
                [
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Icon(ft.icons.PERSON, color=theme.BRASA_CLARA, size=30),
                                ft.Text(op["nome"], color=theme.TEXTO, weight=ft.FontWeight.W_600, size=15),
                            ],
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=6,
                        ),
                        width=140,
                        height=110,
                        bgcolor=theme.SURFACE,
                        border=ft.border.all(1, theme.BORDA),
                        border_radius=theme.RADIUS,
                        alignment=ft.alignment.center,
                        ink=True,
                        on_click=escolher_operador(op),
                    )
                    for op in operadores
                ],
                wrap=True,
                spacing=14,
                run_spacing=14,
                alignment=ft.MainAxisAlignment.CENTER,
            ),
        ],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=0,
    )

    # Verificacao de atualizacao fica so aqui (tela de login), nunca na tela de
    # venda: aqui e o unico momento em que o app esta parado (ninguem no meio
    # de uma venda), entao e seguro deixar o operador decidir baixar e reiniciar.
    banner_atualizacao = ft.Container(visible=False)
    texto_atualizacao = ft.Text("", color=theme.TEXTO, size=13)

    def _iniciar_atualizacao(e=None):
        btn_atualizar_versao.disabled = True
        btn_atualizar_versao.text = "Baixando..."
        try:
            banner_atualizacao.update()
        except Exception:
            pass

        def _baixar_e_instalar():
            try:
                atualizacao.instalar_e_sair()
            except Exception as ex:
                btn_atualizar_versao.disabled = False
                btn_atualizar_versao.text = "Baixar atualização"
                try:
                    banner_atualizacao.update()
                    componentes.aviso(page, f"Não foi possível atualizar agora: {ex}", cor=theme.ERRO)
                except Exception:
                    pass

        threading.Thread(target=_baixar_e_instalar, daemon=True).start()

    btn_atualizar_versao = theme.botao_secundario(
        "Baixar atualização", icone=ft.icons.SYSTEM_UPDATE, on_click=_iniciar_atualizacao,
    )
    banner_atualizacao.content = ft.Row(
        [
            ft.Row([ft.Icon(ft.icons.SYSTEM_UPDATE, color=theme.SUCESSO, size=18), texto_atualizacao], spacing=8),
            btn_atualizar_versao,
        ],
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
    )
    banner_atualizacao.bgcolor = theme.SURFACE_ALTA
    banner_atualizacao.padding = ft.padding.symmetric(8, 16)
    banner_atualizacao.border_radius = theme.RADIUS
    banner_atualizacao.border = ft.border.all(1, theme.SUCESSO)

    def _verificar_atualizacao_uma_vez():
        atualizacao.sincronizar_central_config()
        versao_nova = atualizacao.verificar_nova_versao()
        if versao_nova:
            texto_atualizacao.value = f"Nova versão disponível ({versao_nova})."
            banner_atualizacao.visible = True
            try:
                banner_atualizacao.update()
            except Exception:
                pass  # tela ja foi trocada antes da checagem terminar

    threading.Thread(target=_verificar_atualizacao_uma_vez, daemon=True).start()

    return ft.Container(
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Text(f"Caixa: {estado.caixa_nome} · v{VERSAO_APP}", color=theme.TEXTO_SUAVE, size=13),
                        ft.TextButton(
                            "Configurações", icon=ft.icons.SETTINGS,
                            on_click=lambda e: ao_abrir_configuracao(),
                            style=ft.ButtonStyle(color=theme.TEXTO_SUAVE),
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                banner_atualizacao,
                ft.Image(src="logo_adk.png", width=120, fit=ft.ImageFit.CONTAIN),
                area_operadores,
                area_pin,
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=16,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        ),
        padding=20,
        bgcolor=theme.BG,
        expand=True,
    )
