"""Estado compartilhado da sessao deste terminal (nao e o estado do banco,
e so o que a interface precisa lembrar enquanto o app esta aberto)."""

from dataclasses import dataclass, field


@dataclass
class EstadoApp:
    evento_id: int | None = None
    caixa_id: int | None = None
    caixa_nome: str = ""
    operador_id: int | None = None
    operador_nome: str = ""
    sessao_id: int | None = None
    carrinho: list = field(default_factory=list)  # [{produto_id, nome, preco, custo, quantidade}]

    def limpar_carrinho(self):
        self.carrinho.clear()

    def total_carrinho(self):
        return sum(item["preco"] * item["quantidade"] for item in self.carrinho)

    def encerrar_sessao_local(self):
        self.sessao_id = None
        self.limpar_carrinho()

    def deslogar(self):
        self.operador_id = None
        self.operador_nome = ""
        self.sessao_id = None
        self.limpar_carrinho()
