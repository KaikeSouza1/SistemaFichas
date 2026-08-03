"""Envio de bytes ESC/POS para a impressora.

Estrategia escolhida: em vez de falar USB/libusb direto com a Elgin i9 (o que
exigiria trocar o driver Windows por WinUSB via Zadig, dor de cabeca em
campo), a impressora fica instalada normalmente no Windows (driver generico
ou da Elgin) e nos mandamos os bytes ESC/POS crus como um job "RAW" para a
fila de impressao do Windows. Funciona com a impressora local por USB sem
nenhuma configuracao extra alem de escolher o nome dela em Configuracoes.
"""

import win32print


def listar_impressoras_windows() -> list[str]:
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    return [info[2] for info in win32print.EnumPrinters(flags)]


def imprimir(nome_impressora: str, dados: bytes) -> None:
    if not nome_impressora:
        raise ValueError("Nenhuma impressora configurada em Configurações.")

    handle = win32print.OpenPrinter(nome_impressora)
    try:
        win32print.StartDocPrinter(handle, 1, ("Ficha SistemaChurrasco", None, "RAW"))
        try:
            win32print.StartPagePrinter(handle)
            win32print.WritePrinter(handle, dados)
            win32print.EndPagePrinter(handle)
        finally:
            win32print.EndDocPrinter(handle)
    finally:
        win32print.ClosePrinter(handle)
