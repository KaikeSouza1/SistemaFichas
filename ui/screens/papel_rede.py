"""Primeira tela do dia: este PC vai ser o "computador principal" do evento
(sobe o banco local e os outros caixas conectam nele) ou vai se conectar
num PC principal que outro caixa já ligou?"""

import flet as ft

from config import settings
from db import postgres_local
from ui import componentes, theme


def tela(page: ft.Page, ao_escolher) -> ft.Control:
    texto_status = ft.Text("", color=theme.TEXTO_SUAVE, size=13)

    def escolher_servidor(e):
        if not postgres_local.disponivel():
            componentes.aviso(page, "Banco local embutido não encontrado nesta instalação.", cor=theme.ALERTA)
            return
        texto_status.value = "Preparando o banco local, aguarde..."
        texto_status.update()
        try:
            dados_conexao = postgres_local.iniciar()
            postgres_local.criar_banco_se_preciso()
        except Exception as ex:
            componentes.aviso(page, f"Não consegui iniciar o banco local: {ex}", cor=theme.ERRO)
            texto_status.value = ""
            texto_status.update()
            return

        cfg = settings.load()
        cfg["postgres"] = dados_conexao
        cfg["papel_rede"] = "servidor"
        settings.save(cfg)

        texto_status.value = "Liberando porta no Firewall..."
        texto_status.update()
        firewall_ok = postgres_local.liberar_firewall(dados_conexao["port"])
        texto_status.value = ""
        texto_status.update()
        if firewall_ok:
            componentes.aviso(page, f"Este PC é o principal do evento. IP para os outros caixas: {dados_conexao['host']}")
        else:
            componentes.aviso(
                page,
                f"Este PC é o principal. IP: {dados_conexao['host']}. Não consegui liberar a porta "
                f"{dados_conexao['port']} no Firewall do Windows automaticamente (precisa de administrador) - "
                f"se os outros caixas não conseguirem conectar, feche o programa e abra de novo clicando com "
                f"botão direito no atalho e escolhendo \"Executar como administrador\".",
                cor=theme.ALERTA,
            )
        ao_escolher()

    def escolher_cliente(e):
        campo_ip = theme.campo_texto("IP do computador principal", width=280, autofocus=True)

        def confirmar(e2):
            ip = campo_ip.value.strip()
            if not ip:
                return
            cfg = settings.load()
            cfg["postgres"] = {
                "host": ip,
                "port": postgres_local.PORTA_PADRAO,
                "dbname": postgres_local.NOME_BANCO,
                "user": postgres_local.USUARIO_PADRAO,
                "password": postgres_local.SENHA_PADRAO,
                "sslmode": "disable",
            }
            cfg["papel_rede"] = "cliente"
            settings.save(cfg)
            componentes.fechar_dialogo(page, dlg)
            ao_escolher()

        dlg = ft.AlertDialog(
            modal=True, bgcolor=theme.SURFACE,
            title=ft.Text("Conectar no computador principal", color=theme.TEXTO),
            content=ft.Column([
                ft.Text("Digite o IP mostrado na tela do computador principal deste evento.",
                        color=theme.TEXTO_SUAVE, size=13),
                campo_ip,
            ], tight=True, spacing=10),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda e2: componentes.fechar_dialogo(page, dlg)),
                theme.botao_primario("Conectar", on_click=confirmar),
            ],
        )
        page.dialog = dlg
        dlg.open = True
        page.update()

    return ft.Container(
        content=ft.Column(
            [
                ft.Icon(ft.icons.WIFI_TETHERING, color=theme.BRASA, size=48),
                theme.titulo("Este PC é o principal do evento?", tamanho=22),
                theme.subtitulo(
                    "Só um PC por evento deve ser o principal — ele guarda os dados e os\n"
                    "outros caixas se conectam nele pela rede local, sem precisar de internet.",
                    tamanho=13,
                ),
                ft.Container(height=10),
                ft.Row(
                    [
                        theme.cartao(
                            ft.Column([
                                ft.Icon(ft.icons.DNS, color=theme.BRASA_CLARA, size=32),
                                ft.Text("Sim, sou o principal", color=theme.TEXTO, weight=ft.FontWeight.W_700),
                                ft.Text("Este PC vai guardar os dados do evento e os outros caixas conectam nele.",
                                        color=theme.TEXTO_SUAVE, size=12),
                                ft.Container(height=8),
                                theme.botao_primario("Iniciar como principal", icone=ft.icons.PLAY_ARROW, on_click=escolher_servidor),
                            ], spacing=8, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                            expand=1,
                        ),
                        theme.cartao(
                            ft.Column([
                                ft.Icon(ft.icons.LAN, color=theme.BRASA_CLARA, size=32),
                                ft.Text("Não, vou conectar em outro", color=theme.TEXTO, weight=ft.FontWeight.W_700),
                                ft.Text("Outro caixa já é o principal deste evento — vou digitar o IP dele.",
                                        color=theme.TEXTO_SUAVE, size=12),
                                ft.Container(height=8),
                                theme.botao_secundario("Conectar em outro PC", icone=ft.icons.LINK, on_click=escolher_cliente),
                            ], spacing=8, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                            expand=1,
                        ),
                    ],
                    spacing=16,
                ),
                texto_status,
            ],
            spacing=14, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        alignment=ft.alignment.center, expand=True, bgcolor=theme.BG, padding=40,
    )
