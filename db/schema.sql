-- Schema do SistemaChurrasco
-- Banco central em PostgreSQL, rodando no PC "servidor". Todos os terminais
-- conectam direto aqui via rede local (ver README para configuracao de rede).

CREATE TYPE forma_pagamento AS ENUM ('DINHEIRO', 'CARTAO_CREDITO', 'CARTAO_DEBITO', 'PIX', 'CONSUMACAO');
CREATE TYPE tipo_movimento_caixa AS ENUM ('SANGRIA', 'REFORCO');
CREATE TYPE status_venda AS ENUM ('CONCLUIDA', 'CANCELADA');
CREATE TYPE status_sessao AS ENUM ('ABERTA', 'FECHADA');

CREATE TABLE operadores (
    id SERIAL PRIMARY KEY,
    nome TEXT NOT NULL,
    pin TEXT NOT NULL,
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE caixas (
    id SERIAL PRIMARY KEY,
    nome TEXT NOT NULL UNIQUE,
    ativo BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE categorias_produto (
    id SERIAL PRIMARY KEY,
    nome TEXT NOT NULL UNIQUE,
    ordem INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE produtos (
    id SERIAL PRIMARY KEY,
    categoria_id INTEGER REFERENCES categorias_produto(id),
    nome TEXT NOT NULL,
    preco NUMERIC(10, 2) NOT NULL CHECK (preco >= 0),
    custo NUMERIC(10, 2) NOT NULL DEFAULT 0 CHECK (custo >= 0),
    -- cor do botao na tela de venda (ex: '#E07A3E'), para identificacao visual rapida
    cor_hex TEXT NOT NULL DEFAULT '#E07A3E',
    -- controle de estoque e opcional: fica desligado (FALSE) para produtos "ilimitados"
    -- como fichas de bebida, e ligado para itens com quantidade finita (ex: galeto).
    estoque_controlado BOOLEAN NOT NULL DEFAULT FALSE,
    estoque_atual INTEGER,
    eh_combo BOOLEAN NOT NULL DEFAULT FALSE,
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    -- oculto: tira da grade de venda sem desativar o cadastro (ex: acabou por hoje)
    oculto BOOLEAN NOT NULL DEFAULT FALSE,
    ordem INTEGER NOT NULL DEFAULT 0,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Composicao de produtos "combo" (kits): um combo aponta para N produtos
-- componentes com suas quantidades (ex: Combo Churrasco = 1 Galeto + 1 Farofa + 1 Refri).
CREATE TABLE combo_itens (
    id SERIAL PRIMARY KEY,
    produto_combo_id INTEGER NOT NULL REFERENCES produtos(id) ON DELETE CASCADE,
    produto_componente_id INTEGER NOT NULL REFERENCES produtos(id),
    quantidade INTEGER NOT NULL CHECK (quantidade > 0)
);

-- Evento (a festa). Cada festa e um evento; ao fechar, os dados ficam
-- guardados pra sempre no historico e um evento novo pode ser aberto depois.
CREATE TABLE eventos (
    id SERIAL PRIMARY KEY,
    nome TEXT NOT NULL,
    rodape TEXT NOT NULL DEFAULT '',
    status status_sessao NOT NULL DEFAULT 'ABERTA',
    data_abertura TIMESTAMPTZ NOT NULL DEFAULT now(),
    data_fechamento TIMESTAMPTZ
);

-- So pode existir um evento aberto por vez em todo o sistema.
CREATE UNIQUE INDEX um_evento_aberto ON eventos (status) WHERE status = 'ABERTA';

CREATE TABLE sessoes_caixa (
    id SERIAL PRIMARY KEY,
    evento_id INTEGER NOT NULL REFERENCES eventos(id),
    caixa_id INTEGER NOT NULL REFERENCES caixas(id),
    operador_abertura_id INTEGER NOT NULL REFERENCES operadores(id),
    valor_abertura NUMERIC(10, 2) NOT NULL DEFAULT 0,
    data_abertura TIMESTAMPTZ NOT NULL DEFAULT now(),
    operador_fechamento_id INTEGER REFERENCES operadores(id),
    data_fechamento TIMESTAMPTZ,
    status status_sessao NOT NULL DEFAULT 'ABERTA'
);

-- Garante que um caixa nunca tenha duas sessoes abertas ao mesmo tempo.
CREATE UNIQUE INDEX uma_sessao_aberta_por_caixa ON sessoes_caixa (caixa_id) WHERE status = 'ABERTA';

CREATE TABLE movimentos_caixa (
    id SERIAL PRIMARY KEY,
    sessao_caixa_id INTEGER NOT NULL REFERENCES sessoes_caixa(id),
    tipo tipo_movimento_caixa NOT NULL,
    valor NUMERIC(10, 2) NOT NULL CHECK (valor > 0),
    motivo TEXT,
    operador_id INTEGER NOT NULL REFERENCES operadores(id),
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE vendas (
    id SERIAL PRIMARY KEY,
    sessao_caixa_id INTEGER NOT NULL REFERENCES sessoes_caixa(id),
    caixa_id INTEGER NOT NULL REFERENCES caixas(id),
    operador_id INTEGER NOT NULL REFERENCES operadores(id),
    numero_pedido INTEGER NOT NULL,
    forma_pagamento forma_pagamento NOT NULL,
    valor_total NUMERIC(10, 2) NOT NULL,
    status status_venda NOT NULL DEFAULT 'CONCLUIDA',
    motivo_cancelamento TEXT,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_vendas_sessao ON vendas (sessao_caixa_id);
CREATE INDEX idx_vendas_criado_em ON vendas (criado_em);

CREATE TABLE itens_venda (
    id SERIAL PRIMARY KEY,
    venda_id INTEGER NOT NULL REFERENCES vendas(id) ON DELETE CASCADE,
    produto_id INTEGER NOT NULL REFERENCES produtos(id),
    -- nome/preco/custo sao "congelados" no momento da venda: preservam o
    -- historico correto mesmo se o produto for renomeado/reprecificado depois.
    nome_produto TEXT NOT NULL,
    quantidade INTEGER NOT NULL CHECK (quantidade > 0),
    preco_unitario NUMERIC(10, 2) NOT NULL,
    custo_unitario NUMERIC(10, 2) NOT NULL DEFAULT 0,
    subtotal NUMERIC(10, 2) NOT NULL
);

CREATE INDEX idx_itens_venda_produto ON itens_venda (produto_id);

-- Log de itens removidos do carrinho ANTES de finalizar o pedido (nao e a mesma
-- coisa que cancelar uma venda ja concluida). Existe para auditoria/controle
-- contra fraude: mostra no fechamento quantos itens foram tirados e o valor.
CREATE TABLE itens_excluidos (
    id SERIAL PRIMARY KEY,
    sessao_caixa_id INTEGER NOT NULL REFERENCES sessoes_caixa(id),
    caixa_id INTEGER NOT NULL REFERENCES caixas(id),
    operador_id INTEGER NOT NULL REFERENCES operadores(id),
    produto_id INTEGER REFERENCES produtos(id),
    nome_produto TEXT NOT NULL,
    quantidade INTEGER NOT NULL CHECK (quantidade > 0),
    valor NUMERIC(10, 2) NOT NULL,
    motivo TEXT,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_itens_excluidos_sessao ON itens_excluidos (sessao_caixa_id);

-- Trocas: cliente ja pagou e devolve um item (com ou sem levar outro no lugar).
-- produto_entrada pode ser nulo (so devolucao, sem pegar outro produto).
-- diferenca_valor = valor_entrada - valor_saida (negativo = volta dinheiro pro
-- cliente, positivo = cliente paga a diferenca). Assume pagamento em dinheiro.
CREATE TABLE trocas (
    id SERIAL PRIMARY KEY,
    sessao_caixa_id INTEGER NOT NULL REFERENCES sessoes_caixa(id),
    caixa_id INTEGER NOT NULL REFERENCES caixas(id),
    operador_id INTEGER NOT NULL REFERENCES operadores(id),
    produto_saida_id INTEGER REFERENCES produtos(id),
    nome_saida TEXT NOT NULL,
    quantidade_saida INTEGER NOT NULL CHECK (quantidade_saida > 0),
    valor_saida NUMERIC(10, 2) NOT NULL,
    produto_entrada_id INTEGER REFERENCES produtos(id),
    nome_entrada TEXT,
    quantidade_entrada INTEGER,
    valor_entrada NUMERIC(10, 2) NOT NULL DEFAULT 0,
    diferenca_valor NUMERIC(10, 2) NOT NULL,
    motivo TEXT,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_trocas_sessao ON trocas (sessao_caixa_id);

-- Contador atomico de numero de pedido, reiniciando por dia (independente de qual
-- caixa/terminal esta vendendo, evitando corrida entre terminais concorrentes).
CREATE TABLE contador_pedido_diario (
    dia DATE PRIMARY KEY,
    ultimo_numero INTEGER NOT NULL DEFAULT 0
);

CREATE OR REPLACE FUNCTION proximo_numero_pedido() RETURNS INTEGER AS $$
DECLARE
    n INTEGER;
BEGIN
    INSERT INTO contador_pedido_diario (dia, ultimo_numero)
    VALUES (CURRENT_DATE, 1)
    ON CONFLICT (dia) DO UPDATE SET ultimo_numero = contador_pedido_diario.ultimo_numero + 1
    RETURNING ultimo_numero INTO n;
    RETURN n;
END;
$$ LANGUAGE plpgsql;

-- Operador padrao para o primeiro acesso (PIN deve ser trocado em Configuracoes).
INSERT INTO operadores (nome, pin) VALUES ('Administrador', '0000') ON CONFLICT DO NOTHING;

-- Marca quais eventos (deste banco LOCAL) ja foram enviados com sucesso pro
-- servidor central (ver db/sync.py). Um evento so entra aqui depois de FECHADO
-- e confirmado no central - antes disso o processo de sync fica tentando de novo.
CREATE TABLE sync_controle (
    evento_id INTEGER PRIMARY KEY REFERENCES eventos(id),
    sincronizado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);
