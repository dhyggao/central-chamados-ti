"""Gera o notebook do Colab a partir do código-fonte em src/.

    python build.py

Saídas:
    notebook/Central_Chamados_TI.ipynb   notebook pronto para abrir no Google Colab
    dist/backend_chamados_colab.py       backend com o frontend embutido (mesmo código da célula 1)
"""
import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
SRC = RAIZ / "src"


def backend_completo():
    html = (SRC / "index.html").read_text(encoding="utf-8")
    assert "'''" not in html, "index.html não pode conter três aspas simples seguidas"
    codigo = (SRC / "backend_template.py").read_text(encoding="utf-8").replace("__FRONTEND_HTML__", html)
    compile(codigo, "backend_chamados_colab.py", "exec")
    return codigo


MARKDOWN = """# Central de Chamados TI · Mini Hackathon NPC2

Sistema de chamados técnicos com **três links de acesso** (`/cliente`, `/tecnico`, `/admin`).
O navegador (HTML + CSS + JS) conversa por HTTPS com a **API Flask deste Colab**, que usa o
**Firebase Authentication** (contas e redefinição de senha) e o **Firebase Realtime Database** (`/usuarios` e `/chamados`).

## Antes de rodar: cadastre os Secrets
Na barra lateral do Colab, clique no ícone de **chave (Secrets)**, adicione os quatro itens abaixo e ative **Acesso ao notebook** em cada um:

| Nome | Valor |
|---|---|
| `FIREBASE_API_KEY` | apiKey do app Web (Configurações do projeto > Geral) |
| `FIREBASE_DATABASE_URL` | ex.: `https://seu-projeto-default-rtdb.firebaseio.com` |
| `FIREBASE_EMAIL` | conta do Authentication usada pelo backend (vira o administrador principal) |
| `FIREBASE_SENHA` | senha dessa conta |

Sem os Secrets, a célula 1 pergunta os valores na hora (e não salva).

## Como usar
1. Rode a **célula 1**: sobe o backend e mostra os três links. Mande cada link só para quem vai usar.
2. **Célula 2**: abre aqui no Colab a página com os três acessos.
3. **Célula 3**: tabelas de chamados e usuários · **Célula 4**: monitor ao vivo · **Célula 5**: o banco como está no Firebase.

## Regras de negócio (Python)
1. Validação de todos os campos (CPF com dígitos verificadores, idade, e-mail, senha com 6+ caracteres).
2. Permissões por perfil e por portal decididas no backend.
3. Prazo de atendimento (SLA) pela prioridade: Urgente 4 h · Alta 8 h · Média 24 h · Baixa 72 h.
4. Atendimento preferencial: cliente com 60 anos ou mais sobe um nível de prioridade.
5. Um chamado ativo por patrimônio; até 5 chamados ativos por cliente; CPF único por conta.
6. Só conclui com a solução descrita; avaliação única; reabertura com motivo volta para a fila.

CPFs de teste: 529.982.247-25 · 123.456.789-09 · 111.444.777-35"""


def celula(tipo, texto):
    c = {"cell_type": tipo, "metadata": {}, "source": texto.splitlines(keepends=True)}
    if tipo == "code":
        c.update(execution_count=None, outputs=[])
    return c


def main():
    backend = backend_completo()
    (RAIZ / "dist").mkdir(exist_ok=True)
    (RAIZ / "dist" / "backend_chamados_colab.py").write_text(backend, encoding="utf-8")
    ler = lambda nome: (SRC / "celulas" / nome).read_text(encoding="utf-8")
    nb = {"nbformat": 4, "nbformat_minor": 0,
          "metadata": {"colab": {"provenance": []}, "kernelspec": {"name": "python3", "display_name": "Python 3"},
                       "language_info": {"name": "python"}},
          "cells": [celula("markdown", MARKDOWN),
                    celula("code", "# CÉLULA 1 · BACKEND (+ páginas dos três portais)\n" + backend),
                    celula("code", ler("c2_frontend.py")), celula("code", ler("c3_consulta.py")),
                    celula("code", ler("c4_monitor.py")), celula("code", ler("c5_banco.py"))]}
    destino = RAIZ / "notebook" / "Central_Chamados_TI.ipynb"
    destino.parent.mkdir(exist_ok=True)
    destino.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"ok: {destino.relative_to(RAIZ)} ({len(nb['cells'])} células) e dist/backend_chamados_colab.py")


if __name__ == "__main__":
    main()
