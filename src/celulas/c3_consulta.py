# CÉLULA 3 · Consulta no Colab: chamados e usuários lidos do Firebase (visão do administrador)
import pandas as pd
res = listar_chamados(ADMIN_COLAB)
c, r = res["contagem"], res["resumo"]
print(f"Chamados: {res['total']} | Na fila: {r['fila']} | Em atendimento: {c['Em andamento']} | "
      f"Resolvidos: {c['Concluído']} | Fora do prazo: {r['atrasados']}")
colunas = ["protocolo", "nome", "tipo", "local", "prioridade", "status", "tecnico", "aberto", "prazo", "atrasado"]
display(pd.DataFrame(res["itens"], columns=colunas))
usuarios = listar_usuarios(ADMIN_COLAB)["usuarios"]
print(f"\nUsuários: {len(usuarios)}")
display(pd.DataFrame(usuarios, columns=["nome", "email", "papel_nome", "ativo", "criado"]))
