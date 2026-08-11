"""Acesso pela tela de venda a partir do celular: o PC "principal" do evento
tambem serve a mesma tela via HTTP na rede local (Flet em modo web), pra
vendedores ambulantes abrirem no navegador do celular sem instalar nada -
so escanear o QR code. Ver ui/screens/configuracao.py (mostra o QR) e
ui/app.py (cada celular pede seu proprio nome de caixa, guardado no
navegador via page.client_storage - nao usa o config.json do PC).

Impressao pelo celular: a ideia e usar o app RawBT (Play Store) com
impressoras Bluetooth genericas, mandando os bytes ESC/POS via link
"rawbt:base64,..." - ainda nao implementado de verdade, depende do cliente
comprar a impressora primeiro pra testar com hardware real.
"""

import base64
import io
import subprocess

import qrcode

PORTA_WEB = 8551
_NOME_REGRA_FIREWALL = "ADK Fichas - Acesso Celular"


def liberar_firewall() -> bool:
    """Mesmo padrao de db/postgres_local.py e db/descoberta.py: so tenta sem
    pedir elevacao, e sempre com CREATE_NO_WINDOW (senao abre janela de
    console visivel no app empacotado - ja foi bug real nesta sessao)."""
    try:
        verificar = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule", f"name={_NOME_REGRA_FIREWALL}"],
            capture_output=True, text=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if verificar.returncode == 0 and "No rules match" not in verificar.stdout:
            return True
        resultado = subprocess.run(
            ["netsh", "advfirewall", "firewall", "add", "rule",
             f"name={_NOME_REGRA_FIREWALL}", "dir=in", "action=allow",
             "protocol=TCP", f"localport={PORTA_WEB}"],
            capture_output=True, text=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return resultado.returncode == 0
    except Exception:
        return False


def url_acesso(host: str) -> str:
    return f"http://{host}:{PORTA_WEB}"


def qrcode_base64(url: str) -> str:
    """PNG do QR code do link, ja em base64 - pronto pra ft.Image(src_base64=...)."""
    imagem = qrcode.make(url)
    buffer = io.BytesIO()
    imagem.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")
