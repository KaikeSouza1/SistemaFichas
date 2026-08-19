"""Versao desta build e verificacao de atualizacao via GitHub Releases.

Nao usa tag/release novo a cada build (o fluxo deste projeto sempre
sobrescreve o mesmo asset "ADK_Fichas_Setup.exe" no release v1.0.0, pra nao
espalhar links diferentes). Em vez disso, a versao "atual" fica marcada no
corpo (body) do release, como "versao=2026.08.06.1" - o app compara esse
valor com o proprio VERSAO_APP pra saber se tem uma build mais nova.
"""

VERSAO_APP = "2026.08.19.1"

REPO = "KaikeSouza1/SistemaFichas"
TAG = "v1.0.0"
URL_RELEASE_API = f"https://api.github.com/repos/{REPO}/releases/tags/{TAG}"
URL_INSTALADOR = f"https://github.com/{REPO}/releases/download/{TAG}/ADK_Fichas_Setup.exe"
