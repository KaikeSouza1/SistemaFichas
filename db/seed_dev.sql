-- Dados de exemplo so para desenvolvimento/teste visual, nao usar em producao.
INSERT INTO categorias_produto (nome, ordem) VALUES
    ('Almoço', 1), ('Bebidas', 2), ('Doces', 3)
ON CONFLICT (nome) DO NOTHING;

INSERT INTO produtos (nome, preco, custo, categoria_id, cor_hex, ordem)
SELECT 'Almoço Adulto', 35.00, 18.00, c.id, '#E2662D', 1 FROM categorias_produto c WHERE c.nome = 'Almoço'
UNION ALL
SELECT 'Almoço Infantil', 20.00, 10.00, c.id, '#F08A4B', 2 FROM categorias_produto c WHERE c.nome = 'Almoço'
UNION ALL
SELECT 'Galeto Unidade', 8.00, 4.00, c.id, '#B84F1F', 3 FROM categorias_produto c WHERE c.nome = 'Almoço'
UNION ALL
SELECT 'Farofa', 10.00, 3.00, c.id, '#8A5A3C', 4 FROM categorias_produto c WHERE c.nome = 'Almoço'
UNION ALL
SELECT 'Cerveja', 6.00, 3.00, c.id, '#D9A82E', 1 FROM categorias_produto c WHERE c.nome = 'Bebidas'
UNION ALL
SELECT 'Refrigerante', 6.00, 3.00, c.id, '#3E7CB1', 2 FROM categorias_produto c WHERE c.nome = 'Bebidas'
UNION ALL
SELECT 'Água', 4.00, 1.50, c.id, '#6B6259', 3 FROM categorias_produto c WHERE c.nome = 'Bebidas'
UNION ALL
SELECT 'Sobremesa', 6.00, 2.00, c.id, '#8B5FBF', 1 FROM categorias_produto c WHERE c.nome = 'Doces'
UNION ALL
SELECT 'Pastel', 6.00, 2.50, c.id, '#4F9D63', 2 FROM categorias_produto c WHERE c.nome = 'Doces';
