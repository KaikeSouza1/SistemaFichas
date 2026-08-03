"""Monta os bytes ESC/POS das fichas impressas: uma ficha por UNIDADE
comprada (6 cervejas = 6 fichas separadas, cada uma cortada individualmente,
pra poder entregar uma por vez em cada barraca) e o fechamento de caixa.

Todo texto passa por `_sem_acentos` antes de ir para a impressora: sem saber
ainda qual code page a Elgin i9 vai aceitar em campo, preferimos garantir
ASCII puro sempre. Revisitar depois de testar em impressora real.
"""

import unicodedata
from decimal import Decimal

from escpos.printer import Dummy
from PIL import Image, ImageDraw, ImageFont

LARGURA_COLUNAS = 42  # ajustar em Configurações se a impressora usar outra fonte/largura
LARGURA_PONTOS = 384  # largura da imagem do nome do produto, em pontos (px).
                      # 384 e seguro pra 58mm; se a Elgin usar 80mm, subir p/ 576.

# Fonte usada só pra desenhar o nome do produto como imagem (a impressora não
# tem essa fonte "embutida"). GS v 0 (bitImageRaster, o padrão do
# python-escpos) não funcionou nessa impressora - por isso impl="bitImageColumn"
# abaixo, que usa o comando ESC * bem mais antigo/universal.
_FONTES_CANDIDATAS = [
    r"C:\Windows\Fonts\georgiab.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\ariblk.ttf",
]


def _carregar_fonte(tamanho: int) -> ImageFont.FreeTypeFont:
    for caminho in _FONTES_CANDIDATAS:
        try:
            return ImageFont.truetype(caminho, tamanho)
        except OSError:
            continue
    return ImageFont.load_default()


def _imagem_nome_produto(nome: str, largura_px: int = LARGURA_PONTOS) -> Image.Image:
    """Desenha o nome do produto centralizado, em negrito, no maior tamanho
    que couber na largura do papel."""
    nome = _sem_acentos(nome.upper())
    medidor = ImageDraw.Draw(Image.new("L", (1, 1)))

    tamanho_fonte = 120
    margem = 16
    fonte = _carregar_fonte(tamanho_fonte)
    while tamanho_fonte > 48:
        fonte = _carregar_fonte(tamanho_fonte)
        caixa = medidor.textbbox((0, 0), nome, font=fonte)
        if caixa[2] - caixa[0] <= largura_px - margem:
            break
        tamanho_fonte -= 4

    caixa = medidor.textbbox((0, 0), nome, font=fonte)
    largura_texto, altura_texto = caixa[2] - caixa[0], caixa[3] - caixa[1]
    altura_img = altura_texto + 28
    # Modo coluna (ESC*) imprime em bandas de 24px; se a altura nao for
    # multiplo de 24 a ultima banda fica truncada e "corta" o texto no meio.
    altura_img = ((altura_img + 23) // 24) * 24
    imagem = Image.new("L", (largura_px, altura_img), color=255)
    desenho = ImageDraw.Draw(imagem)
    x = (largura_px - largura_texto) // 2 - caixa[0]
    y = (altura_img - altura_texto) // 2 - caixa[1]
    desenho.text((x, y), nome, font=fonte, fill=0)
    return imagem


def _sem_acentos(texto: str) -> str:
    normalizado = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in normalizado if not unicodedata.combining(c))


def _moeda(valor) -> str:
    valor = Decimal(str(valor))
    texto = f"{valor:,.2f}"
    return texto.replace(",", "@").replace(".", ",").replace("@", ".")


def _duas_colunas(esquerda: str, direita: str) -> str:
    espacos = max(1, LARGURA_COLUNAS - len(esquerda) - len(direita))
    return f"{esquerda}{' ' * espacos}{direita}"


def _separador() -> str:
    return "-" * LARGURA_COLUNAS


def _linha(p, texto: str = "") -> None:
    p.text(_sem_acentos(texto) + "\n")


def _ficha_de_um_item(p, nome_evento, numero_pedido, data_hora, nome_item, preco, operador_nome, caixa_nome):
    # Cabecalho compacto, alinhado a esquerda (como no modelo de referencia:
    # data e numero do pedido na mesma linha, sem espacos em branco extras).
    p.set(align="left", bold=True)
    _linha(p, nome_evento.upper()[:LARGURA_COLUNAS])
    p.set(align="left", bold=False)
    _linha(p, _duas_colunas(data_hora, f"PED: {numero_pedido}"))
    _linha(p, _separador())

    # Nome do produto: o elemento dominante da ficha, desenhado como imagem
    # (fonte grossa que a impressora nao tem embutida). impl="bitImageColumn"
    # usa o comando ESC * (antigo/universal) em vez do GS v 0 padrao, que
    # essa impressora nao reconheceu (testado em hardware real - saiu lixo).
    p.set(align="center")
    p.image(_imagem_nome_produto(nome_item), impl="bitImageColumn")
    _linha(p)

    # Preco, operador e rodape: alinhados a esquerda, compactos, sem linhas
    # em branco entre eles (igual ao modelo de referencia).
    p.set(align="left", bold=True)
    _linha(p, f"R$ {_moeda(preco)}")
    p.set(bold=False)
    _linha(p, f"OPER: {operador_nome} - CAIXA: {caixa_nome}")
    p.cut()


def fichas_venda_bytes(
    nome_evento: str,
    numero_pedido: int,
    data_hora: str,
    itens: list[dict],
    operador_nome: str,
    caixa_nome: str,
) -> bytes:
    """itens: lista de {"nome": str, "quantidade": int, "preco": Decimal}.
    Gera uma ficha separada (com corte) para CADA unidade de CADA item —
    comprar 6 cervejas imprime 6 fichas individuais de cerveja."""
    p = Dummy()
    p.hw("INIT")
    for item in itens:
        for _ in range(item["quantidade"]):
            _ficha_de_um_item(
                p, nome_evento, numero_pedido, data_hora,
                item["nome"], item["preco"], operador_nome, caixa_nome,
            )
    return p.output


def fechamento_caixa_bytes(
    nome_evento: str,
    caixa_nome: str,
    operador_nome: str,
    data_hora: str,
    resumo: dict,
    rodape: str = "",
) -> bytes:
    p = Dummy()
    p.hw("INIT")

    p.set(align="center", bold=True)
    _linha(p, "FECHAMENTO DE CAIXA")
    p.set(align="left", bold=False)
    _linha(p)
    _linha(p, _duas_colunas(f"CAIXA: {caixa_nome}", f"DATA: {data_hora}"))
    _linha(p, f"USUARIO: {operador_nome}")
    _linha(p)

    _linha(p, _duas_colunas(f"(+) ABERTURA: {_moeda(resumo['abertura'])}", f"(+) ADICIONAL: {_moeda(resumo['adicional'])}"))
    _linha(p, f"(+) DINHEIRO: {_moeda(resumo['dinheiro_vendas'])}")
    _linha(p, f"(-) SANGRIA: {_moeda(resumo['sangria'])}")
    _linha(p, _separador())
    p.set(bold=True)
    _linha(p, f"(=) TOTAL DINHEIRO: {_moeda(resumo['total_dinheiro'])}")
    p.set(bold=False)
    _linha(p, f"CARTAO CREDITO: {_moeda(resumo['cartao_credito'])}")
    _linha(p, f"CARTAO DEBITO: {_moeda(resumo['cartao_debito'])}")
    _linha(p, f"PIX: {_moeda(resumo['pix'])}")
    _linha(p, f"CONSUMACAO: {_moeda(resumo['consumacao'])}")
    _linha(p)

    p.set(align="center", bold=True)
    _linha(p, "RELACAO DE ITENS VENDIDOS")
    p.set(align="left", bold=False)
    for item in resumo["itens_vendidos"]:
        nome = f"{item['nome_produto']:<16}"[:16]
        qtd = f"{item['quantidade']:>4}"
        preco = f"{_moeda(item['preco_unitario']):>8}"
        total = f"{_moeda(item['total']):>10}"
        _linha(p, f"{nome} {qtd} {preco} {total}")

    _linha(p, _separador())
    p.set(bold=True)
    _linha(p, _duas_colunas(f"TOTAL GERAL: {resumo['total_geral_qtd']}", _moeda(resumo["total_geral_valor"])))
    p.set(bold=False)
    _linha(p)

    if rodape:
        _linha(p)
        p.set(align="center")
        _linha(p, rodape)

    _linha(p)
    p.cut()
    return p.output
