# CÉLULA 5 · O BANCO NO FIREBASE: usuários e chamados exatamente como estão gravados
import json
banco = {"usuarios": db_get(NO_USUARIOS) or {}, "chamados": db_get(NO_CHAMADOS) or {}}
projeto_fb = DATABASE_URL.split("//")[1].split("-default-rtdb")[0]
print(f"Firebase Realtime Database: {DATABASE_URL}  ·  {len(banco['usuarios'])} usuário(s) · {len(banco['chamados'])} chamado(s)\n")
texto = json.dumps(banco, indent=2, ensure_ascii=False)
print(texto if len(texto) <= 10000 else texto[:10000] + "\n... (cortado; veja tudo no Console)")
display(HTML(f'<a href="https://console.firebase.google.com/project/{projeto_fb}/database/{projeto_fb}-default-rtdb/data" '
             f'target="_blank" style="font-family:Arial;font-weight:600">Abrir o banco no Console do Firebase</a>'))
