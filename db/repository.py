"""Camada de acesso a dados. Cada funcao abre/fecha sua propria conexao
(ver db.connection) e representa uma operacao de negocio completa.
"""

from decimal import Decimal

from psycopg.errors import UniqueViolation

from db.connection import conectar
from pathlib import Path
import sys

# ---------- Operadores ----------


def autenticar_operador(operador_id, pin):
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, nome, administrador FROM operadores WHERE id = %s AND pin = %s AND ativo",
            (operador_id, pin),
        )
        return cur.fetchone()


def garantir_schema(schema_path: str | None = None) -> None:
    """Verifica se a tabela `caixas` existe; se nao existir, aplica o schema SQL.

    A funcao tenta localizar `schema.sql` no codigo fonte (workspace) e ao lado
    do executavel empacotado. Se encontrar, executa o conteudo no banco.
    """
    # determinar caminho possivel do schema
    candidates = []
    # caminho relativo ao pacote (desenvolvimento)
    pkg_schema = Path(__file__).resolve().parent / "schema.sql"
    candidates.append(pkg_schema)
    # caminho relativo ao executavel (quando empacotado)
    if getattr(sys, "frozen", False):
        exe_parent = Path(sys.executable).parent
        candidates.append(exe_parent / "db" / "schema.sql")
        candidates.append(exe_parent / "schema.sql")
        candidates.append(exe_parent / "db_schema.sql")
        # PyInstaller (onedir, versoes recentes) guarda os dados embutidos
        # dentro de _internal/, nao direto do lado do .exe.
        candidates.append(exe_parent / "_internal" / "db" / "schema.sql")
    # uso do argumento, se fornecido, tem prioridade
    if schema_path:
        candidates.insert(0, Path(schema_path))

    schema_file = None
    for p in candidates:
        try:
            if p and p.exists():
                schema_file = p
                break
        except Exception:
            continue
    if not schema_file:
        return

    with conectar() as conn, conn.cursor() as cur:
        # checar existencia da tabela `caixas`
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'caixas')"
        )
        exists = cur.fetchone()
        if exists and list(exists.values())[0]:
            return
        # ler e aplicar o arquivo SQL
        sql = schema_file.read_text(encoding="utf-8")
        # executar todo o script (contendo varios statements)
        cur.execute(sql)
        # commit feito automaticamente pelo contextmanager `conectar`


def garantir_tabela_sync_controle() -> None:
    """Cria a tabela sync_controle se ainda nao existir - separado do
    garantir_schema principal pra tambem funcionar em bancos que ja existiam
    antes dessa tabela ser criada (nao so em bancos novos)."""
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS sync_controle ("
            "evento_id INTEGER PRIMARY KEY REFERENCES eventos(id), "
            "sincronizado_em TIMESTAMPTZ NOT NULL DEFAULT now())"
        )


def garantir_contador_por_evento() -> None:
    """Troca o contador de numero de pedido de 'por dia' pra 'por evento' -
    separado do garantir_schema principal pra tambem migrar bancos que ja
    existiam antes dessa mudanca (evita dois PED:1 num evento que passa da
    meia-noite)."""
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS contador_pedido_evento ("
            "evento_id INTEGER PRIMARY KEY REFERENCES eventos(id), "
            "ultimo_numero INTEGER NOT NULL DEFAULT 0)"
        )
        cur.execute("DROP FUNCTION IF EXISTS proximo_numero_pedido()")
        cur.execute(
            """CREATE OR REPLACE FUNCTION proximo_numero_pedido(p_evento_id INTEGER) RETURNS INTEGER AS $$
               DECLARE
                   n INTEGER;
               BEGIN
                   INSERT INTO contador_pedido_evento (evento_id, ultimo_numero)
                   VALUES (p_evento_id, 1)
                   ON CONFLICT (evento_id) DO UPDATE SET ultimo_numero = contador_pedido_evento.ultimo_numero + 1
                   RETURNING ultimo_numero INTO n;
                   RETURN n;
               END;
               $$ LANGUAGE plpgsql"""
        )


def garantir_coluna_ocultar_valor_produto() -> None:
    """Migracao pra bancos que ja existiam antes de 'nao mostrar valor na
    impressao' virar uma opcao do PRODUTO (era da venda antes) - adiciona a
    coluna se ainda nao existir."""
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            "ALTER TABLE produtos ADD COLUMN IF NOT EXISTS ocultar_valor_impressao "
            "BOOLEAN NOT NULL DEFAULT FALSE"
        )


def garantir_coluna_administrador_operador() -> None:
    """Migracao pra bancos que ja existiam antes do controle de administrador
    - adiciona a coluna se ainda nao existir."""
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            "ALTER TABLE operadores ADD COLUMN IF NOT EXISTS administrador BOOLEAN NOT NULL DEFAULT FALSE"
        )


def garantir_coluna_evento_operador() -> None:
    """Migracao pra bancos que ja existiam antes de operadores comuns
    resetarem por evento (2026-08-19) - so adiciona a coluna se nao existir.
    Linhas ja existentes ficam com evento_id NULL (tratadas como "sempre
    visiveis" - ver listar_operadores_disponiveis_para_login), pra nao
    remover ninguem da lista de login so por causa da migracao."""
    with conectar() as conn, conn.cursor() as cur:
        cur.execute("ALTER TABLE operadores ADD COLUMN IF NOT EXISTS evento_id INTEGER REFERENCES eventos(id)")


def garantir_admin_padrao() -> None:
    """O operador seed antigo (antes de existir a coluna administrador) tinha
    PIN '0000' e nao virava administrador automaticamente. Atualiza esse
    operador padrao pra PIN '1411' + administrador=True. So afeta quem ainda
    esta com o PIN '0000' original - se ja foi trocado, nao faz nada."""
    with conectar() as conn, conn.cursor() as cur:
        cur.execute("UPDATE operadores SET pin='1411', administrador=TRUE WHERE pin='0000'")


def garantir_pagamentos_venda() -> None:
    """Migracao pra bancos que ja existiam antes do pagamento dividido (mais
    de uma forma na mesma venda) - cria a tabela pagamentos_venda, o valor
    'VARIAS' do enum forma_pagamento, e faz backfill de 1 linha por venda ja
    existente (com a forma/valor que ja estava em vendas.forma_pagamento),
    senao os relatorios por forma de pagamento ficariam zerados pras vendas
    antigas."""
    with conectar() as conn, conn.cursor() as cur:
        cur.execute("ALTER TYPE forma_pagamento ADD VALUE IF NOT EXISTS 'VARIAS'")
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            """CREATE TABLE IF NOT EXISTS pagamentos_venda (
                id SERIAL PRIMARY KEY,
                venda_id INTEGER NOT NULL REFERENCES vendas(id) ON DELETE CASCADE,
                forma_pagamento forma_pagamento NOT NULL,
                valor NUMERIC(10, 2) NOT NULL CHECK (valor > 0)
            )"""
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_pagamentos_venda_venda ON pagamentos_venda (venda_id)")
        cur.execute(
            """INSERT INTO pagamentos_venda (venda_id, forma_pagamento, valor)
               SELECT v.id, v.forma_pagamento, v.valor_total FROM vendas v
               WHERE v.forma_pagamento != 'VARIAS'
                 AND NOT EXISTS (SELECT 1 FROM pagamentos_venda pv WHERE pv.venda_id = v.id)"""
        )


def garantir_schema_churrasco() -> None:
    """Migracao pra bancos que ja existiam antes do modulo Churrasco - cria
    as tabelas/tipo/funcao se ainda nao existirem. Postgres nao tem "CREATE
    TYPE IF NOT EXISTS" - o bloco DO/EXCEPTION e o jeito idiomatico de
    simular isso pra um enum novo. Nao cria mais `carnes_churrasco` - o
    cadastro/catalogo de carnes foi removido (carne+valor sao digitados na
    hora de emitir a ficha), essa tabela nunca chega a ser necessaria pra
    quem esta migrando pela primeira vez a partir de hoje."""
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            """DO $$ BEGIN
                   CREATE TYPE status_ficha_churrasco AS ENUM ('EMITIDA', 'CANCELADA');
               EXCEPTION WHEN duplicate_object THEN NULL;
               END $$;"""
        )
        cur.execute(
            """CREATE TABLE IF NOT EXISTS fichas_churrasco (
                id SERIAL PRIMARY KEY,
                sessao_caixa_id INTEGER NOT NULL REFERENCES sessoes_caixa(id),
                caixa_id INTEGER NOT NULL REFERENCES caixas(id),
                operador_id INTEGER NOT NULL REFERENCES operadores(id),
                nome_carne TEXT NOT NULL,
                valor NUMERIC(10, 2) NOT NULL,
                cor_hex TEXT NOT NULL,
                nome_cliente TEXT NOT NULL,
                numero_ficha INTEGER NOT NULL,
                forma_pagamento forma_pagamento NOT NULL DEFAULT 'DINHEIRO',
                status status_ficha_churrasco NOT NULL DEFAULT 'EMITIDA',
                motivo_cancelamento TEXT,
                criado_em TIMESTAMPTZ NOT NULL DEFAULT now()
            )"""
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_fichas_churrasco_sessao ON fichas_churrasco (sessao_caixa_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_fichas_churrasco_cor ON fichas_churrasco (cor_hex)")
        cur.execute(
            """CREATE TABLE IF NOT EXISTS contador_ficha_churrasco_evento (
                evento_id INTEGER PRIMARY KEY REFERENCES eventos(id),
                ultimo_numero INTEGER NOT NULL DEFAULT 0
            )"""
        )
        cur.execute(
            """CREATE OR REPLACE FUNCTION proximo_numero_ficha_churrasco(p_evento_id INTEGER) RETURNS INTEGER AS $$
               DECLARE
                   n INTEGER;
               BEGIN
                   INSERT INTO contador_ficha_churrasco_evento (evento_id, ultimo_numero)
                   VALUES (p_evento_id, 1)
                   ON CONFLICT (evento_id) DO UPDATE SET ultimo_numero = contador_ficha_churrasco_evento.ultimo_numero + 1
                   RETURNING ultimo_numero INTO n;
                   RETURN n;
               END;
               $$ LANGUAGE plpgsql"""
        )


def garantir_tabela_faixas_numeracao_churrasco() -> None:
    """Migracao pra quem instalou o modulo Churrasco antes das faixas de
    numeracao existirem (2026.08.10) - cria a tabela se ainda nao existir.
    carnes_churrasco.cor_hex deixou de ser usada (a cor agora vem da faixa,
    nao da carne) mas a coluna antiga fica intocada em bancos ja existentes -
    sem risco de dropar coluna com dados."""
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            """CREATE TABLE IF NOT EXISTS faixas_numeracao_churrasco (
                id SERIAL PRIMARY KEY,
                evento_id INTEGER NOT NULL REFERENCES eventos(id),
                numero_inicio INTEGER NOT NULL CHECK (numero_inicio > 0),
                numero_fim INTEGER NOT NULL CHECK (numero_fim >= numero_inicio),
                cor_hex TEXT NOT NULL,
                criado_em TIMESTAMPTZ NOT NULL DEFAULT now()
            )"""
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_faixas_numeracao_churrasco_evento "
            "ON faixas_numeracao_churrasco (evento_id)"
        )


def garantir_coluna_pagamento_churrasco() -> None:
    """Migracao pra quem instalou o modulo Churrasco antes da forma de
    pagamento existir (2026.08.07.6) - adiciona a coluna se ainda nao
    existir. Fichas antigas sem essa informacao ficam com 'DINHEIRO' (o
    default) so pra nao ter linha nula; nao ha como recuperar a forma real
    usada antes dessa coluna existir."""
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            "ALTER TABLE fichas_churrasco ADD COLUMN IF NOT EXISTS forma_pagamento "
            "forma_pagamento NOT NULL DEFAULT 'DINHEIRO'"
        )


def garantir_colunas_pago_entregue_churrasco() -> None:
    """Migracao pra quem instalou o modulo Churrasco antes de 'pago'/'entregue'
    existirem (2026-08-11) - controle de fichas vendidas "no fio" (sem pagar
    na hora) e de entrega da carne, pedido explicito do usuario. Fichas
    antigas ficam com pago=true (assume-se que ja foram pagas, ja que antes
    pagamento era obrigatorio na hora) e entregue=false (nao ha como saber
    retroativamente). forma_pagamento precisa aceitar NULL a partir de agora
    (fica NULL enquanto pago=false) - relaxar NOT NULL nao afeta as linhas
    existentes, que ja tem valor."""
    with conectar() as conn, conn.cursor() as cur:
        cur.execute("ALTER TABLE fichas_churrasco ADD COLUMN IF NOT EXISTS pago BOOLEAN NOT NULL DEFAULT TRUE")
        cur.execute("ALTER TABLE fichas_churrasco ADD COLUMN IF NOT EXISTS entregue BOOLEAN NOT NULL DEFAULT FALSE")
        cur.execute("ALTER TABLE fichas_churrasco ALTER COLUMN forma_pagamento DROP NOT NULL")


def garantir_blocos_numeracao_churrasco() -> None:
    """Migracao pra quem instalou o modulo Churrasco antes dos blocos de
    numeracao independentes existirem (2026-08-11) - pedido explicito do
    usuario: cada faixa/bloco (ver faixas_numeracao_churrasco) passou a ter
    seu PROPRIO contador, em vez de um unico contador global do evento (que
    so cruzava de bloco em bloco automaticamente, sem deixar o operador
    escolher). Ver definir_faixas_numeracao_churrasco e
    registrar_ficha_churrasco_do_bloco.

    fichas_churrasco ganha `evento_id` (denormalizado, direto - antes so
    vinha via sessao_caixa_id) pra permitir uma UNIQUE (evento_id,
    numero_ficha) de verdade no banco - garantia real contra ficha
    duplicada, nao so o contador atomico (pedido explicito do usuario:
    "não quero depender só de um contador visual... utilize uma
    restrição/validação no banco de dados"). Fichas antigas sao
    retroativamente preenchidas via join com sessoes_caixa."""
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            """CREATE TABLE IF NOT EXISTS contador_ficha_churrasco_bloco (
                evento_id INTEGER NOT NULL REFERENCES eventos(id),
                numero_inicio INTEGER NOT NULL,
                ultimo_numero INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (evento_id, numero_inicio)
            )"""
        )
        cur.execute("ALTER TABLE fichas_churrasco ADD COLUMN IF NOT EXISTS evento_id INTEGER REFERENCES eventos(id)")
        cur.execute(
            """UPDATE fichas_churrasco f SET evento_id = s.evento_id
               FROM sessoes_caixa s WHERE s.id = f.sessao_caixa_id AND f.evento_id IS NULL"""
        )
        cur.execute("ALTER TABLE fichas_churrasco ALTER COLUMN evento_id SET NOT NULL")
        cur.execute(
            """DO $$ BEGIN
                   ALTER TABLE fichas_churrasco ADD CONSTRAINT uq_fichas_churrasco_evento_numero
                       UNIQUE (evento_id, numero_ficha);
               EXCEPTION WHEN duplicate_object OR duplicate_table THEN NULL;
               END $$;"""
        )


def listar_operadores(somente_ativos=True):
    """Lista TODOS os operadores (qualquer evento, inclusive de eventos ja
    fechados) - usada em Configuracoes > Operadores, onde o administrador
    gerencia/reativa o cadastro completo. Pro seletor de LOGIN (onde
    operador comum de evento fechado nao deveria aparecer/autenticar mais),
    ver listar_operadores_disponiveis_para_login()."""
    with conectar() as conn, conn.cursor() as cur:
        if somente_ativos:
            cur.execute("SELECT id, nome, administrador FROM operadores WHERE ativo ORDER BY nome")
        else:
            cur.execute("SELECT id, nome, ativo, administrador FROM operadores ORDER BY nome")
        return cur.fetchall()


def listar_operadores_disponiveis_para_login():
    """Pedido explicito do usuario (2026-08-19, audio): operador comum
    "reseta" por evento - some do seletor de login quando o evento em que
    foi cadastrado fecha e outro evento abre (nao precisa mais desativar
    manualmente um por um a cada festa nova). Administrador e SEMPRE global/
    fixo (nunca some). evento_id NULL tambem sempre aparece - e o estado de
    quem ja existia antes dessa coluna existir (ver
    garantir_coluna_evento_operador), pra nao "sumir" cadastro de ninguem
    so por causa da migracao."""
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT o.id, o.nome, o.administrador FROM operadores o
               WHERE o.ativo AND (o.administrador OR o.evento_id IS NULL
                   OR o.evento_id = (SELECT id FROM eventos WHERE status = 'ABERTA'))
               ORDER BY o.nome"""
        )
        return cur.fetchall()


def criar_operador(nome, pin, administrador=False):
    """Administrador fica sempre com evento_id NULL (global/fixo). Operador
    comum fica vinculado ao evento ATUALMENTE aberto (se houver algum) - e
    isso que faz ele "sumir" do login quando esse evento fechar e outro
    abrir, ate ser reativado (ver definir_ativo_operador)."""
    with conectar() as conn, conn.cursor() as cur:
        evento_id = None
        if not administrador:
            cur.execute("SELECT id FROM eventos WHERE status = 'ABERTA'")
            evento_aberto = cur.fetchone()
            evento_id = evento_aberto["id"] if evento_aberto else None
        cur.execute(
            "INSERT INTO operadores (nome, pin, administrador, evento_id) VALUES (%s, %s, %s, %s) RETURNING id",
            (nome, pin, administrador, evento_id),
        )
        return cur.fetchone()["id"]


def definir_ativo_operador(operador_id, ativo):
    with conectar() as conn, conn.cursor() as cur:
        cur.execute("UPDATE operadores SET ativo = %s WHERE id = %s", (ativo, operador_id))
        if ativo:
            # Reativar um operador comum (nao administrador) o "migra" pro
            # evento atualmente aberto - pedido do usuario (2026-08-19): sem
            # isso, reativar um operador de um evento antigo nao adiantaria
            # nada (ele continuaria escondido do login por pertencer a um
            # evento ja fechado). Administrador nunca e afetado (WHERE NOT
            # administrador) - continua global/fixo sempre.
            cur.execute(
                """UPDATE operadores SET evento_id = (SELECT id FROM eventos WHERE status = 'ABERTA')
                   WHERE id = %s AND NOT administrador""",
                (operador_id,),
            )


# ---------- Caixas ----------


def listar_caixas(somente_ativos=True):
    with conectar() as conn, conn.cursor() as cur:
        if somente_ativos:
            cur.execute("SELECT id, nome FROM caixas WHERE ativo ORDER BY nome")
        else:
            cur.execute("SELECT id, nome, ativo FROM caixas ORDER BY nome")
        return cur.fetchall()


def criar_caixa(nome):
    with conectar() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO caixas (nome) VALUES (%s) RETURNING id", (nome,))
        return cur.fetchone()["id"]


def obter_ou_criar_caixa(nome):
    with conectar() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM caixas WHERE nome = %s", (nome,))
        row = cur.fetchone()
        if row:
            return row["id"]
        cur.execute("INSERT INTO caixas (nome) VALUES (%s) RETURNING id", (nome,))
        return cur.fetchone()["id"]


# ---------- Categorias / Produtos ----------


def listar_categorias():
    with conectar() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, nome, ordem FROM categorias_produto ORDER BY ordem, nome")
        return cur.fetchall()


def criar_categoria(nome, ordem=0):
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO categorias_produto (nome, ordem) VALUES (%s, %s) RETURNING id",
            (nome, ordem),
        )
        return cur.fetchone()["id"]


def listar_produtos(somente_ativos=True, incluir_ocultos=True):
    with conectar() as conn, conn.cursor() as cur:
        sql = """
            SELECT p.id, p.nome, p.preco, p.custo, p.cor_hex, p.estoque_controlado,
                   p.estoque_atual, p.eh_combo, p.ativo, p.oculto, p.ordem,
                   p.ocultar_valor_impressao, p.categoria_id, c.nome AS categoria_nome
            FROM produtos p
            LEFT JOIN categorias_produto c ON c.id = p.categoria_id
        """
        condicoes = []
        if somente_ativos:
            condicoes.append("p.ativo")
        if not incluir_ocultos:
            condicoes.append("NOT p.oculto")
        if condicoes:
            sql += " WHERE " + " AND ".join(condicoes)
        # Ordem e global (nao por categoria) - dá pra organizar o layout da
        # grade de venda inteira, misturando categorias, em Configuracoes >
        # Produtos > Organizar layout. Quando filtrado por categoria (ver
        # venda.py), essa mesma ordem global continua valendo dentro do
        # subconjunto filtrado.
        sql += " ORDER BY p.ordem, p.nome"
        cur.execute(sql)
        return cur.fetchall()


def definir_ordem_produtos(ids_em_ordem):
    """ids_em_ordem: lista de ids de produto na ordem visual desejada (todos
    da MESMA categoria, ver ui/screens/configuracao.py - editor de layout).
    Renumera ordem=0,1,2... nessa sequencia, sobrescrevendo o que tinha antes.
    As UPDATEs sao feitas em ordem crescente de id (nao na ordem visual, que
    varia a cada chamada) para sempre travar as linhas na mesma sequencia -
    sem isso, duas chamadas concorrentes (dois admins reorganizando ao mesmo
    tempo) podem travar as mesmas linhas em ordem invertida uma da outra e o
    Postgres derruba uma delas com "deadlock detected" (visto no teste de
    carga com reordenacoes concorrentes)."""
    novas_ordens = {produto_id: posicao for posicao, produto_id in enumerate(ids_em_ordem)}
    with conectar() as conn, conn.cursor() as cur:
        for produto_id in sorted(novas_ordens):
            cur.execute("UPDATE produtos SET ordem = %s WHERE id = %s", (novas_ordens[produto_id], produto_id))


def excluir_produto(produto_id):
    """Exclui o produto de verdade (diferente de desativar/ocultar, que so
    esconde da venda mas mantem o cadastro). Bloqueado se o produto ja tem
    venda registrada - nesse caso perderia o historico, o certo e usar os
    switches Ativo/Ocultar em vez de excluir. Se ele for componente de algum
    combo, so remove essa linha da composicao daquele combo (nao bloqueia).
    Itens excluidos do carrinho (itens_excluidos) que citam esse produto
    mantem o registro (nome/quantidade/valor ja congelados), so perdem a
    referencia ao cadastro."""
    with conectar() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM itens_venda WHERE produto_id = %s LIMIT 1", (produto_id,))
        if cur.fetchone():
            raise ValueError(
                "Esse produto já tem vendas registradas e não pode ser excluído "
                "(perderia o histórico). Use \"Ativo\"/\"Ocultar\" para escondê-lo em vez disso."
            )
        cur.execute("UPDATE itens_excluidos SET produto_id = NULL WHERE produto_id = %s", (produto_id,))
        cur.execute("DELETE FROM combo_itens WHERE produto_componente_id = %s", (produto_id,))
        cur.execute("DELETE FROM produtos WHERE id = %s", (produto_id,))


def criar_produto(nome, preco, categoria_id=None, custo=0, cor_hex="#E07A3E",
                   estoque_controlado=False, estoque_atual=None, eh_combo=False, ordem=0,
                   ocultar_valor_impressao=False):
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO produtos
               (nome, preco, categoria_id, custo, cor_hex, estoque_controlado,
                estoque_atual, eh_combo, ordem, ocultar_valor_impressao)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (nome, preco, categoria_id, custo, cor_hex, estoque_controlado,
             estoque_atual, eh_combo, ordem, ocultar_valor_impressao),
        )
        return cur.fetchone()["id"]


def atualizar_produto(produto_id, nome, preco, categoria_id=None, custo=0, cor_hex="#E07A3E",
                       estoque_controlado=False, estoque_atual=None, eh_combo=False,
                       ativo=True, oculto=False, ocultar_valor_impressao=False):
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE produtos SET nome=%s, preco=%s, categoria_id=%s, custo=%s, cor_hex=%s,
               estoque_controlado=%s, estoque_atual=%s, eh_combo=%s, ativo=%s, oculto=%s,
               ocultar_valor_impressao=%s
               WHERE id=%s""",
            (nome, preco, categoria_id, custo, cor_hex, estoque_controlado,
             estoque_atual, eh_combo, ativo, oculto, ocultar_valor_impressao, produto_id),
        )


def ajustar_estoque(produto_id, delta):
    """delta negativo para consumo na venda, positivo para reposicao manual."""
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE produtos SET estoque_atual = estoque_atual + %s
               WHERE id = %s AND estoque_controlado""",
            (delta, produto_id),
        )


# ---------- Combos (kits) ----------


def listar_itens_combo(produto_combo_id):
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT ci.id, ci.produto_componente_id, ci.quantidade, p.nome, p.preco
               FROM combo_itens ci
               JOIN produtos p ON p.id = ci.produto_componente_id
               WHERE ci.produto_combo_id = %s""",
            (produto_combo_id,),
        )
        return cur.fetchall()


def definir_itens_combo(produto_combo_id, itens):
    """itens: lista de {"produto_componente_id": int, "quantidade": int}.
    Substitui a composicao inteira do combo pela lista informada."""
    with conectar() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM combo_itens WHERE produto_combo_id = %s", (produto_combo_id,))
        for item in itens:
            cur.execute(
                """INSERT INTO combo_itens (produto_combo_id, produto_componente_id, quantidade)
                   VALUES (%s, %s, %s)""",
                (produto_combo_id, item["produto_componente_id"], item["quantidade"]),
            )


# ---------- Sessao de caixa ----------


def obter_sessao_aberta(caixa_id):
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id, caixa_id, operador_abertura_id, valor_abertura, data_abertura
               FROM sessoes_caixa WHERE caixa_id = %s AND status = 'ABERTA'""",
            (caixa_id,),
        )
        return cur.fetchone()


def abrir_sessao(evento_id, caixa_id, operador_id, valor_abertura):
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO sessoes_caixa (evento_id, caixa_id, operador_abertura_id, valor_abertura)
               VALUES (%s, %s, %s, %s) RETURNING id""",
            (evento_id, caixa_id, operador_id, valor_abertura),
        )
        return cur.fetchone()["id"]


# ---------- Eventos (festas) ----------


def obter_evento_aberto():
    with conectar() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, nome, rodape, data_abertura FROM eventos WHERE status = 'ABERTA'")
        return cur.fetchone()


def listar_eventos():
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id, nome, status, data_abertura, data_fechamento
               FROM eventos ORDER BY data_abertura DESC"""
        )
        return cur.fetchall()


def criar_evento(nome, rodape=""):
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO eventos (nome, rodape) VALUES (%s, %s) RETURNING id",
            (nome, rodape),
        )
        return cur.fetchone()["id"]


def atualizar_evento(evento_id, nome, rodape):
    with conectar() as conn, conn.cursor() as cur:
        cur.execute("UPDATE eventos SET nome=%s, rodape=%s WHERE id=%s", (nome, rodape, evento_id))


def existe_sessao_aberta_no_evento(evento_id):
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM sessoes_caixa WHERE evento_id = %s AND status = 'ABERTA' LIMIT 1",
            (evento_id,),
        )
        return cur.fetchone() is not None


def fechar_evento(evento_id):
    """So fecha se nenhum caixa desse evento estiver com sessao aberta."""
    if existe_sessao_aberta_no_evento(evento_id):
        raise ValueError("Existe caixa aberto nesse evento. Feche todos os caixas antes.")
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE eventos SET status='FECHADA', data_fechamento=now() WHERE id=%s",
            (evento_id,),
        )


def registrar_movimento(sessao_id, tipo, valor, motivo, operador_id):
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO movimentos_caixa (sessao_caixa_id, tipo, valor, motivo, operador_id)
               VALUES (%s, %s, %s, %s, %s) RETURNING id""",
            (sessao_id, tipo, valor, motivo, operador_id),
        )
        return cur.fetchone()["id"]


# ---------- Vendas ----------


def _consumir_estoque(cur, produto_id, quantidade, nome_para_erro):
    """Desconta do estoque SO se tiver o suficiente (a condicao vai dentro do
    proprio UPDATE, atomica - o Postgres trava a linha durante a checagem+troca,
    entao dois caixas vendendo o ultimo item ao mesmo tempo nunca conseguem os
    dois passar: um dos dois sempre ve estoque_atual < quantidade e cai no
    ValueError abaixo, nunca fica negativo). Produto sem estoque_controlado
    (estoque_atual NULL/nao controlado) nunca bloqueia - continua sem controle,
    como sempre foi. Achado em produção (2026-08): cliente vendeu o mesmo
    produto (estoque=1) em dois caixas diferentes porque o controle antes era
    so um aviso visual ("Só resta 1"/"ESGOTADO"), nunca bloqueava a venda de
    verdade - a tela de outro caixa so atualiza o aviso com um delay (poll de
    catálogo), then virou venda duplicada real. Bloquear aqui, no banco, e a
    unica forma de garantir "instantaneo" de verdade - não tem como um
    refresh de tela nunca ser mais rapido que isso."""
    cur.execute(
        """UPDATE produtos SET estoque_atual = estoque_atual - %s
           WHERE id = %s AND estoque_controlado AND estoque_atual >= %s""",
        (quantidade, produto_id, quantidade),
    )
    if cur.rowcount > 0:
        return
    cur.execute("SELECT estoque_controlado, estoque_atual FROM produtos WHERE id = %s", (produto_id,))
    produto = cur.fetchone()
    if produto and produto["estoque_controlado"]:
        raise ValueError(
            f"Estoque insuficiente para \"{nome_para_erro}\" (restam {produto['estoque_atual']}, "
            f"pedido {quantidade}) - outro caixa deve ter vendido antes. Venda cancelada."
        )


def registrar_venda(sessao_id, caixa_id, operador_id, itens, pagamentos):
    """itens: lista de dicts {produto_id, nome, preco, quantidade, custo (opcional)}.
    pagamentos: lista de dicts {forma, valor} - o total dos valores deve bater
    com o total dos itens (nao e validado aqui, quem monta a lista antes ja
    garante isso). Uma venda paga em uma unica forma vira so 1 item nessa
    lista - "pagamento dividido" e so o caso de ter mais de um.
    Consome estoque dos produtos com estoque_controlado=TRUE - bloqueia a
    venda inteira (ValueError, nada e salvo) se nao tiver estoque suficiente
    pra algum item ou componente de combo. Se o item for um combo, tambem
    consome o estoque dos produtos que compoem ele."""
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT proximo_numero_pedido(evento_id) AS n FROM sessoes_caixa WHERE id = %s""",
            (sessao_id,),
        )
        numero_pedido = cur.fetchone()["n"]

        valor_total = sum(Decimal(str(i["preco"])) * i["quantidade"] for i in itens)
        forma_pagamento = pagamentos[0]["forma"] if len(pagamentos) == 1 else "VARIAS"
        cur.execute(
            """INSERT INTO vendas (sessao_caixa_id, caixa_id, operador_id, numero_pedido,
                                    forma_pagamento, valor_total)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
            (sessao_id, caixa_id, operador_id, numero_pedido, forma_pagamento, valor_total),
        )
        venda_id = cur.fetchone()["id"]

        for pagamento in pagamentos:
            cur.execute(
                "INSERT INTO pagamentos_venda (venda_id, forma_pagamento, valor) VALUES (%s, %s, %s)",
                (venda_id, pagamento["forma"], pagamento["valor"]),
            )

        for item in itens:
            subtotal = Decimal(str(item["preco"])) * item["quantidade"]
            cur.execute(
                """INSERT INTO itens_venda
                   (venda_id, produto_id, nome_produto, quantidade, preco_unitario, custo_unitario, subtotal)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (venda_id, item["produto_id"], item["nome"], item["quantidade"],
                 item["preco"], item.get("custo", 0), subtotal),
            )
            _consumir_estoque(cur, item["produto_id"], item["quantidade"], item["nome"])
            cur.execute(
                "SELECT p.nome, ci.produto_componente_id, ci.quantidade FROM combo_itens ci "
                "JOIN produtos p ON p.id = ci.produto_componente_id WHERE ci.produto_combo_id = %s",
                (item["produto_id"],),
            )
            for componente in cur.fetchall():
                _consumir_estoque(
                    cur, componente["produto_componente_id"], componente["quantidade"] * item["quantidade"],
                    f"{componente['nome']} (componente de {item['nome']})",
                )

    return {"venda_id": venda_id, "numero_pedido": numero_pedido, "valor_total": valor_total}


def expandir_itens_para_impressao(itens):
    """Combo nao imprime uma ficha so pra ele - imprime uma ficha de cada
    produto que compoe o combo (ex: Combo 4 Cervejas -> 4 fichas de Cerveja).
    Produtos normais passam direto. O preco de cada ficha do combo e o preco
    do combo dividido pelo total de unidades que ele tem (nao o preco de
    balcao do componente, que normalmente e maior - o combo e um desconto).

    Cada ficha resultante ja vem com "ocultar_valor" (do cadastro do PRODUTO,
    nao mais uma escolha por venda) - pro componente de um combo, e a flag do
    componente em si que vale, nao a do combo."""
    with conectar() as conn, conn.cursor() as cur:
        expandido = []
        for item in itens:
            cur.execute(
                "SELECT produto_componente_id, quantidade, nome, ocultar_valor_impressao FROM combo_itens ci "
                "JOIN produtos p ON p.id = ci.produto_componente_id WHERE ci.produto_combo_id = %s",
                (item["produto_id"],),
            )
            componentes = cur.fetchall()
            if not componentes:
                cur.execute("SELECT ocultar_valor_impressao FROM produtos WHERE id = %s", (item["produto_id"],))
                linha = cur.fetchone()
                expandido.append({**item, "ocultar_valor": bool(linha["ocultar_valor_impressao"]) if linha else False})
                continue
            total_unidades = sum(c["quantidade"] for c in componentes)
            preco_por_ficha = Decimal(str(item["preco"])) / total_unidades if total_unidades else Decimal("0")
            for _ in range(item["quantidade"]):
                for componente in componentes:
                    expandido.append({
                        "produto_id": componente["produto_componente_id"],
                        "nome": componente["nome"],
                        "preco": preco_por_ficha,
                        "quantidade": componente["quantidade"],
                        "ocultar_valor": bool(componente["ocultar_valor_impressao"]),
                    })
    return expandido


def registrar_item_excluido(sessao_id, caixa_id, operador_id, produto_id, nome, quantidade, valor, motivo=None):
    """Registra um item removido do carrinho antes de finalizar o pedido
    (auditoria/antifraude) - nao afeta vendas ja concluidas."""
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO itens_excluidos
               (sessao_caixa_id, caixa_id, operador_id, produto_id, nome_produto, quantidade, valor, motivo)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (sessao_id, caixa_id, operador_id, produto_id, nome, quantidade, valor, motivo),
        )
        return cur.fetchone()["id"]


def registrar_troca(sessao_id, caixa_id, operador_id, produto_saida, quantidade_saida,
                     produto_entrada=None, quantidade_entrada=0, motivo=None):
    """produto_saida/produto_entrada: dict {id, nome, preco} (entrada pode ser None
    se o cliente so devolveu o item sem levar outro no lugar)."""
    valor_saida = Decimal(str(produto_saida["preco"])) * quantidade_saida
    valor_entrada = Decimal(str(produto_entrada["preco"])) * quantidade_entrada if produto_entrada else Decimal("0")
    diferenca = valor_entrada - valor_saida

    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO trocas (sessao_caixa_id, caixa_id, operador_id, produto_saida_id, nome_saida,
                                    quantidade_saida, valor_saida, produto_entrada_id, nome_entrada,
                                    quantidade_entrada, valor_entrada, diferenca_valor, motivo)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (sessao_id, caixa_id, operador_id,
             produto_saida["id"], produto_saida["nome"], quantidade_saida, valor_saida,
             produto_entrada["id"] if produto_entrada else None,
             produto_entrada["nome"] if produto_entrada else None,
             quantidade_entrada if produto_entrada else None,
             valor_entrada, diferenca, motivo),
        )
        return cur.fetchone()["id"]


def trocas_da_sessao(sessao_id):
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT nome_saida, quantidade_saida, nome_entrada, quantidade_entrada,
                      diferenca_valor, criado_em
               FROM trocas WHERE sessao_caixa_id = %s ORDER BY criado_em DESC""",
            (sessao_id,),
        )
        return cur.fetchall()


def cancelar_venda(venda_id, motivo):
    """Marca a venda como CANCELADA e devolve o estoque dos itens com
    estoque_controlado. So cancela vendas ainda CONCLUIDA (evita cancelar
    duas vezes e devolver estoque em dobro)."""
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE vendas SET status='CANCELADA', motivo_cancelamento=%s WHERE id=%s AND status='CONCLUIDA'",
            (motivo, venda_id),
        )
        if cur.rowcount == 0:
            raise ValueError("Venda nao encontrada ou ja cancelada.")
        cur.execute("SELECT produto_id, quantidade FROM itens_venda WHERE venda_id = %s", (venda_id,))
        for item in cur.fetchall():
            cur.execute(
                "UPDATE produtos SET estoque_atual = estoque_atual + %s WHERE id = %s AND estoque_controlado",
                (item["quantidade"], item["produto_id"]),
            )
            cur.execute(
                "SELECT produto_componente_id, quantidade FROM combo_itens WHERE produto_combo_id = %s",
                (item["produto_id"],),
            )
            for componente in cur.fetchall():
                cur.execute(
                    "UPDATE produtos SET estoque_atual = estoque_atual + %s WHERE id = %s AND estoque_controlado",
                    (componente["quantidade"] * item["quantidade"], componente["produto_componente_id"]),
                )


def vendas_recentes(sessao_id, limite=20):
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id, numero_pedido, valor_total, forma_pagamento, status, criado_em
               FROM vendas WHERE sessao_caixa_id = %s
               ORDER BY criado_em DESC LIMIT %s""",
            (sessao_id, limite),
        )
        return cur.fetchall()


def contar_vendas_caixa_no_evento(caixa_id, evento_id):
    """Quantos pedidos (vendas concluidas) esse caixa ja fez nesse evento -
    conta em TODAS as sessoes desse caixa no evento (nao so a sessao atual),
    pra continuar certo mesmo se o caixa foi fechado e reaberto no meio do
    mesmo evento. Mostrado na tela de venda, acima do carrinho."""
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT COUNT(*) AS qtd FROM vendas v
               JOIN sessoes_caixa s ON s.id = v.sessao_caixa_id
               WHERE v.caixa_id = %s AND s.evento_id = %s AND v.status = 'CONCLUIDA'""",
            (caixa_id, evento_id),
        )
        return cur.fetchone()["qtd"]


def detalhes_venda(venda_id):
    """Tudo que e preciso pra reimprimir a ficha de uma venda ja registrada."""
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT v.id, v.numero_pedido, v.criado_em, v.forma_pagamento, v.status,
                      c.nome AS caixa_nome, o.nome AS operador_nome
               FROM vendas v
               JOIN caixas c ON c.id = v.caixa_id
               JOIN operadores o ON o.id = v.operador_id
               WHERE v.id = %s""",
            (venda_id,),
        )
        venda = cur.fetchone()
        cur.execute(
            """SELECT produto_id, nome_produto AS nome, quantidade, preco_unitario AS preco
               FROM itens_venda WHERE venda_id = %s""",
            (venda_id,),
        )
        itens = cur.fetchall()
    return {"venda": venda, "itens": itens}


# ---------- Fechamento ----------


def resumo_sessao(sessao_id):
    with conectar() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM sessoes_caixa WHERE id = %s", (sessao_id,))
        sessao = cur.fetchone()

        cur.execute(
            """SELECT COALESCE(SUM(valor), 0) AS total FROM movimentos_caixa
               WHERE sessao_caixa_id=%s AND tipo='REFORCO'""",
            (sessao_id,),
        )
        adicional = cur.fetchone()["total"]

        cur.execute(
            """SELECT COALESCE(SUM(valor), 0) AS total FROM movimentos_caixa
               WHERE sessao_caixa_id=%s AND tipo='SANGRIA'""",
            (sessao_id,),
        )
        sangria = cur.fetchone()["total"]

        cur.execute(
            """SELECT pv.forma_pagamento, COALESCE(SUM(pv.valor), 0) AS total
               FROM pagamentos_venda pv
               JOIN vendas v ON v.id = pv.venda_id
               WHERE v.sessao_caixa_id=%s AND v.status='CONCLUIDA'
               GROUP BY pv.forma_pagamento""",
            (sessao_id,),
        )
        por_forma = {r["forma_pagamento"]: r["total"] for r in cur.fetchall()}

        # Fichas de churrasco entram no MESMO calculo de dinheiro/cartao/pix do
        # caixa - sem isso, o fechamento ficava sem a receita do churrasco.
        # "AND f.pago" e essencial: fichas vendidas "no fio" (pago=false) nao
        # tem forma_pagamento definida ainda e NAO devem contar aqui - so
        # depois que alguem finalizar o pagamento de verdade (ver
        # finalizar_pagamento_ficha), senao o fechamento contaria dinheiro
        # que ainda nao entrou no caixa.
        cur.execute(
            """SELECT f.forma_pagamento, COALESCE(SUM(f.valor), 0) AS total
               FROM fichas_churrasco f
               WHERE f.sessao_caixa_id=%s AND f.status='EMITIDA' AND f.pago
               GROUP BY f.forma_pagamento""",
            (sessao_id,),
        )
        for r in cur.fetchall():
            por_forma[r["forma_pagamento"]] = por_forma.get(r["forma_pagamento"], Decimal("0")) + r["total"]

        cur.execute(
            """SELECT iv.nome_produto, SUM(iv.quantidade) AS quantidade,
                      iv.preco_unitario, SUM(iv.subtotal) AS total
               FROM itens_venda iv
               JOIN vendas v ON v.id = iv.venda_id
               WHERE v.sessao_caixa_id = %s AND v.status = 'CONCLUIDA'
               GROUP BY iv.nome_produto, iv.preco_unitario
               ORDER BY iv.nome_produto""",
            (sessao_id,),
        )
        itens_vendidos = cur.fetchall()

        # Fichas de churrasco pagas entram na MESMA lista "itens_vendidos" do
        # fechamento (relatorio impresso e tela) - sem isso, o dinheiro delas
        # ja contava no total (ver `por_forma` acima), mas elas nunca
        # apareciam na relacao de itens vendidos, dando a falsa impressao de
        # que o fechamento "nao pegava" as fichas de churrasco (bug real
        # reportado pelo usuario, 2026-08-11). Mesmo filtro AND f.pago do
        # `por_forma` acima - ficha vendida "no fio" so entra aqui depois que
        # alguem finalizar o pagamento de verdade.
        cur.execute(
            """SELECT f.nome_carne AS nome_produto, COUNT(*) AS quantidade,
                      f.valor AS preco_unitario, SUM(f.valor) AS total
               FROM fichas_churrasco f
               WHERE f.sessao_caixa_id = %s AND f.status = 'EMITIDA' AND f.pago
               GROUP BY f.nome_carne, f.valor
               ORDER BY f.nome_carne""",
            (sessao_id,),
        )
        itens_vendidos = itens_vendidos + cur.fetchall()

        cur.execute(
            """SELECT COALESCE(SUM(quantidade), 0) AS qtd, COALESCE(SUM(valor), 0) AS total
               FROM itens_excluidos WHERE sessao_caixa_id = %s""",
            (sessao_id,),
        )
        excluidos = cur.fetchone()

        cur.execute(
            """SELECT COALESCE(SUM(iv.custo_unitario * iv.quantidade), 0) AS total
               FROM itens_venda iv
               JOIN vendas v ON v.id = iv.venda_id
               WHERE v.sessao_caixa_id = %s AND v.status = 'CONCLUIDA'""",
            (sessao_id,),
        )
        custo_total = cur.fetchone()["total"]

        cur.execute(
            """SELECT COALESCE(SUM(diferenca_valor), 0) AS total FROM trocas
               WHERE sessao_caixa_id = %s""",
            (sessao_id,),
        )
        trocas_total = cur.fetchone()["total"]

    dinheiro_vendas = por_forma.get("DINHEIRO", Decimal("0"))
    total_dinheiro = sessao["valor_abertura"] + adicional + dinheiro_vendas - sangria + trocas_total

    return {
        "sessao": sessao,
        "abertura": sessao["valor_abertura"],
        "adicional": adicional,
        "sangria": sangria,
        "dinheiro_vendas": dinheiro_vendas,
        "total_dinheiro": total_dinheiro,
        "cartao_credito": por_forma.get("CARTAO_CREDITO", Decimal("0")),
        "cartao_debito": por_forma.get("CARTAO_DEBITO", Decimal("0")),
        "pix": por_forma.get("PIX", Decimal("0")),
        "consumacao": por_forma.get("CONSUMACAO", Decimal("0")),
        "itens_vendidos": itens_vendidos,
        "total_geral_qtd": sum(i["quantidade"] for i in itens_vendidos),
        "total_geral_valor": sum(i["total"] for i in itens_vendidos),
        "itens_excluidos_qtd": excluidos["qtd"],
        "itens_excluidos_valor": excluidos["total"],
        "custo_total": custo_total,
        "lucro_total": sum(i["total"] for i in itens_vendidos) - custo_total,
        "trocas_total": trocas_total,
    }


def fechar_sessao(sessao_id, operador_id):
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE sessoes_caixa SET status='FECHADA', operador_fechamento_id=%s,
               data_fechamento=now() WHERE id=%s""",
            (operador_id, sessao_id),
        )


# ---------- Relatorios ----------


def produtos_mais_vendidos(evento_id, limite=20):
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT iv.nome_produto, SUM(iv.quantidade) AS quantidade, SUM(iv.subtotal) AS total
               FROM itens_venda iv
               JOIN vendas v ON v.id = iv.venda_id
               JOIN sessoes_caixa s ON s.id = v.sessao_caixa_id
               WHERE v.status = 'CONCLUIDA' AND (%s::int IS NULL OR s.evento_id = %s)
               GROUP BY iv.nome_produto
               ORDER BY quantidade DESC
               LIMIT %s""",
            (evento_id, evento_id, limite),
        )
        return cur.fetchall()


def vendas_por_operador(evento_id):
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT o.nome, COUNT(*) AS qtd_vendas, COALESCE(SUM(v.valor_total), 0) AS total
               FROM vendas v
               JOIN operadores o ON o.id = v.operador_id
               JOIN sessoes_caixa s ON s.id = v.sessao_caixa_id
               WHERE v.status = 'CONCLUIDA' AND (%s::int IS NULL OR s.evento_id = %s)
               GROUP BY o.nome ORDER BY total DESC""",
            (evento_id, evento_id),
        )
        return cur.fetchall()


def vendas_por_caixa(evento_id):
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT c.nome, COUNT(*) AS qtd_vendas, COALESCE(SUM(v.valor_total), 0) AS total
               FROM vendas v
               JOIN caixas c ON c.id = v.caixa_id
               JOIN sessoes_caixa s ON s.id = v.sessao_caixa_id
               WHERE v.status = 'CONCLUIDA' AND (%s::int IS NULL OR s.evento_id = %s)
               GROUP BY c.nome ORDER BY total DESC""",
            (evento_id, evento_id),
        )
        return cur.fetchall()


def itens_excluidos_por_evento(evento_id):
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT ie.nome_produto, SUM(ie.quantidade) AS quantidade, SUM(ie.valor) AS total
               FROM itens_excluidos ie
               JOIN sessoes_caixa s ON s.id = ie.sessao_caixa_id
               WHERE (%s::int IS NULL OR s.evento_id = %s)
               GROUP BY ie.nome_produto
               ORDER BY quantidade DESC""",
            (evento_id, evento_id),
        )
        return cur.fetchall()


def listar_sessoes_abertas_por_evento(evento_id):
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT s.id AS sessao_id, c.nome AS caixa_nome, o.nome AS operador_abertura, s.data_abertura
               FROM sessoes_caixa s
               JOIN caixas c ON c.id = s.caixa_id
               LEFT JOIN operadores o ON o.id = s.operador_abertura_id
               WHERE s.evento_id = %s AND s.status = 'ABERTA'""",
            (evento_id,)
        )
        return cur.fetchall()


def fechar_evento_forcado(evento_id):
    """Fecha o evento mesmo se houver sessoes abertas: marca sessoes como FECHADA
    e depois fecha o evento. Deve ser usado com confirmacao do usuario."""
    with conectar() as conn, conn.cursor() as cur:
        # fechar sessoes abertas deste evento
        cur.execute(
            "UPDATE sessoes_caixa SET status='FECHADA', operador_fechamento_id=NULL, data_fechamento=now() WHERE evento_id=%s AND status='ABERTA'",
            (evento_id,),
        )
        # fechar o evento
        cur.execute(
            "UPDATE eventos SET status='FECHADA', data_fechamento=now() WHERE id=%s",
            (evento_id,),
        )


# ---------- Sincronizacao com o servidor central ----------


def eventos_fechados_pendentes_sync():
    """Eventos ja FECHADOS neste banco local que ainda nao foram confirmados
    no servidor central (ver db/sync.py)."""
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id, nome, rodape, data_abertura, data_fechamento
               FROM eventos
               WHERE status = 'FECHADA'
                 AND id NOT IN (SELECT evento_id FROM sync_controle)
               ORDER BY data_fechamento"""
        )
        return cur.fetchall()


def marcar_evento_sincronizado(evento_id):
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sync_controle (evento_id) VALUES (%s) ON CONFLICT (evento_id) DO NOTHING",
            (evento_id,),
        )


def dump_evento_completo(evento_id):
    """Junta tudo desse evento (sessoes, vendas, itens, trocas, excluidos) num
    dict so, ja com nomes (nao so IDs) - pra mandar pro central sem o central
    precisar conhecer os produtos/operadores/caixas deste banco local especifico."""
    with conectar() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, nome, rodape, data_abertura, data_fechamento FROM eventos WHERE id = %s", (evento_id,))
        evento = cur.fetchone()

        cur.execute(
            """SELECT s.id, c.nome AS caixa_nome, s.valor_abertura, s.data_abertura, s.data_fechamento,
                      oa.nome AS operador_abertura, of.nome AS operador_fechamento
               FROM sessoes_caixa s
               JOIN caixas c ON c.id = s.caixa_id
               LEFT JOIN operadores oa ON oa.id = s.operador_abertura_id
               LEFT JOIN operadores of ON of.id = s.operador_fechamento_id
               WHERE s.evento_id = %s ORDER BY s.data_abertura""",
            (evento_id,),
        )
        sessoes = cur.fetchall()

        cur.execute(
            """SELECT v.id, c.nome AS caixa_nome, o.nome AS operador_nome, v.numero_pedido,
                      v.forma_pagamento, v.valor_total, v.status, v.criado_em
               FROM vendas v
               JOIN sessoes_caixa s ON s.id = v.sessao_caixa_id
               JOIN caixas c ON c.id = v.caixa_id
               JOIN operadores o ON o.id = v.operador_id
               WHERE s.evento_id = %s ORDER BY v.criado_em""",
            (evento_id,),
        )
        vendas = cur.fetchall()

        cur.execute(
            """SELECT iv.venda_id, iv.nome_produto, iv.quantidade, iv.preco_unitario,
                      iv.custo_unitario, iv.subtotal
               FROM itens_venda iv
               JOIN vendas v ON v.id = iv.venda_id
               JOIN sessoes_caixa s ON s.id = v.sessao_caixa_id
               WHERE s.evento_id = %s""",
            (evento_id,),
        )
        itens_venda = cur.fetchall()

        cur.execute(
            """SELECT t.nome_saida, t.quantidade_saida, t.valor_saida, t.nome_entrada,
                      t.quantidade_entrada, t.valor_entrada, t.diferenca_valor, t.motivo, t.criado_em
               FROM trocas t
               JOIN sessoes_caixa s ON s.id = t.sessao_caixa_id
               WHERE s.evento_id = %s""",
            (evento_id,),
        )
        trocas = cur.fetchall()

        cur.execute(
            """SELECT ie.nome_produto, ie.quantidade, ie.valor, ie.motivo, ie.criado_em
               FROM itens_excluidos ie
               JOIN sessoes_caixa s ON s.id = ie.sessao_caixa_id
               WHERE s.evento_id = %s""",
            (evento_id,),
        )
        itens_excluidos = cur.fetchall()

        cur.execute(
            """SELECT f.numero_ficha, f.nome_carne, f.valor, f.cor_hex, f.nome_cliente, f.forma_pagamento,
                      f.pago, f.entregue,
                      f.status, c.nome AS caixa_nome, o.nome AS operador_nome, f.criado_em
               FROM fichas_churrasco f
               JOIN sessoes_caixa s ON s.id = f.sessao_caixa_id
               JOIN caixas c ON c.id = f.caixa_id
               JOIN operadores o ON o.id = f.operador_id
               WHERE s.evento_id = %s ORDER BY f.numero_ficha""",
            (evento_id,),
        )
        fichas_churrasco = cur.fetchall()

    return {
        "evento": evento,
        "sessoes": sessoes,
        "vendas": vendas,
        "itens_venda": itens_venda,
        "trocas": trocas,
        "itens_excluidos": itens_excluidos,
        "fichas_churrasco": fichas_churrasco,
    }


# ---------- Modulo Churrasco ----------


def listar_blocos_numeracao_churrasco(evento_id):
    """Cada bloco (faixa) configurado, junto com sua propria proxima ficha e
    se ja esta ESGOTADO - pedido explicito do usuario: cada bloco tem
    numeracao INDEPENDENTE (nao um contador unico global), o operador escolhe
    livremente qual esta vendendo agora, e um bloco esgotado (chegou no
    numero_fim) nao pode receber novas vendas. `proximo_numero` e so consulta
    (nao gasta nenhum numero - ver registrar_ficha_churrasco_do_bloco pra
    quem de fato incrementa)."""
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT f.id, f.numero_inicio, f.numero_fim, f.cor_hex,
                      COALESCE(c.ultimo_numero, f.numero_inicio - 1) + 1 AS proximo_numero
               FROM faixas_numeracao_churrasco f
               LEFT JOIN contador_ficha_churrasco_bloco c
                   ON c.evento_id = f.evento_id AND c.numero_inicio = f.numero_inicio
               WHERE f.evento_id = %s
               ORDER BY f.numero_inicio""",
            (evento_id,),
        )
        blocos = cur.fetchall()
        for bloco in blocos:
            bloco["esgotado"] = bloco["proximo_numero"] > bloco["numero_fim"]
        return blocos


def registrar_ficha_churrasco_do_bloco(sessao_id, caixa_id, operador_id, faixa_id, nome_carne, valor, nome_cliente,
                                        forma_pagamento, pago=True):
    """Emite UMA ficha do bloco escolhido (`faixa_id`) - cada bloco tem seu
    proprio contador independente (`contador_ficha_churrasco_bloco`, chaveado
    por numero_inicio - ver comentario da tabela em db/schema.sql), entao o
    operador pode alternar livremente entre blocos configurados sem nenhuma
    ordem (Verde, Azul, Laranja, Verde de novo...) sem nunca repetir numero:
    cada bloco ocupa uma faixa de numeros que nunca se sobrepoe com outra
    (validado em definir_faixas_numeracao_churrasco).

    O incremento e atomico (INSERT...ON CONFLICT...RETURNING, mesmo padrao
    ja usado no contador antigo) - concorrencia entre caixas vendendo do
    MESMO bloco ao mesmo tempo nunca gera numero duplicado. Se o bloco ja
    esgotou (numero calculado > numero_fim), a venda inteira e cancelada
    (ValueError) SEM gastar o numero - o rollback da transacao desfaz o
    incremento. A UNIQUE (evento_id, numero_ficha) em fichas_churrasco e uma
    segunda garantia (banco recusa duplicata mesmo se algo escapar da lógica
    acima) - pedido explicito do usuario pra nao depender so do contador.

    `pago=False` registra a ficha sem forma de pagamento definida ainda
    ("vendida no fio") - fica pendente até alguém finalizar o pagamento de
    verdade (ver finalizar_pagamento_ficha) via "Buscar fichas"."""
    with conectar() as conn, conn.cursor() as cur:
        cur.execute("SELECT evento_id FROM sessoes_caixa WHERE id = %s", (sessao_id,))
        evento_id = cur.fetchone()["evento_id"]

        cur.execute(
            "SELECT numero_inicio, numero_fim, cor_hex FROM faixas_numeracao_churrasco WHERE id = %s AND evento_id = %s",
            (faixa_id, evento_id),
        )
        bloco = cur.fetchone()
        if not bloco:
            raise ValueError("Esse bloco de numeração não existe mais - escolha outro na tela.")

        cur.execute(
            """INSERT INTO contador_ficha_churrasco_bloco (evento_id, numero_inicio, ultimo_numero)
               VALUES (%s, %s, %s)
               ON CONFLICT (evento_id, numero_inicio)
                   DO UPDATE SET ultimo_numero = contador_ficha_churrasco_bloco.ultimo_numero + 1
               RETURNING ultimo_numero""",
            (evento_id, bloco["numero_inicio"], bloco["numero_inicio"]),
        )
        numero = cur.fetchone()["ultimo_numero"]
        if numero > bloco["numero_fim"]:
            raise ValueError(
                f"O bloco está esgotado - todas as fichas de {bloco['numero_inicio']} até "
                f"{bloco['numero_fim']} já foram vendidas. Escolha outro bloco ou aumente o intervalo "
                f"em \"Configurar faixas de numeração\"."
            )

        forma_pagamento_gravada = forma_pagamento if pago else None
        try:
            cur.execute(
                """INSERT INTO fichas_churrasco
                   (sessao_caixa_id, caixa_id, operador_id, evento_id, nome_carne, valor, cor_hex,
                    nome_cliente, numero_ficha, forma_pagamento, pago)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (sessao_id, caixa_id, operador_id, evento_id, nome_carne, valor, bloco["cor_hex"],
                 nome_cliente, numero, forma_pagamento_gravada, pago),
            )
        except UniqueViolation:
            raise ValueError(
                f"A ficha Nº {numero} já existe nesse evento (numeração duplicada) - tente novamente."
            )
        ficha_id = cur.fetchone()["id"]
        return {
            "id": ficha_id, "numero_ficha": numero, "nome_carne": nome_carne,
            "valor": valor, "cor_hex": bloco["cor_hex"], "nome_cliente": nome_cliente, "pago": pago,
        }


def listar_faixas_numeracao_churrasco(evento_id):
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, numero_inicio, numero_fim, cor_hex FROM faixas_numeracao_churrasco "
            "WHERE evento_id = %s ORDER BY numero_inicio",
            (evento_id,),
        )
        return cur.fetchall()


def definir_faixas_numeracao_churrasco(evento_id, faixas):
    """Substitui todas as faixas do evento pela lista informada - cada item e
    (numero_inicio, numero_fim, cor_hex). A numeracao da ficha e global
    (proximo_numero_ficha_churrasco), entao duas faixas nao podem se sobrepor:
    ficaria ambiguo qual cor vale pra um numero. Valida isso em Python antes
    de gravar (mais simples que uma constraint de exclusao no Postgres pra um
    numero pequeno de faixas por evento)."""
    ordenadas = sorted(faixas, key=lambda f: f[0])
    fim_anterior = 0
    for numero_inicio, numero_fim, _ in ordenadas:
        if numero_inicio <= 0 or numero_fim < numero_inicio:
            raise ValueError(
                f"Faixa inválida ({numero_inicio} a {numero_fim}): o número final não pode ser "
                f"menor que o inicial, e o inicial deve ser maior que zero."
            )
        if numero_inicio <= fim_anterior:
            raise ValueError(
                f"Faixas sobrepostas: o número {numero_inicio} já pertence a outra faixa configurada."
            )
        fim_anterior = numero_fim

    with conectar() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM faixas_numeracao_churrasco WHERE evento_id = %s", (evento_id,))
        for numero_inicio, numero_fim, cor_hex in ordenadas:
            cur.execute(
                "INSERT INTO faixas_numeracao_churrasco (evento_id, numero_inicio, numero_fim, cor_hex) "
                "VALUES (%s, %s, %s, %s)",
                (evento_id, numero_inicio, numero_fim, cor_hex),
            )


def finalizar_pagamento_ficha(ficha_id, forma_pagamento):
    """Confirma o pagamento de uma ficha vendida 'no fio' (pago=False na
    hora da venda) - so a partir de agora ela entra no fechamento de caixa
    (resumo_sessao)."""
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE fichas_churrasco SET pago=TRUE, forma_pagamento=%s WHERE id=%s AND status='EMITIDA'",
            (forma_pagamento, ficha_id),
        )
        if cur.rowcount == 0:
            raise ValueError("Ficha não encontrada ou cancelada.")


def marcar_ficha_entregue(ficha_id, entregue: bool):
    with conectar() as conn, conn.cursor() as cur:
        cur.execute("UPDATE fichas_churrasco SET entregue=%s WHERE id=%s", (entregue, ficha_id))
        if cur.rowcount == 0:
            raise ValueError("Ficha não encontrada.")


def cancelar_ficha_churrasco(ficha_id, motivo):
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE fichas_churrasco SET status='CANCELADA', motivo_cancelamento=%s WHERE id=%s AND status='EMITIDA'",
            (motivo, ficha_id),
        )
        if cur.rowcount == 0:
            raise ValueError("Ficha não encontrada ou já cancelada.")


def fichas_churrasco_recentes(sessao_id, limite=30):
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id, numero_ficha, nome_carne, valor, nome_cliente, forma_pagamento, pago, entregue,
                      status, criado_em
               FROM fichas_churrasco WHERE sessao_caixa_id = %s
               ORDER BY criado_em DESC LIMIT %s""",
            (sessao_id, limite),
        )
        return cur.fetchall()


def buscar_fichas_churrasco(evento_id, nome_cliente=None, numero_ficha=None, cor_hex=None, limite=300):
    """Consulta completa das fichas emitidas no evento - por nome do cliente
    (busca parcial, sem diferenciar maiusculas/minusculas), numero exato da
    ficha, e/ou churrasqueira (cor). Sem nenhum filtro, traz as mais recentes
    primeiro (limitado a `limite`) - usado na tela "Buscar fichas" do modulo."""
    condicoes = ["s.evento_id = %s"]
    params = [evento_id]
    if nome_cliente:
        condicoes.append("f.nome_cliente ILIKE %s")
        params.append(f"%{nome_cliente}%")
    if numero_ficha is not None:
        condicoes.append("f.numero_ficha = %s")
        params.append(numero_ficha)
    if cor_hex:
        condicoes.append("f.cor_hex = %s")
        params.append(cor_hex)
    params.append(limite)

    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            f"""SELECT f.id, f.numero_ficha, f.nome_carne, f.nome_cliente, f.valor, f.cor_hex, f.forma_pagamento,
                       f.pago, f.entregue,
                       f.status, f.criado_em, o.nome AS operador_nome, c.nome AS caixa_nome
                FROM fichas_churrasco f
                JOIN sessoes_caixa s ON s.id = f.sessao_caixa_id
                JOIN operadores o ON o.id = f.operador_id
                JOIN caixas c ON c.id = f.caixa_id
                WHERE {' AND '.join(condicoes)}
                ORDER BY f.numero_ficha DESC
                LIMIT %s""",
            params,
        )
        return cur.fetchall()


def resumo_churrasco_por_cor(evento_id):
    """Totais em tempo real por churrasqueira (cor) - pra quem esta na grelha
    saber quanto ja foi vendido/quanto ainda precisa preparar. evento_id=None
    soma todos os eventos (usado em Relatorios > "Todos os eventos")."""
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT f.cor_hex, COUNT(*) AS qtd, COALESCE(SUM(f.valor), 0) AS total
               FROM fichas_churrasco f
               JOIN sessoes_caixa s ON s.id = f.sessao_caixa_id
               WHERE f.status = 'EMITIDA' AND (%s::int IS NULL OR s.evento_id = %s)
               GROUP BY f.cor_hex ORDER BY qtd DESC""",
            (evento_id, evento_id),
        )
        return cur.fetchall()


def resumo_churrasco_por_carne(evento_id):
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT f.nome_carne, COUNT(*) AS qtd, COALESCE(SUM(f.valor), 0) AS total
               FROM fichas_churrasco f
               JOIN sessoes_caixa s ON s.id = f.sessao_caixa_id
               WHERE f.status = 'EMITIDA' AND (%s::int IS NULL OR s.evento_id = %s)
               GROUP BY f.nome_carne ORDER BY qtd DESC""",
            (evento_id, evento_id),
        )
        return cur.fetchall()
