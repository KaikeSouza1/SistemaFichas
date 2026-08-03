"""Servidor central fixo: destino de sincronizacao de TODOS os eventos, de
TODOS os PCs, de TODAS as cidades. Fixo de proposito - nao aparece em nenhuma
tela de configuracao, o usuario/operador nunca ve nem edita isso.

CREDENCIAIS REMOVIDAS DO HISTORICO (vazamento real corrigido - a versao
antiga deste arquivo tinha host/user/senha em texto puro, exposta quando o
repositorio ficou publico). Nunca mais commitar segredo aqui - config real
fica em config/central.local.json, gitignored.
"""

CENTRAL = None
