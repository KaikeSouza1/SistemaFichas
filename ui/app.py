import traceback

import flet as ft

from config import settings
from db import descoberta, postgres_local, repository, sync
from db.connection import ConexaoIndisponivel
from ui import theme
from ui.state import EstadoApp
from ui.screens import abertura_caixa, churrasco, configuracao, evento, fechamento, login, papel_rede, relatorios, venda


def _logar_erro(contexto: str) -> None:
    """Mesma ideia do log de erro de ui/screens/configuracao.py: o .exe
    empacotado nao tem console, um erro sem isso simplesmente desaparece sem
    deixar rastro - e foi exatamente assim que o bug do "Editar itens do
    combo" ficou escondido por varias tentativas erradas antes."""
    try:
        caminho = settings.PASTA_DADOS_LOCAIS / "ui_errors.log"
        settings.PASTA_DADOS_LOCAIS.mkdir(parents=True, exist_ok=True)
        with open(caminho, "a", encoding="utf-8") as f:
            f.write(f"\n--- {contexto} ---\n")
            f.write(traceback.format_exc())
    except Exception:
        pass


def main(page: ft.Page):
    theme.aplicar(page)
    estado = EstadoApp()
    _sync_iniciado = [False]

    def mostrar(builder):
        # Monta o novo conteudo ANTES de limpar a tela atual: se o builder
        # falhar com uma excecao nao tratada, a tela anterior nao vira uma
        # tela em branco/travada - mostramos um erro e o usuario pode voltar.
        # O try/except cobre TUDO (montar E exibir) - um clique que nao dava
        # em nada (visto num evento real, PC sem conexao) e exatamente esse
        # tipo de falha: se so o builder() fosse protegido e o page.update()
        # depois falhasse, a tela antiga ficava travada sem nenhum aviso.
        try:
            novo_conteudo = builder()
            page.controls.clear()
            page.add(novo_conteudo)
            page.update()
        except Exception as ex:
            _logar_erro("mostrar()")
            try:
                page.controls.clear()
                page.add(_erro_generico(str(ex), tentar_de_novo=verificar_inicio))
                page.update()
            except Exception:
                _logar_erro("mostrar() - fallback tambem falhou")

    def verificar_inicio():
        cfg = settings.load()
        if not cfg.get("papel_rede"):
            mostrar(lambda: papel_rede.tela(page, ao_escolher=verificar_inicio))
            return
        if cfg.get("papel_rede") == "servidor" and postgres_local.disponivel():
            # O banco local só fica de pé enquanto o processo dele estiver rodando -
            # se o PC reiniciar (ou o app for so fechado e reaberto), precisa subir
            # de novo aqui, nao so na primeira vez que o usuario escolheu "sou o
            # principal" (ver ui/screens/papel_rede.py), senao o app fica preso
            # em "Sem conexao com o servidor" pra sempre.
            try:
                dados_conexao = postgres_local.iniciar()
                postgres_local.criar_banco_se_preciso()
                cfg["postgres"] = dados_conexao
                settings.save(cfg)
                postgres_local.liberar_firewall(dados_conexao["port"])
            except Exception:
                pass  # se nao conseguir, o erro de conexao normal abaixo cobre isso
        try:
            # Garantir que o schema exista ANTES de qualquer outra coisa que
            # dependa do banco - inclusive antes do proprio "settings.is_configured"
            # abaixo. Achado num evento real (2026-08-07): se o nome do caixa
            # ainda nao tinha sido definido, o fluxo antigo pulava direto pra tela
            # de Configuracoes SEM nunca ter chamado garantir_schema() - o banco
            # existia (Postgres local ja rodando) mas vazio, sem nenhuma tabela, e
            # a aba "Produtos" de Configuracoes quebrava com "relation ... does not
            # exist" na hora de listar categorias. Rodar isso aqui, incondicional,
            # garante que o banco NUNCA fica "pela metade" - a primeira coisa que
            # qualquer tela faz com o banco encontra o schema completo.
            repository.garantir_schema()
            repository.garantir_tabela_sync_controle()
            repository.garantir_contador_por_evento()
            repository.garantir_coluna_ocultar_valor_produto()
            repository.garantir_pagamentos_venda()
            repository.garantir_coluna_administrador_operador()
            repository.garantir_admin_padrao()
            repository.garantir_coluna_evento_operador()
            repository.garantir_schema_churrasco()
            repository.garantir_coluna_pagamento_churrasco()
            repository.garantir_tabela_faixas_numeracao_churrasco()
            repository.garantir_colunas_pago_entregue_churrasco()
            repository.garantir_blocos_numeracao_churrasco()
            if not _sync_iniciado[0]:
                sync.iniciar_em_background()
                _sync_iniciado[0] = True
            if cfg.get("papel_rede") == "servidor":
                descoberta.iniciar_responder_em_background(descoberta.informacoes_deste_servidor)
        except ConexaoIndisponivel:
            mostrar(lambda: _erro_inicial(page, verificar_inicio, ir_para_configuracao))
            return
        except Exception:
            # Falha "estranha" (nao ConexaoIndisponivel) aplicando schema - nao
            # trava o app aqui; deixa o fluxo normal abaixo tentar e, se de fato
            # nao der pra usar o banco, o erro aparece de um jeito visivel lá.
            pass

        if not settings.is_configured(cfg):
            ir_para_configuracao()
            return
        nome_caixa = cfg["caixa_nome"]
        if page.web:
            # Celular acessando pela rede (ver db/modo_celular.py) nao tem
            # config.json - cada um e um caixa separado, o nome fica guardado
            # so no navegador daquele celular (client_storage), nao no PC.
            nome_caixa = page.client_storage.get("caixa_nome") if page.client_storage else None
            if not nome_caixa:
                mostrar(lambda: _tela_nome_caixa_web(page, ao_definir=verificar_inicio))
                return
        try:
            estado.caixa_id = repository.obter_ou_criar_caixa(nome_caixa)
            estado.caixa_nome = nome_caixa
            evento_aberto = repository.obter_evento_aberto()
        except ConexaoIndisponivel:
            mostrar(lambda: _erro_inicial(page, verificar_inicio, ir_para_configuracao))
            return
        if not evento_aberto:
            ir_para_evento_abrir()
            return
        estado.evento_id = evento_aberto["id"]
        ir_para_login()

    def ir_para_evento_abrir():
        # "Ver relatórios de eventos anteriores" nesse gate e o unico jeito
        # de sair daqui sem abrir um evento novo - antes disso, fechar um
        # evento sempre devolvia pra essa tela sem nenhuma outra opcao alem
        # de criar mais um evento, mesmo so pra consultar o historico. Como
        # relatorios.tela() nao depende de operador logado nem de evento
        # aberto, o atalho funciona direto daqui, antes do login.
        mostrar(lambda: evento.tela_abrir(
            page, ao_abrir=verificar_inicio, ao_tentar_de_novo=verificar_inicio,
            ao_ver_relatorios=ir_para_relatorios_sem_evento,
            ao_abrir_configuracao=ir_para_configuracao,
        ))

    def ir_para_relatorios_sem_evento():
        mostrar(lambda: relatorios.tela(page, ao_voltar=ir_para_evento_abrir))

    def ir_para_configuracao():
        # Bootstrap/recuperacao (antes de logar, ou quando a conexao falhou) -
        # nao ha operador logado pra saber se e administrador, e nesse ponto
        # normalmente nem existe operador cadastrado ainda - libera tudo.
        mostrar(lambda: configuracao.tela(page, ao_salvar_conexao=verificar_inicio, ao_voltar=None, administrador=True))

    def ir_para_login():
        mostrar(lambda: login.tela(
            page, estado,
            ao_autenticar=ir_para_abertura_ou_venda,
            ao_tentar_de_novo=ir_para_login,
            # Atalho de "Configuracoes" direto na tela de login, sem operador
            # logado ainda - restrito (so as abas nao administrativas). Pra
            # gerenciar Evento/Operadores e preciso logar como admin e abrir
            # Configuracoes de dentro da tela de venda.
            ao_abrir_configuracao=lambda: mostrar(
                lambda: configuracao.tela(page, ao_salvar_conexao=verificar_inicio, ao_voltar=ir_para_login, administrador=False)
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
        mostrar(lambda: abertura_caixa.tela(
            page, estado, ao_abrir=ir_para_venda, ao_tentar_de_novo=ir_para_abertura,
            ao_abrir_configuracao=lambda: mostrar(
                lambda: configuracao.tela(
                    page, ao_salvar_conexao=verificar_inicio, ao_voltar=ir_para_abertura,
                    administrador=estado.operador_administrador,
                )
            ),
        ))

    def ir_para_venda():
        # Reconfirma que ainda existe um evento aberto antes de montar a tela
        # de venda - normalmente nunca muda no meio de uma sessao, MAS se
        # outro caixa fechar o evento (ou o evento for apagado/zerado por
        # manutencao) enquanto este PC ainda esta na tela de venda, voltar
        # pra ca (de Configuracoes/Relatorios/Churrasco/Fechamento) chamava
        # venda.tela() direto, que assume evento sempre existe e quebra com
        # TypeError ao tentar usar evento["id"]. Mesma checagem que
        # verificar_inicio() ja faz no login, só que tambem aqui.
        try:
            evento_aberto = repository.obter_evento_aberto()
        except ConexaoIndisponivel:
            mostrar(lambda: _erro_inicial(page, ir_para_venda, ir_para_configuracao))
            return
        if not evento_aberto:
            ir_para_evento_abrir()
            return
        mostrar(lambda: venda.tela(
            page, estado,
            ao_fechar_caixa=ir_para_fechamento,
            ao_deslogar=ir_para_login_reset,
            ao_abrir_configuracao=lambda: mostrar(
                lambda: configuracao.tela(
                    page, ao_salvar_conexao=verificar_inicio, ao_voltar=ir_para_venda,
                    administrador=estado.operador_administrador,
                )
            ),
            ao_abrir_relatorios=lambda: mostrar(lambda: relatorios.tela(page, ao_voltar=ir_para_venda)),
            ao_abrir_churrasco=lambda: mostrar(lambda: churrasco.tela(page, estado, ao_voltar=ir_para_venda)),
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


def _tela_nome_caixa_web(page, ao_definir):
    """So aparece pra sessao aberta via navegador (celular) - pergunta uma
    unica vez o nome desse caixa e guarda no proprio navegador, pra nao
    perguntar de novo nas proximas vezes que abrir nesse mesmo celular."""
    campo_nome = theme.campo_texto("Nome deste caixa (ex: Vendedor 1)", width=280, autofocus=True)

    def confirmar(e):
        nome = (campo_nome.value or "").strip()
        if not nome:
            return
        page.client_storage.set("caixa_nome", nome)
        ao_definir()

    return ft.Container(
        content=ft.Column(
            [
                ft.Icon(ft.icons.PHONE_ANDROID, color=theme.BRASA, size=48),
                theme.titulo("Como vamos chamar esse caixa?", tamanho=20),
                theme.subtitulo("Só nesse celular - ele vai lembrar dessa vez em diante.", tamanho=13),
                campo_nome,
                theme.botao_primario("Confirmar", icone=ft.icons.CHECK, on_click=confirmar),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=14,
        ),
        alignment=ft.alignment.center, expand=True, bgcolor=theme.BG, padding=40,
    )


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
    # "Mudar servidor/rede" e um atalho direto pra voltar na tela de escolha
    # (papel_rede.tela) sem passar por Configuracoes - existe pra sempre ter
    # um jeito de sair dessa tela mesmo que algo em Configuracoes falhe, e
    # cobre o caso mais comum de ficar preso aqui: um PC que ja tinha
    # papel_rede="cliente" configurado com o IP de OUTRA rede/evento (ex: PC
    # usado num teste anterior, levado pra um evento novo) - sem isso, o
    # unico jeito de corrigir era achar "Configuracoes > Conexao > Trocar",
    # varios cliques a mais bem no momento em que o app parece quebrado.
    def mudar_rede(e):
        cfg = settings.load()
        cfg["papel_rede"] = None
        settings.save(cfg)
        tentar_de_novo()

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
                ft.TextButton(
                    "Este PC deveria ser o principal ou conectar em outro IP? Mudar rede",
                    icon=ft.icons.SWAP_HORIZ, on_click=mudar_rede,
                    style=ft.ButtonStyle(color=theme.TEXTO_SUAVE),
                ),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10,
        ),
        alignment=ft.alignment.center, expand=True, bgcolor=theme.BG,
    )
