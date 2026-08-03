import flet as ft

from config import settings
from db import repository
from db.connection import ConexaoIndisponivel
from ui import theme
from ui.state import EstadoApp
from ui.screens import abertura_caixa, configuracao, evento, fechamento, login, relatorios, venda


def main(page: ft.Page):
    theme.aplicar(page)
    estado = EstadoApp()

    def mostrar(builder):
        # Monta o novo conteudo ANTES de limpar a tela atual: se o builder
        # falhar com uma excecao nao tratada, a tela anterior nao vira uma
        # tela em branco/travada - mostramos um erro e o usuario pode voltar.
        try:
            novo_conteudo = builder()
        except Exception as ex:
            novo_conteudo = _erro_generico(str(ex), tentar_de_novo=verificar_inicio)
        page.controls.clear()
        page.add(novo_conteudo)
        page.update()

    def verificar_inicio():
        cfg = settings.load()
        if not settings.is_configured(cfg):
            ir_para_configuracao()
            return
        try:
            # Garantir que o schema exista no banco remoto (aplica se faltar)
            try:
                repository.garantir_schema()
            except Exception:
                # se falhar aqui, deixamos o fluxo normal capturar a excecao
                pass
            estado.caixa_id = repository.obter_ou_criar_caixa(cfg["caixa_nome"])
            estado.caixa_nome = cfg["caixa_nome"]
            evento_aberto = repository.obter_evento_aberto()
        except ConexaoIndisponivel:
            mostrar(lambda: _erro_inicial(page, verificar_inicio, ir_para_configuracao))
            return
        if not evento_aberto:
            mostrar(lambda: evento.tela_abrir(page, ao_abrir=verificar_inicio, ao_tentar_de_novo=verificar_inicio))
            return
        estado.evento_id = evento_aberto["id"]
        ir_para_login()

    def ir_para_configuracao():
        mostrar(lambda: configuracao.tela(page, ao_salvar_conexao=verificar_inicio, ao_voltar=None))

    def ir_para_login():
        mostrar(lambda: login.tela(
            page, estado,
            ao_autenticar=ir_para_abertura_ou_venda,
            ao_tentar_de_novo=ir_para_login,
            ao_abrir_configuracao=lambda: mostrar(
                lambda: configuracao.tela(page, ao_salvar_conexao=verificar_inicio, ao_voltar=ir_para_login)
            ),
        ))

    def ir_para_abertura_ou_venda():
        try:
            sessao = repository.obter_sessao_aberta(estado.caixa_id)
        except ConexaoIndisponivel:
            mostrar(lambda: _erro_inicial(page, ir_para_abertura_ou_venda, ir_para_configuracao))
            return
        if sessao:
            estado.sessao_id = sessao["id"]
            ir_para_venda()
        else:
            ir_para_abertura()

    def ir_para_abertura():
        mostrar(lambda: abertura_caixa.tela(page, estado, ao_abrir=ir_para_venda, ao_tentar_de_novo=ir_para_abertura))

    def ir_para_venda():
        mostrar(lambda: venda.tela(
            page, estado,
            ao_fechar_caixa=ir_para_fechamento,
            ao_deslogar=ir_para_login_reset,
            ao_abrir_configuracao=lambda: mostrar(
                lambda: configuracao.tela(page, ao_salvar_conexao=verificar_inicio, ao_voltar=ir_para_venda)
            ),
            ao_abrir_relatorios=lambda: mostrar(lambda: relatorios.tela(page, ao_voltar=ir_para_venda)),
            ao_tentar_de_novo=ir_para_venda,
        ))

    def ir_para_fechamento():
        mostrar(lambda: fechamento.tela(
            page, estado, ao_concluir=ir_para_login_reset, ao_tentar_de_novo=ir_para_fechamento,
            ao_voltar=ir_para_venda,
        ))

    def ir_para_login_reset():
        estado.deslogar()
        ir_para_login()

    verificar_inicio()


def _erro_generico(mensagem, tentar_de_novo):
    return ft.Container(
        content=ft.Column(
            [
                ft.Icon(ft.icons.ERROR_OUTLINE, color=theme.ERRO, size=64),
                ft.Text("Deu um problema nessa tela", size=20, weight=ft.FontWeight.W_700, color=theme.TEXTO),
                ft.Text(mensagem, size=13, color=theme.TEXTO_SUAVE, text_align=ft.TextAlign.CENTER, selectable=True),
                ft.Container(height=12),
                theme.botao_primario("Voltar ao início", icone=ft.icons.HOME, on_click=lambda e: tentar_de_novo()),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10,
        ),
        alignment=ft.alignment.center, expand=True, bgcolor=theme.BG, padding=30,
    )


def _erro_inicial(page, tentar_de_novo, ir_para_configuracao):
    return ft.Container(
        content=ft.Column(
            [
                ft.Icon(ft.icons.WIFI_OFF, color=theme.ERRO, size=64),
                ft.Text("Sem conexão com o servidor", size=20, weight=ft.FontWeight.W_700, color=theme.TEXTO),
                ft.Text("Confira o cabo de rede e o PC servidor, ou revise a configuração.",
                         size=14, color=theme.TEXTO_SUAVE, text_align=ft.TextAlign.CENTER),
                ft.Container(height=12),
                ft.Row(
                    [
                        theme.botao_secundario("Configurações", icone=ft.icons.SETTINGS, on_click=lambda e: ir_para_configuracao()),
                        theme.botao_primario("Tentar novamente", icone=ft.icons.REFRESH, on_click=lambda e: tentar_de_novo()),
                    ],
                    spacing=10,
                ),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10,
        ),
        alignment=ft.alignment.center, expand=True, bgcolor=theme.BG,
    )
