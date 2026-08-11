-- Schema do SistemaChurrasco
-- Banco central em PostgreSQL, rodando no PC "servidor". Todos os terminais
-- conectam direto aqui via rede local (ver README para configuracao de rede).

-- 'VARIAS' e usado quando o pagamento de uma venda foi dividido em mais de
-- uma forma (ex: parte dinheiro, parte cartao) - o detalhe de quanto foi
-- pago em cada forma fica em pagamentos_venda, nunca nessa coluna.
CREATE TYPE forma_pagamento AS ENUM ('DINHEIRO', 'CARTAO_CREDITO', 'CARTAO_DEBITO', 'PIX', 'CONSUMACAO', 'VARIAS');
CREATE TYPE tipo_movimento_caixa AS ENUM ('SANGRIA', 'REFORCO');
CREATE TYPE status_venda AS ENUM ('CONCLUIDA', 'CANCELADA');
CREATE TYPE status_sessao AS ENUM ('ABERTA', 'FECHADA');

CREATE TABLE operadores (
    id SERIAL PRIMARY KEY,
    nome TEXT NOT NULL,
    pin TEXT NOT NULL,
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    -- operador administrador ve as abas de Evento e Operadores em
    -- Configuracoes; os demais so veem Conexao/impressora, Produtos e
    -- Vender pelo celular.
    administrador BOOLEAN NOT NULL DEFAULT FALSE,
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
    -- se marcado, a ficha impressa deste produto nao mostra o valor (ex:
    -- cortesia/brinde) - vale tambem quando este produto e componente de
    -- um combo (a ficha daquele componente especifico sai sem valor).
    ocultar_valor_impressao BOOLEAN NOT NULL DEFAULT FALSE,
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

-- Detalhe de quanto foi pago em cada forma, pra permitir dividir o pagamento
-- de uma venda (ex: parte em dinheiro, parte no cartao). Toda venda tem pelo
-- menos 1 linha aqui - mesmo pagamento em uma unica forma (a mais comum).
-- SUM(valor) por venda_id sempre bate com vendas.valor_total.
CREATE TABLE pagamentos_venda (
    id SERIAL PRIMARY KEY,
    venda_id INTEGER NOT NULL REFERENCES vendas(id) ON DELETE CASCADE,
    forma_pagamento forma_pagamento NOT NULL,
    valor NUMERIC(10, 2) NOT NULL CHECK (valor > 0)
);

CREATE INDEX idx_pagamentos_venda_venda ON pagamentos_venda (venda_id);

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

-- Contador atomico de numero de pedido, reiniciando por EVENTO (nao por dia -
-- um evento que passa da meia-noite nao pode ter dois "PED: 1" diferentes).
-- Continua atomico entre caixas/terminais concorrentes do mesmo evento.
CREATE TABLE contador_pedido_evento (
    evento_id INTEGER PRIMARY KEY REFERENCES eventos(id),
    ultimo_numero INTEGER NOT NULL DEFAULT 0
);

CREATE OR REPLACE FUNCTION proximo_numero_pedido(p_evento_id INTEGER) RETURNS INTEGER AS $$
DECLARE
    n INTEGER;
BEGIN
    INSERT INTO contador_pedido_evento (evento_id, ultimo_numero)
    VALUES (p_evento_id, 1)
    ON CONFLICT (evento_id) DO UPDATE SET ultimo_numero = contador_pedido_evento.ultimo_numero + 1
    RETURNING ultimo_numero INTO n;
    RETURN n;
END;
$$ LANGUAGE plpgsql;

-- Operador padrao para o primeiro acesso (PIN deve ser trocado em Configuracoes).
INSERT INTO operadores (nome, pin, administrador) VALUES ('Administrador', '1411', TRUE) ON CONFLICT DO NOTHING;

-- Catalogo padrao (churrasco tipico) - todo evento novo ja nasce com isso.
-- Pode ser editado, desativado ou ter novos itens cadastrados em
-- Configuracoes > Produtos, sem afetar outros eventos.
INSERT INTO categorias_produto (nome, ordem) VALUES
    ('Bebidas', 1),
    ('Comidas', 2)
ON CONFLICT (nome) DO NOTHING;

INSERT INTO produtos (nome, preco, categoria_id, cor_hex, ordem) VALUES
    ('Cerveja', 8.00, (SELECT id FROM categorias_produto WHERE nome = 'Bebidas'), '#D9A82E', 1),
    ('Refrigerante', 7.00, (SELECT id FROM categorias_produto WHERE nome = 'Bebidas'), '#D1483B', 2),
    ('Água', 5.00, (SELECT id FROM categorias_produto WHERE nome = 'Bebidas'), '#3E7CB1', 3),
    ('Água de Coco', 7.00, (SELECT id FROM categorias_produto WHERE nome = 'Bebidas'), '#4F9D63', 4),
    ('Suco', 7.00, (SELECT id FROM categorias_produto WHERE nome = 'Bebidas'), '#8B5FBF', 5),
    ('Espetinho', 12.00, (SELECT id FROM categorias_produto WHERE nome = 'Comidas'), '#8A5A3C', 6),
    ('Galeto', 25.00, (SELECT id FROM categorias_produto WHERE nome = 'Comidas'), '#E2662D', 7),
    ('Costela', 30.00, (SELECT id FROM categorias_produto WHERE nome = 'Comidas'), '#8A5A3C', 8),
    ('Linguiça', 15.00, (SELECT id FROM categorias_produto WHERE nome = 'Comidas'), '#D1483B', 9),
    ('Pão de Alho', 8.00, (SELECT id FROM categorias_produto WHERE nome = 'Comidas'), '#D9A82E', 10),
    ('Porção de Fritas', 15.00, (SELECT id FROM categorias_produto WHERE nome = 'Comidas'), '#6B6259', 11);

-- ---------- Modulo Churrasco ----------
-- Venda por ficha nomeada (uma unidade por vez, com nome do cliente) -
-- substitui o bloco de papel fisico com via+canhoto: so a via do cliente e
-- impressa, o proprio banco guarda o controle que antes ficava no canhoto.
-- Vive dentro do MESMO evento/caixa/sessao/operador do resto do sistema -
-- fecha e sincroniza junto com o evento, sem fluxo de abertura/fechamento
-- proprio.

-- Blocos de numeracao (faixas) configurados por evento (nao fixo entre
-- eventos - cada evento redefine os seus). CADA BLOCO TEM SUA PROPRIA
-- NUMERACAO INDEPENDENTE (pedido explicito do usuario, 2026-08-11 - substitui
-- o modelo anterior de contador unico global) - o operador escolhe
-- livremente qual bloco esta vendendo a qualquer momento (pode alternar sem
-- ordem nenhuma: Verde, Azul, Laranja, Verde de novo...), e cada bloco lembra
-- seu proprio progresso. Um bloco fica ESGOTADO quando sua ultima ficha
-- (numero_fim) e vendida - nenhuma venda alem disso e permitida nesse bloco.
CREATE TABLE faixas_numeracao_churrasco (
    id SERIAL PRIMARY KEY,
    evento_id INTEGER NOT NULL REFERENCES eventos(id),
    numero_inicio INTEGER NOT NULL CHECK (numero_inicio > 0),
    numero_fim INTEGER NOT NULL CHECK (numero_fim >= numero_inicio),
    cor_hex TEXT NOT NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_faixas_numeracao_churrasco_evento ON faixas_numeracao_churrasco (evento_id);

-- Progresso de cada bloco - chaveado por (evento_id, numero_inicio), NAO por
-- faixas_numeracao_churrasco.id: salvar a configuracao de blocos (ver
-- db.repository.definir_faixas_numeracao_churrasco) apaga e recria todas as
-- linhas de faixas_numeracao_churrasco (ids novos toda vez) - se o contador
-- referenciasse esse id, editar a configuracao destruiria o progresso de
-- todos os blocos via ON DELETE CASCADE. numero_inicio e estavel (identifica
-- "qual bloco e esse" mesmo que o numero_fim ou a cor sejam ajustados depois)
-- porque faixas nunca se sobrepoem dentro do mesmo evento.
CREATE TABLE contador_ficha_churrasco_bloco (
    evento_id INTEGER NOT NULL REFERENCES eventos(id),
    numero_inicio INTEGER NOT NULL,
    ultimo_numero INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (evento_id, numero_inicio)
);

CREATE TYPE status_ficha_churrasco AS ENUM ('EMITIDA', 'CANCELADA');

CREATE TABLE fichas_churrasco (
    id SERIAL PRIMARY KEY,
    sessao_caixa_id INTEGER NOT NULL REFERENCES sessoes_caixa(id),
    caixa_id INTEGER NOT NULL REFERENCES caixas(id),
    operador_id INTEGER NOT NULL REFERENCES operadores(id),
    -- evento_id "duplicado" aqui (alem de vir via sessao_caixa_id) de proposito -
    -- e o que permite a UNIQUE (evento_id, numero_ficha) abaixo: garantia REAL
    -- de banco contra ficha duplicada (pedido explicito do usuario - "nao
    -- quero depender so de um contador visual"), sem precisar de constraint
    -- cruzando tabelas via join.
    evento_id INTEGER NOT NULL REFERENCES eventos(id),
    -- nao ha cadastro/catalogo de carnes - o operador digita nome e valor na
    -- hora de emitir a ficha (pedido explicito do usuario), entao ja nasce
    -- "congelado" aqui, sem nenhuma tabela catalogo por tras.
    nome_carne TEXT NOT NULL,
    valor NUMERIC(10, 2) NOT NULL,
    -- cor do BLOCO escolhido pelo operador na hora da venda - "congelada"
    -- aqui pelo mesmo motivo de nome_carne (historico correto mesmo se o
    -- bloco for reconfigurado depois).
    cor_hex TEXT NOT NULL,
    nome_cliente TEXT NOT NULL,
    numero_ficha INTEGER NOT NULL,
    -- NULL enquanto pago=false (ainda nao foi decidido/cobrado) - so entra no
    -- calculo de fechamento de caixa (resumo_sessao) quando pago=true, senao
    -- contaria dinheiro que ainda nao entrou de verdade no caixa.
    forma_pagamento forma_pagamento,
    -- pago=false = venda registrada mas ainda sem pagamento definido ("fio"
    -- do churrasco) - aparece com aviso em "Buscar fichas" até alguém
    -- finalizar o pagamento de verdade. entregue = controle separado de
    -- entrega da carne (independente de pago - pode entregar sem ter
    -- cobrado, ou ter cobrado e ainda nao entregue).
    pago BOOLEAN NOT NULL DEFAULT TRUE,
    entregue BOOLEAN NOT NULL DEFAULT FALSE,
    status status_ficha_churrasco NOT NULL DEFAULT 'EMITIDA',
    motivo_cancelamento TEXT,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (evento_id, numero_ficha)
);

CREATE INDEX idx_fichas_churrasco_sessao ON fichas_churrasco (sessao_caixa_id);
CREATE INDEX idx_fichas_churrasco_cor ON fichas_churrasco (cor_hex);

-- Marca quais eventos (deste banco LOCAL) ja foram enviados com sucesso pro
-- servidor central (ver db/sync.py). Um evento so entra aqui depois de FECHADO
-- e confirmado no central - antes disso o processo de sync fica tentando de novo.
CREATE TABLE sync_controle (
    evento_id INTEGER PRIMARY KEY REFERENCES eventos(id),
    sincronizado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);
