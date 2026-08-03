"""Camada de acesso a dados. Cada funcao abre/fecha sua propria conexao
(ver db.connection) e representa uma operacao de negocio completa.
"""

from decimal import Decimal

from db.connection import conectar
from pathlib import Path
import sys

# ---------- Operadores ----------


def autenticar_operador(operador_id, pin):
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, nome FROM operadores WHERE id = %s AND pin = %s AND ativo",
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


def listar_operadores(somente_ativos=True):
    with conectar() as conn, conn.cursor() as cur:
        if somente_ativos:
            cur.execute("SELECT id, nome FROM operadores WHERE ativo ORDER BY nome")
        else:
            cur.execute("SELECT id, nome, ativo FROM operadores ORDER BY nome")
        return cur.fetchall()


def criar_operador(nome, pin):
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO operadores (nome, pin) VALUES (%s, %s) RETURNING id",
            (nome, pin),
        )
        return cur.fetchone()["id"]


def definir_ativo_operador(operador_id, ativo):
    with conectar() as conn, conn.cursor() as cur:
        cur.execute("UPDATE operadores SET ativo = %s WHERE id = %s", (ativo, operador_id))


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
                   p.categoria_id, c.nome AS categoria_nome
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
        sql += " ORDER BY c.ordem NULLS LAST, p.ordem, p.nome"
        cur.execute(sql)
        return cur.fetchall()


def criar_produto(nome, preco, categoria_id=None, custo=0, cor_hex="#E07A3E",
                   estoque_controlado=False, estoque_atual=None, eh_combo=False, ordem=0):
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO produtos
               (nome, preco, categoria_id, custo, cor_hex, estoque_controlado,
                estoque_atual, eh_combo, ordem)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (nome, preco, categoria_id, custo, cor_hex, estoque_controlado,
             estoque_atual, eh_combo, ordem),
        )
        return cur.fetchone()["id"]


def atualizar_produto(produto_id, nome, preco, categoria_id=None, custo=0, cor_hex="#E07A3E",
                       estoque_controlado=False, estoque_atual=None, eh_combo=False,
                       ativo=True, oculto=False):
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE produtos SET nome=%s, preco=%s, categoria_id=%s, custo=%s, cor_hex=%s,
               estoque_controlado=%s, estoque_atual=%s, eh_combo=%s, ativo=%s, oculto=%s
               WHERE id=%s""",
            (nome, preco, categoria_id, custo, cor_hex, estoque_controlado,
             estoque_atual, eh_combo, ativo, oculto, produto_id),
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


def registrar_venda(sessao_id, caixa_id, operador_id, itens, forma_pagamento):
    """itens: lista de dicts {produto_id, nome, preco, quantidade, custo (opcional)}.
    Consome estoque dos produtos com estoque_controlado=TRUE."""
    with conectar() as conn, conn.cursor() as cur:
        cur.execute("SELECT proximo_numero_pedido() AS n")
        numero_pedido = cur.fetchone()["n"]

        valor_total = sum(Decimal(str(i["preco"])) * i["quantidade"] for i in itens)
        cur.execute(
            """INSERT INTO vendas (sessao_caixa_id, caixa_id, operador_id, numero_pedido,
                                    forma_pagamento, valor_total)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
            (sessao_id, caixa_id, operador_id, numero_pedido, forma_pagamento, valor_total),
        )
        venda_id = cur.fetchone()["id"]

        for item in itens:
            subtotal = Decimal(str(item["preco"])) * item["quantidade"]
            cur.execute(
                """INSERT INTO itens_venda
                   (venda_id, produto_id, nome_produto, quantidade, preco_unitario, custo_unitario, subtotal)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (venda_id, item["produto_id"], item["nome"], item["quantidade"],
                 item["preco"], item.get("custo", 0), subtotal),
            )
            cur.execute(
                """UPDATE produtos SET estoque_atual = estoque_atual - %s
                   WHERE id = %s AND estoque_controlado""",
                (item["quantidade"], item["produto_id"]),
            )

    return {"venda_id": venda_id, "numero_pedido": numero_pedido, "valor_total": valor_total}


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
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE vendas SET status='CANCELADA', motivo_cancelamento=%s WHERE id=%s",
            (motivo, venda_id),
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
            """SELECT forma_pagamento, COALESCE(SUM(valor_total), 0) AS total
               FROM vendas WHERE sessao_caixa_id=%s AND status='CONCLUIDA'
               GROUP BY forma_pagamento""",
            (sessao_id,),
        )
        por_forma = {r["forma_pagamento"]: r["total"] for r in cur.fetchall()}

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
