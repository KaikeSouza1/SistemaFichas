"""Monta os bytes ESC/POS das fichas impressas: uma ficha por UNIDADE
comprada (6 cervejas = 6 fichas separadas, cada uma cortada individualmente,
pra poder entregar uma por vez em cada barraca) e o fechamento de caixa.

Todo texto passa por `_sem_acentos` antes de ir para a impressora: sem saber
ainda qual code page a Elgin i9 vai aceitar em campo, preferimos garantir
ASCII puro sempre. Revisitar depois de testar em impressora real.
"""

import unicodedata
from decimal import Decimal
from io import BytesIO

from escpos.printer import Dummy
from PIL import Image, ImageDraw, ImageFont

from config.settings import pasta_assets

LARGURA_COLUNAS = 42  # ajustar em Configurações se a impressora usar outra fonte/largura
LARGURA_PONTOS = 384  # largura da imagem do nome do produto, em pontos (px).
                      # 384 e seguro pra 58mm; se a Elgin usar 80mm, subir p/ 576.

_logo_cache: dict[int, Image.Image] = {}


def _imagem_logo(largura_px: int) -> Image.Image | None:
    """Logo ADK em preto (a impressora nao tem cor), redimensionada pra largura
    pedida. Cacheada por tamanho apos a primeira leitura - a mesma imagem se
    repete em toda ficha e fechamento. Retorna None se o arquivo nao existir
    (impressao segue sem logo em vez de falhar)."""
    if largura_px in _logo_cache:
        return _logo_cache[largura_px]

    caminho = pasta_assets() / "logo_adk_preto.png"
    if not caminho.exists():
        return None

    logo = Image.open(caminho)
    alpha = logo.split()[-1]
    cinza = Image.eval(alpha, lambda a: 255 - a)  # alpha 255 (preto opaco) -> cinza 0 (preto)

    altura_proporcional = int(cinza.height * (largura_px / cinza.width))
    cinza = cinza.resize((largura_px, altura_proporcional), Image.LANCZOS)

    # Modo coluna (ESC*) imprime em bandas de 24px - arredondar evita corte no meio.
    altura_final = ((altura_proporcional + 23) // 24) * 24
    canvas = Image.new("L", (largura_px, altura_final), color=255)
    canvas.paste(cinza, (0, (altura_final - altura_proporcional) // 2))

    _logo_cache[largura_px] = canvas
    return canvas

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

    margem = 16
    tamanho_fonte = 120
    fonte = _carregar_fonte(tamanho_fonte)
    caixa = medidor.textbbox((0, 0), nome, font=fonte)
    # Piso baixo o bastante pra nomes longos ("PORCAO DE FRITAS") realmente
    # coubessem - um piso alto (o antigo, 48) fazia o laço desistir cedo demais
    # e desenhar largo demais pra caber, cortando o texto dos dois lados.
    while caixa[2] - caixa[0] > largura_px - margem and tamanho_fonte > 24:
        tamanho_fonte -= 4
        fonte = _carregar_fonte(tamanho_fonte)
        caixa = medidor.textbbox((0, 0), nome, font=fonte)

    largura_texto, altura_texto = caixa[2] - caixa[0], caixa[3] - caixa[1]
    altura_img = altura_texto + 28
    # Modo coluna (ESC*) imprime em bandas de 24px; se a altura nao for
    # multiplo de 24 a ultima banda fica truncada e "corta" o texto no meio.
    altura_img = ((altura_img + 23) // 24) * 24
    imagem = Image.new("L", (largura_px, altura_img), color=255)
    desenho = ImageDraw.Draw(imagem)
    # Nunca desenhar com x negativo: se ainda assim nao coubesse, e melhor
    # cortar so a direita (nome legivel do inicio) do que cortar dos dois
    # lados e virar sopa de letra (era exatamente o bug: "RCAO DE FRIT").
    x = max(0, (largura_px - largura_texto) // 2 - caixa[0])
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


def _ficha_de_um_item(p, nome_evento, numero_pedido, data_hora, nome_item, preco, operador_nome, caixa_nome,
                        ocultar_valor=False, largura_pontos=LARGURA_PONTOS, cortador_automatico=True):
    logo_pequeno = _imagem_logo(160)
    if logo_pequeno:
        p.set(align="center")
        p.image(logo_pequeno, impl="bitImageColumn")

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
    p.image(_imagem_nome_produto(nome_item, largura_pontos), impl="bitImageColumn")
    _linha(p)

    # Preco, operador e rodape: alinhados a esquerda, compactos, sem linhas
    # em branco entre eles (igual ao modelo de referencia).
    if not ocultar_valor:
        p.set(align="left", bold=True)
        _linha(p, f"R$ {_moeda(preco)}")
    p.set(align="left", bold=False)
    _linha(p, f"OPER: {operador_nome} - CAIXA: {caixa_nome}")
    if cortador_automatico:
        p.cut()
    else:
        # Impressoras Bluetooth portateis (as que os vendedores usam andando
        # pela festa) normalmente NAO tem guilhotina automatica - so a Elgin
        # i9 do PC tem. p.cut() sempre avanca 6 linhas de papel pra dar
        # margem pra guilhotina cortar; nessa impressora o corte nunca
        # acontece e esse avanco todo fica so como espaco em branco
        # desperdicado. Aqui avancamos bem pouco e marcamos uma linha
        # pontilhada, pra cortar/rasgar na mao no lugar certo.
        p.set(align="center", bold=False)
        _linha(p, "- " * (LARGURA_COLUNAS // 2))
        p.print_and_feed(2)


def fichas_venda_bytes(
    nome_evento: str,
    numero_pedido: int,
    data_hora: str,
    itens: list[dict],
    operador_nome: str,
    caixa_nome: str,
    largura_pontos: int = LARGURA_PONTOS,
    cortador_automatico: bool = True,
) -> bytes:
    """itens: lista de {"nome": str, "quantidade": int, "preco": Decimal,
    "ocultar_valor": bool}. Gera uma ficha separada (com corte) para CADA
    unidade de CADA item — comprar 6 cervejas imprime 6 fichas individuais de
    cerveja. Itens de combo ja devem chegar aqui expandidos nos componentes,
    cada um ja com seu proprio "ocultar_valor" (ver
    repository.expandir_itens_para_impressao - a flag vem do cadastro do
    PRODUTO, nao e mais uma escolha feita na hora de vender).

    largura_pontos: largura da imagem do nome do produto. A Elgin i9 (USB,
    PC) usa o padrao de 58mm (LARGURA_PONTOS); impressoras Bluetooth de
    80mm usadas no celular (ver db/modo_celular.py) devem passar 576.

    cortador_automatico: a Elgin i9 (PC) tem guilhotina automatica - deixa
    True. Impressoras Bluetooth portateis normalmente NAO tem - passe False
    pra nao desperdicar papel com o avanco que a guilhotina inexistente
    nunca usa (ver _ficha_de_um_item)."""
    p = Dummy()
    p.hw("INIT")
    for item in itens:
        for _ in range(item["quantidade"]):
            _ficha_de_um_item(
                p, nome_evento, numero_pedido, data_hora,
                item["nome"], item["preco"], operador_nome, caixa_nome, item.get("ocultar_valor", False),
                largura_pontos, cortador_automatico,
            )
    return p.output


def ficha_churrasco_bytes(
    nome_evento: str,
    numero_ficha: int,
    nome_carne: str,
    nome_cliente: str,
    valor,
    data_hora: str,
    operador_nome: str,
    caixa_nome: str,
    nome_churrasqueira: str,
    largura_pontos: int = LARGURA_PONTOS,
    cortador_automatico: bool = True,
) -> bytes:
    """Ficha do modulo de churrasco (venda por unidade, com nome do cliente -
    ver ui/screens/churrasco.py). So a via do cliente e impressa - o canhoto
    de papel que ficava com o time deixou de ser necessario, o proprio banco
    ja registra quem vendeu pra quem (ver db/repository.registrar_ficha_churrasco_do_bloco).

    Layout pedido pelo usuario (2026-08-11): o NOME DO CLIENTE e o destaque
    principal - usa a mesma imagem grande que antes era so pro nome da carne
    (`_imagem_nome_produto`, generica, apesar do nome). O NUMERO da ficha
    tambem e grande (ESC ! double_width/height), mas SO o numero, sem "No"
    na frente. A CARNE virou secundaria - texto pequeno, junto de VALOR/data,
    em vez de imagem grande."""
    p = Dummy()
    p.hw("INIT")

    logo_pequeno = _imagem_logo(160)
    if logo_pequeno:
        p.set(align="center")
        p.image(logo_pequeno, impl="bitImageColumn")

    p.set(align="center", bold=True)
    _linha(p, nome_evento.upper()[:LARGURA_COLUNAS])
    p.set(align="left", bold=False)
    _linha(p, _separador())

    p.set(align="center")
    p.image(_imagem_nome_produto(nome_cliente, largura_pontos), impl="bitImageColumn")
    _linha(p)

    p.set(align="left", bold=True)
    _linha(p, f"CHURRASQUEIRA: {nome_churrasqueira}")
    p.set(align="left", bold=False)
    _linha(p)

    p.set(align="center", bold=True, double_width=True, double_height=True)
    _linha(p, f"{numero_ficha}")
    p.set(align="center", bold=False, normal_textsize=True)
    _linha(p)

    p.set(align="left", bold=True)
    _linha(p, f"CARNE: {nome_carne}")
    _linha(p, f"VALOR: R$ {_moeda(valor)}")
    p.set(align="left", bold=False)
    _linha(p, _duas_colunas(data_hora, f"OPER: {operador_nome}"))
    _linha(p, f"CAIXA: {caixa_nome}")

    if cortador_automatico:
        p.cut()
    else:
        p.set(align="center", bold=False)
        _linha(p, "- " * (LARGURA_COLUNAS // 2))
        p.print_and_feed(2)
    return p.output


def ficha_churrasco_preview_png(
    nome_evento: str,
    numero_ficha: int,
    nome_carne: str,
    nome_cliente: str,
    valor,
    data_hora: str,
    operador_nome: str,
    caixa_nome: str,
    nome_churrasqueira: str,
    largura_pontos: int = LARGURA_PONTOS,
) -> bytes:
    """Gera uma IMAGEM (PNG) com o mesmo conteudo da ficha real, pra
    pre-visualizar dentro do proprio app sem precisar de impressora termica
    de verdade. Pedido do usuario: se a impressora escolhida em Configurações
    for "Microsoft Print to PDF" (ou qualquer outra sem suporte real a
    ESC/POS), mandar os bytes crus pra ela so produz lixo - essa
    pre-visualizacao sempre funciona, independente de qual impressora esta
    configurada (ver ui/screens/churrasco.py, botão "Pré-visualizar")."""
    largura = largura_pontos
    margem = 20

    fonte_normal = _carregar_fonte(20)
    fonte_negrito = _carregar_fonte(22)
    fonte_numero = _carregar_fonte(46)

    logo = _imagem_logo(min(160, largura - 2 * margem))
    # Nome do CLIENTE e o destaque principal (mesma imagem grande que antes
    # era so pra carne - `_imagem_nome_produto` e generica, apesar do nome).
    nome_img = _imagem_nome_produto(nome_cliente, largura - 2 * margem)

    medidor = ImageDraw.Draw(Image.new("L", (1, 1)))

    def altura_linha(fonte):
        caixa = medidor.textbbox((0, 0), "Agy", font=fonte)
        return (caixa[3] - caixa[1]) + 12

    linha_churrasqueira = (f"CHURRASQUEIRA: {nome_churrasqueira}", fonte_negrito)
    linhas_rodape = [
        (f"CARNE: {nome_carne}", fonte_negrito),
        (f"VALOR: R$ {_moeda(valor)}", fonte_negrito),
        (data_hora, fonte_normal),
        (f"OPER: {operador_nome} - CAIXA: {caixa_nome}", fonte_normal),
    ]

    altura_total = margem
    if logo:
        altura_total += logo.height + 10
    altura_total += altura_linha(fonte_negrito) + 8  # nome do evento + separador
    altura_total += nome_img.height + 10
    altura_total += altura_linha(fonte_negrito) + 10  # churrasqueira
    altura_total += altura_linha(fonte_numero) + 10  # numero grande
    altura_total += sum(altura_linha(fonte) for _, fonte in linhas_rodape)
    altura_total += margem

    canvas = Image.new("RGB", (largura, altura_total), color="white")
    desenho = ImageDraw.Draw(canvas)

    def centralizar(texto, fonte, y):
        texto = _sem_acentos(texto)
        caixa = desenho.textbbox((0, 0), texto, font=fonte)
        x = max(margem, (largura - (caixa[2] - caixa[0])) // 2)
        desenho.text((x, y), texto, font=fonte, fill="black")

    y = margem
    if logo:
        canvas.paste(logo.convert("RGB"), ((largura - logo.width) // 2, y))
        y += logo.height + 10

    centralizar(nome_evento.upper()[:LARGURA_COLUNAS], fonte_negrito, y)
    y += altura_linha(fonte_negrito)
    desenho.line([(margem, y), (largura - margem, y)], fill="black", width=1)
    y += 8

    canvas.paste(nome_img.convert("RGB"), ((largura - nome_img.width) // 2, y))
    y += nome_img.height + 10

    texto_churrasqueira, fonte_churrasqueira = linha_churrasqueira
    desenho.text((margem, y), _sem_acentos(texto_churrasqueira), font=fonte_churrasqueira, fill="black")
    y += altura_linha(fonte_churrasqueira) + 10

    centralizar(str(numero_ficha), fonte_numero, y)
    y += altura_linha(fonte_numero) + 10

    for texto, fonte in linhas_rodape:
        desenho.text((margem, y), _sem_acentos(texto), font=fonte, fill="black")
        y += altura_linha(fonte)

    buffer = BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()


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

    logo = _imagem_logo(280)
    if logo:
        p.set(align="center")
        p.image(logo, impl="bitImageColumn")

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


def relatorio_ranking_bytes(titulo: str, linhas: list[dict], campo_nome: str, campo_qtd: str, campo_total: str) -> bytes:
    """Imprime um relatorio simples de ranking (produtos mais vendidos, vendas
    por operador/caixa, itens excluidos etc) em texto puro, sem imagem."""
    p = Dummy()
    p.hw("INIT")

    p.set(align="center", bold=True)
    _linha(p, titulo.upper()[:LARGURA_COLUNAS])
    p.set(align="left", bold=False)
    _linha(p, _separador())

    total_qtd = 0
    total_valor = Decimal("0")
    for linha in linhas:
        nome = f"{str(linha[campo_nome]):<24}"[:24]
        qtd = f"{linha[campo_qtd]:>5}"
        total = f"{_moeda(linha[campo_total]):>10}"
        _linha(p, f"{nome} {qtd} {total}")
        total_qtd += linha[campo_qtd]
        total_valor += Decimal(str(linha[campo_total]))

    if not linhas:
        _linha(p, "Sem dados.")

    _linha(p, _separador())
    p.set(bold=True)
    _linha(p, _duas_colunas(f"TOTAL: {total_qtd}", _moeda(total_valor)))
    p.set(bold=False)
    _linha(p)
    p.cut()
    return p.output


def relatorio_churrasco_bytes(nome_evento: str, fichas: list[dict], por_churrasqueira: list[dict]) -> bytes:
    """Relatorio final do churrasco (pedido do usuario, 2026-09: substitui o
    ranking "por carne" separado) - uma unica impressao com: 1) lista achatada
    de TODAS as fichas pagas (numero + carne + valor, sem agrupar/selecionar
    carne nenhuma) com total de quantidade e valor no fim; 2) resumo por
    churrasqueira (cor) logo em seguida, na MESMA impressao - antes isso
    dependia de um botao separado que o usuario as vezes nao via imprimir."""
    p = Dummy()
    p.hw("INIT")

    p.set(align="center", bold=True)
    _linha(p, "RELATORIO DO CHURRASCO")
    p.set(bold=False)
    _linha(p, nome_evento.upper()[:LARGURA_COLUNAS])
    _linha(p, _separador())

    p.set(align="left", bold=True)
    _linha(p, "Nº   CARNE                    VALOR")
    p.set(bold=False)
    total_qtd = 0
    total_valor = Decimal("0")
    for f in fichas:
        numero = f"{f['numero_ficha']:<4}"[:4]
        carne = f"{str(f['nome_carne']):<20}"[:20]
        valor = f"{_moeda(f['valor']):>10}"
        _linha(p, f"{numero} {carne} {valor}")
        total_qtd += 1
        total_valor += Decimal(str(f["valor"]))

    if not fichas:
        _linha(p, "Nenhuma ficha paga.")

    _linha(p, _separador())
    p.set(bold=True)
    _linha(p, _duas_colunas(f"TOTAL: {total_qtd} ficha(s)", _moeda(total_valor)))
    p.set(bold=False)
    _linha(p)

    p.set(align="center", bold=True)
    _linha(p, "POR CHURRASQUEIRA")
    p.set(align="left", bold=False)
    _linha(p, _separador())
    for linha in por_churrasqueira:
        nome = f"{str(linha['nome_churrasqueira'] or linha['cor_hex']):<20}"[:20]
        qtd = f"{linha['qtd']:>5}"
        total = f"{_moeda(linha['total']):>10}"
        _linha(p, f"{nome} {qtd} {total}")
    if not por_churrasqueira:
        _linha(p, "Sem dados.")

    _linha(p)
    p.cut()
    return p.output
