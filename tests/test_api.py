"""Testes da API: permissões por perfil, portais, regras de negócio e esqueci a senha.

    python tests/test_api.py
"""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import *
import requests as rq
from requests.sessions import Session
s = rq.Session(); s.trust_env = False
def req(metodo, caminho, token=None, json=None, params=None):
    h = {"Authorization": "Bearer " + token} if token else {}
    r = Session.request(s, metodo, API + caminho, json=json, headers=h, params=params)
    try: return r.status_code, r.json()
    except ValueError: return r.status_code, {}
ok = lambda r, c=200: (r[0] == c) or (_ for _ in ()).throw(AssertionError(r))

# --- Admin principal criado automaticamente
assert db["usuarios"]["uidADMIN0001"]["papel"] == "admin"
st, r = req("POST", "/api/auth/login", json={"email": "ADMIN@exemplo.com", "senha": "senha-admin-teste"}); assert st == 200, r
ADM = r["token"]; assert r["usuario"]["papel"] == "admin"
assert req("POST", "/api/auth/login", json={"email": "admin@exemplo.com", "senha": "errada"})[1]["erro"] == "E-mail ou senha incorretos."
# --- Sem login: 401
assert req("GET", "/api/chamados")[0] == 401
assert req("GET", "/api/chamados", token="falso")[0] == 401
# --- Cadastro de cliente (validações)
base_cli = {"nome": "Maria da Silva", "idade": "32", "cpf": "529.982.247-25", "email": "maria@ciesa.br", "senha": "maria123"}
for campo, valor, msg in [("cpf", "111.444.777-36", "CPF inválido"), ("email", "maria", "e-mail válido"),
                          ("senha", "123", "6 caracteres"), ("idade", "9", "intervalo"), ("nome", "M1", "nome válido")]:
    st, r = req("POST", "/api/auth/cadastro", json={**base_cli, campo: valor}); assert st == 400 and msg in r["erro"], (campo, r)
st, r = req("POST", "/api/auth/cadastro", json=base_cli); assert st == 201, r
CLI1 = r["token"]; assert r["usuario"]["papel"] == "cliente" and r["usuario"]["cpf"] == "***.982.247-**"
assert "CPF" in req("POST", "/api/auth/cadastro", json={**base_cli, "email": "outra@ciesa.br"})[1]["erro"]
assert "já está cadastrado" in req("POST", "/api/auth/cadastro", json={**base_cli, "cpf": "12345678909"})[1]["erro"]
st, r = req("POST", "/api/auth/cadastro", json={"nome": "José Antônio", "idade": "67", "cpf": "11144477735", "email": "jose@ciesa.br", "senha": "jose1234"})
CLI2 = r["token"]
# --- Admin cria técnicos; cliente/técnico não podem
assert req("POST", "/api/usuarios", token=CLI1, json={"nome": "X", "email": "x@x.com", "senha": "123456", "papel": "admin"})[0] == 403
st, r = req("POST", "/api/usuarios", token=ADM, json={"nome": "Carlos Técnico", "email": "carlos@ciesa.br", "senha": "carlos123", "papel": "tecnico"}); assert st == 201, r
UID_CARLOS = r["uid"]
req("POST", "/api/usuarios", token=ADM, json={"nome": "Bruna Suporte", "email": "bruna@ciesa.br", "senha": "bruna123", "papel": "tecnico"})
assert "Técnico ou Administrador" in req("POST", "/api/usuarios", token=ADM, json={"nome": "Zé Silva", "email": "ze@x.com", "senha": "123456", "papel": "cliente"})[1]["erro"]
TEC1 = req("POST", "/api/auth/login", json={"email": "carlos@ciesa.br", "senha": "carlos123"})[1]["token"]
TEC2 = req("POST", "/api/auth/login", json={"email": "bruna@ciesa.br", "senha": "bruna123"})[1]["token"]
assert req("GET", "/api/usuarios", token=TEC1)[0] == 403 and req("GET", "/api/painel", token=CLI1)[0] == 403
# --- Abertura: só cliente
ch = {"tipo": "Impressora / scanner", "setor": "Biblioteca", "local": "Balcão", "patrimonio": "imp-001", "prioridade": "Média", "descricao": "Impressora com papel enroscado."}
assert req("POST", "/api/chamados", token=TEC1, json=ch)[0] == 403
assert req("POST", "/api/chamados", token=ADM, json=ch)[0] == 403
st, r = req("POST", "/api/chamados", token=CLI1, json=ch); assert st == 201, r; K1 = r["chave"]
st, r = req("POST", "/api/chamados", token=CLI2, json={**ch, "patrimonio": "IMP-001"}); assert st == 400 and "patrimônio" in r["erro"]
st, r = req("POST", "/api/chamados", token=CLI2, json={**ch, "patrimonio": "", "prioridade": "Alta", "tipo": "Rede / internet / Wi-Fi"}); K2 = r["chave"]
assert r["prioridade"] == "Urgente" and r["preferencial"]
assert db["chamados"][K2]["solicitante"]["nome"] == "José Antônio" and db["chamados"][K2]["solicitante"]["cpf"] == "111.444.777-35"
# limite de 5 ativos por cliente
for i in range(4): ok(req("POST", "/api/chamados", token=CLI1, json={**ch, "patrimonio": ""}), 201)
st, r = req("POST", "/api/chamados", token=CLI1, json={**ch, "patrimonio": ""}); assert st == 400 and "5 chamados" in r["erro"], r
# --- Visibilidade
assert req("GET", "/api/chamados", token=CLI1)[1]["total"] == 5
assert req("GET", "/api/chamados", token=CLI2)[1]["total"] == 1
l = req("GET", "/api/chamados", token=TEC1)[1]; assert l["total"] == 6 and l["resumo"]["fila"] == 6
assert [i["acoes"] for i in l["itens"] if i["chave"] == K1][0] == ["assumir"]
assert [i["acoes"] for i in req("GET", "/api/chamados", token=CLI1)[1]["itens"] if i["chave"] == K1][0] == ["comentar"]
assert [i["acoes"] for i in req("GET", "/api/chamados", token=ADM)[1]["itens"] if i["chave"] == K1][0] == ["assumir", "comentar", "concluir", "atribuir"]
# --- Fluxo técnico
assert req("POST", f"/api/chamados/{K1}/concluir", token=TEC1, json={"texto": "Resolvido"})[0] == 403   # precisa assumir
ok(req("POST", f"/api/chamados/{K1}/assumir", token=TEC1))
assert req("POST", f"/api/chamados/{K1}/assumir", token=TEC2)[0] == 403        # já tem responsável
assert req("POST", f"/api/chamados/{K1}/comentar", token=TEC2, json={"texto": "oi"})[0] == 403
assert req("POST", f"/api/chamados/{K2}/comentar", token=CLI1, json={"texto": "oi oi"})[0] == 403  # chamado de outro cliente
ok(req("POST", f"/api/chamados/{K1}/comentar", token=TEC1, json={"texto": "Vou passar na biblioteca às 14h."}))
ok(req("POST", f"/api/chamados/{K1}/comentar", token=CLI1, json={"texto": "Ok, estarei no balcão."}))
assert "solução" in req("POST", f"/api/chamados/{K1}/concluir", token=TEC1, json={"texto": "ok"})[1]["erro"]
ok(req("POST", f"/api/chamados/{K1}/concluir", token=TEC1, json={"texto": "Rolete de tração limpo e papel realinhado."}))
assert req("POST", f"/api/chamados/{K1}/avaliar", token=TEC1, json={"nota": 5})[0] == 403
assert "1 a 5" in req("POST", f"/api/chamados/{K1}/avaliar", token=CLI1, json={"nota": 9})[1]["erro"]
ok(req("POST", f"/api/chamados/{K1}/avaliar", token=CLI1, json={"nota": 5, "texto": "Rápido e educado"}))
assert req("POST", f"/api/chamados/{K1}/avaliar", token=CLI1, json={"nota": 4})[0] == 403          # só uma vez
assert req("POST", f"/api/chamados/{K1}/reabrir", token=CLI1, json={"texto": "Voltou a travar"})[0] == 403  # já avaliou
# admin atribui, técnico devolve, cliente reabre
st, r = req("GET", "/api/tecnicos", token=ADM); assert [t["nome"] for t in r["tecnicos"]] == ["Administrador", "Bruna Suporte", "Carlos Técnico"]
assert req("POST", f"/api/chamados/{K2}/atribuir", token=ADM, json={"tecnico_uid": "uidINEXISTE"})[0] == 400
ok(req("POST", f"/api/chamados/{K2}/atribuir", token=ADM, json={"tecnico_uid": UID_CARLOS}))
assert db["chamados"][K2]["tecnico"]["nome"] == "Carlos Técnico"
ok(req("POST", f"/api/chamados/{K2}/devolver", token=TEC1)); assert "tecnico" not in db["chamados"][K2]
ok(req("POST", f"/api/chamados/{K2}/assumir", token=TEC2))
ok(req("POST", f"/api/chamados/{K2}/concluir", token=TEC2, json={"texto": "Cabo de rede trocado no balcão."}))
assert "5 a 300" in req("POST", f"/api/chamados/{K2}/reabrir", token=CLI2, json={"texto": "x"})[1]["erro"]
ok(req("POST", f"/api/chamados/{K2}/reabrir", token=CLI2, json={"texto": "Sem internet de novo hoje cedo."}))
c2 = db["chamados"][K2]; assert c2["status"] == "Aberto" and "tecnico" not in c2 and "solucao" not in c2
assert req("POST", f"/api/chamados/{K2}/xpto", token=ADM)[1]["erro"] == "Ação desconhecida."
assert req("POST", "/api/chamados/../x/assumir", token=ADM)[0] in (400, 404)
# histórico com autores
h = [i for i in req("GET", "/api/chamados", token=CLI1)[1]["itens"] if i["chave"] == K1][0]["historico"]
assert [(x["tipo"], x["autor"]) for x in h] == [("status", "Maria da Silva"), ("status", "Carlos Técnico"), ("comentario", "Carlos Técnico"),
                                                 ("comentario", "Maria da Silva"), ("status", "Carlos Técnico"), ("avaliacao", "Maria da Silva")], h
# escopos do técnico
assert req("GET", "/api/chamados", token=TEC1, params={"escopo": "meus"})[1]["encontrados"] == 1
assert req("GET", "/api/chamados", token=TEC1, params={"escopo": "fila"})[1]["encontrados"] == 5
# --- Painel
st, p = req("GET", "/api/painel", token=ADM); assert st == 200, p
assert p["contagem"] == {"Aberto": 5, "Em andamento": 0, "Concluído": 1} and p["satisfacao"] == 5.0 and p["avaliacoes"] == 1
assert p["usuarios"] == {"Cliente": 2, "Técnico": 2, "Administrador": 1} and p["tempo_medio_min"] is not None
assert {t["nome"]: (t["ativos"], t["concluidos"]) for t in p["por_tecnico"]} == {"Carlos Técnico": (0, 1), "Bruna Suporte": (0, 0)}, p["por_tecnico"]
# --- Gestão de usuários
st, r = req("GET", "/api/usuarios", token=ADM); assert [u["papel"] for u in r["usuarios"]] == ["admin", "tecnico", "tecnico", "cliente", "cliente"]
uid_adm = "uidADMIN0001"
assert "próprio" in req("PATCH", f"/api/usuarios/{uid_adm}", token=ADM, json={"ativo": False})[1]["erro"]
ok(req("PATCH", f"/api/usuarios/{UID_CARLOS}", token=ADM, json={"ativo": False}))
assert req("GET", "/api/chamados", token=TEC1)[0] == 401                       # sessão encerrada
assert "desativado" in req("POST", "/api/auth/login", json={"email": "carlos@ciesa.br", "senha": "carlos123"})[1]["erro"]
assert "CPF" in req("PATCH", f"/api/usuarios/{UID_CARLOS}", token=ADM, json={"papel": "cliente"})[1]["erro"]
ok(req("PATCH", f"/api/usuarios/{UID_CARLOS}", token=ADM, json={"ativo": True, "papel": "admin"}))
assert req("POST", "/api/auth/login", json={"email": "carlos@ciesa.br", "senha": "carlos123"})[1]["usuario"]["papel"] == "admin"
# --- Sair
ok(req("POST", "/api/auth/sair", token=CLI2)); assert req("GET", "/api/eu", token=CLI2)[0] == 401
# --- CORS com Authorization
o = s.options(API + "/api/chamados", headers={"Origin": "null", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,content-type"})
assert "Authorization" in o.headers["Access-Control-Allow-Headers"]
# --- Firebase fora
estado["negar"] = True; assert req("GET", "/api/chamados", token=CLI1)[0] == 502; estado["negar"] = False
# senhas nunca no banco nem no log
assert "maria123" not in json.dumps(db) and not any("maria123" in l for l in ns["LOG"])
print("Permissões por perfil: OK")
print("\n".join(list(ns["LOG"])[-8:]))

# ======================= NOVIDADES DA V4 =======================
import harness as harness4
CLI1 = req("POST", "/api/auth/login", json={"email": "maria@ciesa.br", "senha": "maria123"})[1]["token"]
# --- Portais: cada link só aceita o seu perfil
assert req("POST", "/api/auth/login", json={"email": "maria@ciesa.br", "senha": "maria123", "portal": "cliente"})[0] == 200
st, r = req("POST", "/api/auth/login", json={"email": "maria@ciesa.br", "senha": "maria123", "portal": "admin"})
assert st == 403 and "exclusiva para administradores" in r["erro"] and "/cliente" in r["erro"], r
st, r = req("POST", "/api/auth/login", json={"email": "bruna@ciesa.br", "senha": "bruna123", "portal": "cliente"})
assert st == 403 and "exclusiva para clientes" in r["erro"] and "/tecnico" in r["erro"], r
assert req("POST", "/api/auth/login", json={"email": "bruna@ciesa.br", "senha": "bruna123", "portal": "tecnico"})[0] == 200
assert req("POST", "/api/auth/login", json={"email": "admin@exemplo.com", "senha": "senha-admin-teste", "portal": "tecnico"})[0] == 403
ADM = req("POST", "/api/auth/login", json={"email": "admin@exemplo.com", "senha": "senha-admin-teste", "portal": "admin"})[1]["token"]
assert req("POST", "/api/auth/login", json={"email": "maria@ciesa.br", "senha": "errada", "portal": "admin"})[1]["erro"] == "E-mail ou senha incorretos."
# --- Rotas dos portais servem a página
for p in ("/", "/cliente", "/tecnico", "/admin"):
    rr = Session.request(s, "GET", API + p); assert rr.status_code == 200 and "text/html" in rr.headers["Content-Type"], p
# --- Esqueci a senha
st, r = req("POST", "/api/auth/esqueci", json={"email": "Maria@Ciesa.br", "portal": "cliente"}); assert st == 200 and "Se este e-mail" in r["mensagem"], r
assert harness4.EMAILS_ENVIADOS[-1] == ("maria@ciesa.br", "pt-BR")
st, r = req("POST", "/api/auth/esqueci", json={"email": "maria@ciesa.br"}); assert st == 400 and "1 minuto" in r["erro"]
st, r = req("POST", "/api/auth/esqueci", json={"email": "naoexiste@ciesa.br"}); assert st == 200 and "Se este e-mail" in r["mensagem"]   # não revela
assert req("POST", "/api/auth/esqueci", json={"email": "invalido"})[0] == 400
st, r = req("POST", "/api/auth/esqueci", json={"email": "admin@exemplo.com"}); assert st == 400 and "FIREBASE_SENHA" in r["erro"]
assert len(harness4.EMAILS_ENVIADOS) == 1
# --- E-mail do cliente: técnico e admin veem; cliente não recebe o campo preenchido
st, r = req("POST", "/api/chamados", token=req("POST", "/api/auth/login", json={"email": "jose@ciesa.br", "senha": "jose1234"})[1]["token"],
            json={**ch, "patrimonio": "", "tipo": "Telefonia / ramal"}); assert st == 201, r
K9 = r["chave"]
TEC2 = req("POST", "/api/auth/login", json={"email": "bruna@ciesa.br", "senha": "bruna123", "portal": "tecnico"})[1]["token"]
assert [i["email"] for i in req("GET", "/api/chamados", token=TEC2)[1]["itens"] if i["chave"] == K9] == ["jose@ciesa.br"]
assert [i["email"] for i in req("GET", "/api/chamados", token=ADM)[1]["itens"] if i["chave"] == K9] == ["jose@ciesa.br"]
JOSE = req("POST", "/api/auth/login", json={"email": "jose@ciesa.br", "senha": "jose1234"})[1]["token"]
assert all(i["email"] == "" for i in req("GET", "/api/chamados", token=JOSE)[1]["itens"])
# --- Visão do super usuário: resumo de chamados por pessoa
us = {u["email"]: u for u in req("GET", "/api/usuarios", token=ADM)[1]["usuarios"]}
assert us["maria@ciesa.br"]["chamados"] == "4 ativos · 5 no total", us["maria@ciesa.br"]
assert us["jose@ciesa.br"]["chamados"] == "2 ativos · 2 no total", us["jose@ciesa.br"]
assert us["bruna@ciesa.br"]["chamados"] == "0 em atendimento · 0 resolvidos" and us["carlos@ciesa.br"]["chamados"] == "0 em atendimento · 1 resolvido", us
print("Portais, esqueci a senha, contato e resumo por usuário: OK")
