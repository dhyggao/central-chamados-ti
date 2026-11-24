# =====================================================================
#  MINI HACKATHON NPC2 | CHAMADOS TÉCNICOS · BACKEND (Google Colab)
#  Três portais com links próprios: /cliente · /tecnico · /admin
#  Python (Flask) = autenticação, permissões, validação e regras de negócio
#  Firebase Authentication (contas) + Realtime Database (dados), tudo via HTTPS
# =====================================================================
import os
import re
import time
import secrets
import logging
import datetime
import threading
import subprocess
import collections
import urllib.request
import requests
from flask import Flask, request, jsonify
from werkzeug.serving import make_server
from IPython.display import HTML, display

# ----------------------------- CONFIGURAÇÃO -----------------------------
# As credenciais NÃO ficam no código. No Colab, cadastre-as em "Secrets" (ícone de chave, na barra
# lateral) com os nomes abaixo e ative "Acesso ao notebook". Fora do Colab, use variáveis de ambiente.
#   FIREBASE_API_KEY       apiKey do app Web (Configurações do projeto > Geral)
#   FIREBASE_DATABASE_URL  ex.: https://seu-projeto-default-rtdb.firebaseio.com
#   FIREBASE_EMAIL         conta do Authentication usada pelo backend (vira o administrador principal)
#   FIREBASE_SENHA         senha dessa conta
def config(nome, secreto=False):
    try:
        from google.colab import userdata
        valor = userdata.get(nome)
        if valor:
            return valor.strip()
    except Exception:
        pass
    valor = os.environ.get(nome, "").strip()
    if valor:
        return valor
    from getpass import getpass
    pergunta = f"{nome} não encontrado nos Secrets. Digite (não fica salvo): "
    return (getpass(pergunta) if secreto else input(pergunta)).strip()


PROJETO      = "Chamados Técnicos · Suporte TI"
EQUIPE       = ["Rodrigo Miranda Braga"]          # adicione os nomes da equipe aqui
API_KEY      = config("FIREBASE_API_KEY", secreto=True)
DATABASE_URL = config("FIREBASE_DATABASE_URL").rstrip("/")
EMAIL        = config("FIREBASE_EMAIL").lower()   # conta do backend = administrador principal
SENHA        = config("FIREBASE_SENHA", secreto=True)
ADMIN_NOME   = "Administrador"
NO_CHAMADOS  = "chamados"
NO_USUARIOS  = "usuarios"
PORTA        = 5000
USAR_TUNEL   = True
FUSO         = datetime.timezone(datetime.timedelta(hours=-4))   # Manaus

# ------------------------- CATÁLOGO E REGRAS -----------------------------
TIPOS = [
    {"grupo": "Hardware", "itens": [
        "Computador não liga", "Computador lento ou travando", "Impressora / scanner",
        "Periférico (teclado, mouse, monitor)", "Projetor / lousa digital"]},
    {"grupo": "Software e acesso", "itens": [
        "Instalação de software", "Erro em sistema / programa", "Acesso, senha ou e-mail"]},
    {"grupo": "Infraestrutura", "itens": [
        "Rede / internet / Wi-Fi", "Telefonia / ramal", "Energia / tomada"]},
    {"grupo": "Outros", "itens": ["Outro"]},
]
TODOS_TIPOS  = [t for g in TIPOS for t in g["itens"]]
SETORES      = ["Laboratório de informática", "Sala de aula", "Biblioteca", "Secretaria acadêmica",
                "Coordenação", "Financeiro", "Administrativo", "Outro"]
PRIORIDADES  = ["Baixa", "Média", "Alta", "Urgente"]
PRAZO_HORAS  = {"Baixa": 72, "Média": 24, "Alta": 8, "Urgente": 4}   # regra: SLA por prioridade
STATUS       = ["Aberto", "Em andamento", "Concluído"]
PAPEIS       = {"cliente": "Cliente", "tecnico": "Técnico", "admin": "Administrador"}
PAPEIS_PLURAL = {"cliente": "clientes", "tecnico": "técnicos", "admin": "administradores"}
IDADE_PREFERENCIAL     = 60     # regra: atendimento preferencial
MAX_ATIVOS_POR_CLIENTE = 5      # regra: limite de chamados ativos por cliente
DURACAO_SESSAO_H       = 8

URL_AUTH = "https://identitytoolkit.googleapis.com/v1/accounts:"
ERROS_CONTA = {
    "EMAIL_EXISTS": "Este e-mail já está cadastrado.",
    "WEAK_PASSWORD": "A senha precisa de pelo menos 6 caracteres.",
    "MISSING_PASSWORD": "Informe a senha.",
    "INVALID_EMAIL": "E-mail em formato inválido.",
    "EMAIL_NOT_FOUND": "E-mail ou senha incorretos.",
    "INVALID_PASSWORD": "E-mail ou senha incorretos.",
    "INVALID_LOGIN_CREDENTIALS": "E-mail ou senha incorretos.",
    "USER_DISABLED": "Conta desativada no Firebase.",
    "TOO_MANY_ATTEMPTS_TRY_LATER": "Muitas tentativas; aguarde alguns minutos.",
    "OPERATION_NOT_ALLOWED": "Login por e-mail/senha desativado (Authentication > Sign-in method).",
    "RESET_PASSWORD_EXCEED_LIMIT": "Limite de pedidos de nova senha atingido; tente mais tarde.",
    "ADMIN_ONLY_OPERATION": "O Firebase está bloqueando novos cadastros (Authentication > Configurações > Ações do usuário > Permitir criação).",
}
FORMATO = "%Y-%m-%d %H:%M:%S"
LOG = collections.deque(maxlen=150)


class NaoAutenticado(Exception):
    pass


class SemPermissao(Exception):
    pass


def agora():
    return datetime.datetime.now(FUSO).replace(tzinfo=None)


def agora_txt():
    return agora().strftime(FORMATO)


def registrar_log(texto):
    LOG.append(f"{agora():%H:%M:%S}  {texto}")


def curta(data_txt):
    """'2026-11-19 20:15:03' -> '19/11 20:15'"""
    s = str(data_txt or "")
    return f"{s[8:10]}/{s[5:7]} {s[11:16]}" if len(s) >= 16 else s


def protocolo(chave):
    return "CT-" + chave[-6:].upper()


def mascarar_cpf(cpf):
    cpf = str(cpf or "")
    return f"***.{cpf[4:11]}-**" if len(cpf) == 14 else cpf


def chave_valida(chave):
    if not re.fullmatch(r"[-_A-Za-z0-9]{1,40}", str(chave or "")):
        raise ValueError("Identificador inválido.")
    return chave


# ------------------------------ HTTP (HTTPS) -----------------------------
def _http(funcao, url, **kwargs):
    try:
        return funcao(url, timeout=15, **kwargs)
    except requests.RequestException:
        raise RuntimeError("Não foi possível conectar ao Firebase (verifique a internet e as URLs).")


def _resposta_db(r):
    if r.status_code == 200:
        return r.json()
    if r.status_code == 401:
        raise RuntimeError("Permissão negada pelo Realtime Database (confira as Rules do banco).")
    if r.status_code == 404:
        raise RuntimeError("Banco não encontrado (confira o DATABASE_URL).")
    try:
        detalhe = r.json().get("error", r.text)
    except ValueError:
        detalhe = r.text
    raise RuntimeError(f"Erro {r.status_code} do Firebase: {detalhe}")


def _url(caminho):
    return f"{DATABASE_URL}/{caminho.strip('/')}.json"


# ------------------- CONTA DO BACKEND (Firebase Auth) --------------------
_sessao = {"token": None, "expira": 0.0, "uid": None}

def autenticar():
    """Login do próprio backend (conta do administrador); o token dá acesso ao banco."""
    if _sessao["token"] and time.time() < _sessao["expira"] - 60:
        return _sessao["token"]
    r = _http(requests.post, URL_AUTH + "signInWithPassword", params={"key": API_KEY},
              json={"email": EMAIL, "password": SENHA, "returnSecureToken": True})
    try:
        dados = r.json()
    except ValueError:
        dados = {}
    if r.status_code != 200:
        codigo = dados.get("error", {}).get("message", f"HTTP {r.status_code}")
        if "API key not valid" in codigo or "API_KEY_INVALID" in codigo:
            raise RuntimeError("apiKey inválida (confira API_KEY).")
        raise RuntimeError("Login do backend: " + ERROS_CONTA.get(codigo.split(" ")[0].split(":")[0], codigo))
    _sessao.update(token=dados["idToken"], uid=dados["localId"],
                   expira=time.time() + int(dados.get("expiresIn", 3600)))
    return _sessao["token"]


def db_get(caminho):
    return _resposta_db(_http(requests.get, _url(caminho), params={"auth": autenticar()}))


def db_post(caminho, dados):
    return _resposta_db(_http(requests.post, _url(caminho), params={"auth": autenticar()}, json=dados))


def db_put(caminho, dados):
    return _resposta_db(_http(requests.put, _url(caminho), params={"auth": autenticar()}, json=dados))


def db_patch(caminho, dados):
    return _resposta_db(_http(requests.patch, _url(caminho), params={"auth": autenticar()}, json=dados))


# ------------------------------ VALIDAÇÕES -------------------------------
def validar_cpf(cpf):
    d = re.sub(r"\D", "", str(cpf or ""))
    if len(d) != 11 or d == d[0] * 11:
        return None
    for n in (9, 10):
        soma = sum(int(d[i]) * (n + 1 - i) for i in range(n))
        if (soma * 10 % 11) % 10 != int(d[n]):
            return None
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"


def validar_nome(nome):
    nome = " ".join(str(nome or "").split())
    if len(nome) < 3 or len(nome) > 80 or not re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿ' .-]+", nome):
        raise ValueError("Informe um nome válido (somente letras, mínimo 3 caracteres).")
    return nome


def validar_idade(idade):
    txt = str(idade if idade is not None else "").strip()
    if not txt:
        raise ValueError("Informe a idade.")
    if not txt.isdigit():
        raise ValueError("A idade deve ser um número inteiro.")
    if not 14 <= int(txt) <= 110:
        raise ValueError("Idade fora do intervalo permitido (14 a 110 anos).")
    return int(txt)


def validar_email(email):
    email = str(email or "").strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", email):
        raise ValueError("Informe um e-mail válido.")
    return email


def validar_senha(senha):
    senha = str(senha or "")
    if len(senha) < 6:
        raise ValueError("A senha precisa de pelo menos 6 caracteres.")
    return senha


def validar_texto(texto, minimo, maximo, rotulo):
    texto = " ".join(str(texto or "").split())
    if not minimo <= len(texto) <= maximo:
        raise ValueError(f"{rotulo} deve ter de {minimo} a {maximo} caracteres.")
    return texto


def validar_dados_chamado(d):
    if not isinstance(d, dict):
        raise ValueError("Dados inválidos.")
    if d.get("tipo") not in TODOS_TIPOS:
        raise ValueError("Selecione o tipo de solicitação.")
    if d.get("setor") not in SETORES:
        raise ValueError("Selecione o setor.")
    local = validar_texto(d.get("local"), 2, 60, "O local (ex.: Laboratório 03, Sala S012)")
    patrimonio = str(d.get("patrimonio") or "").strip().upper()
    if patrimonio and not re.fullmatch(r"[A-Z0-9./-]{2,20}", patrimonio):
        raise ValueError("Patrimônio inválido (use letras, números, ponto, barra ou hífen).")
    if d.get("prioridade") not in PRIORIDADES:
        raise ValueError("Selecione a prioridade.")
    descricao = validar_texto(d.get("descricao"), 10, 500, "A descrição do problema")
    return {"tipo": d["tipo"], "setor": d["setor"], "local": local, "patrimonio": patrimonio,
            "prioridade": d["prioridade"], "descricao": descricao}


# ------------------- CONTAS DE USUÁRIO (Firebase Auth) -------------------
def conta_firebase(acao, email, senha):
    """acao = 'signUp' (criar conta) ou 'signInWithPassword' (entrar)."""
    r = _http(requests.post, URL_AUTH + acao, params={"key": API_KEY},
              json={"email": email, "password": senha, "returnSecureToken": True})
    try:
        dados = r.json()
    except ValueError:
        dados = {}
    if r.status_code != 200:
        codigo = dados.get("error", {}).get("message", f"HTTP {r.status_code}")
        chave = codigo.split(" ")[0].split(":")[0]
        if chave in ERROS_CONTA:
            raise ValueError(ERROS_CONTA[chave])
        raise RuntimeError(f"Firebase Authentication: {codigo}")
    return dados


SESSOES = {}   # token da sessão -> usuário logado (o perfil fica no Firebase)

def abrir_sessao(uid, perfil):
    token = secrets.token_urlsafe(32)
    SESSOES[token] = {"uid": uid, "nome": perfil["nome"], "email": perfil["email"], "papel": perfil["papel"],
                      "expira": time.time() + DURACAO_SESSAO_H * 3600}
    return token


def encerrar_sessoes(uid):
    for token in [t for t, s in SESSOES.items() if s["uid"] == uid]:
        del SESSOES[token]


def _token_requisicao():
    cab = request.headers.get("Authorization", "")
    return cab[7:] if cab.startswith("Bearer ") else ""


def usuario_atual():
    token = _token_requisicao()
    s = SESSOES.get(token)
    if not s or s["expira"] < time.time():
        SESSOES.pop(token, None)
        raise NaoAutenticado("Sessão expirada ou inválida. Entre novamente.")
    return s


def requer(*papeis):
    u = usuario_atual()
    if papeis and u["papel"] not in papeis:
        raise SemPermissao("Seu perfil não tem acesso a esta função.")
    return u


def publico(uid, perfil):
    return {"uid": uid, "nome": perfil.get("nome", ""), "email": perfil.get("email", ""),
            "papel": perfil.get("papel", ""), "papel_nome": PAPEIS.get(perfil.get("papel"), ""),
            "idade": perfil.get("idade"), "cpf": mascarar_cpf(perfil.get("cpf"))}


def garantir_admin():
    """A conta do backend (EMAIL) é sempre o administrador principal."""
    autenticar()
    uid = _sessao["uid"]
    perfil = db_get(f"{NO_USUARIOS}/{uid}")
    if not isinstance(perfil, dict):
        db_put(f"{NO_USUARIOS}/{uid}", {"nome": ADMIN_NOME, "email": EMAIL, "papel": "admin",
                                        "ativo": True, "criado_em": agora_txt()})
    elif perfil.get("papel") != "admin" or not perfil.get("ativo", True):
        db_patch(f"{NO_USUARIOS}/{uid}", {"papel": "admin", "ativo": True})
    return uid


def cadastrar_cliente(d):
    """Cadastro público: cria a conta no Firebase Auth e o perfil de CLIENTE no banco."""
    d = d if isinstance(d, dict) else {}
    nome, idade = validar_nome(d.get("nome")), validar_idade(d.get("idade"))
    cpf = validar_cpf(d.get("cpf"))
    if not cpf:
        raise ValueError("CPF inválido (confira os números digitados).")
    email, senha = validar_email(d.get("email")), validar_senha(d.get("senha"))
    usuarios = db_get(NO_USUARIOS) or {}
    if any(isinstance(p, dict) and p.get("cpf") == cpf for p in usuarios.values()):
        raise ValueError("Já existe uma conta com este CPF.")
    conta = conta_firebase("signUp", email, senha)
    perfil = {"nome": nome, "idade": idade, "cpf": cpf, "email": email, "papel": "cliente",
              "ativo": True, "criado_em": agora_txt()}
    db_put(f"{NO_USUARIOS}/{conta['localId']}", perfil)
    registrar_log(f"CADASTRO cliente {nome} <{email}>")
    return {"token": abrir_sessao(conta["localId"], perfil), "usuario": publico(conta["localId"], perfil)}


def entrar(d):
    d = d if isinstance(d, dict) else {}
    email = validar_email(d.get("email"))
    senha = str(d.get("senha") or "")
    if not senha:
        raise ValueError("Informe a senha.")
    conta = conta_firebase("signInWithPassword", email, senha)
    uid = conta["localId"]
    perfil = db_get(f"{NO_USUARIOS}/{uid}")
    if not isinstance(perfil, dict):
        raise ValueError("Conta sem perfil no sistema. Fale com o administrador.")
    if not perfil.get("ativo", True):
        raise ValueError("Seu acesso está desativado. Fale com o administrador.")
    portal = d.get("portal")
    if portal in PAPEIS and perfil.get("papel") != portal:
        # Regra: cada link de acesso só aceita contas do seu perfil
        registrar_log(f"BLOQUEADO {perfil['nome']} ({PAPEIS.get(perfil['papel'])}) tentou o portal /{portal}")
        raise SemPermissao(f"Esta área é exclusiva para {PAPEIS_PLURAL[portal]}. Sua conta é de "
                           f"{PAPEIS.get(perfil.get('papel'), '').lower()}: use o link /{perfil.get('papel')}.")
    registrar_log(f"LOGIN {perfil['nome']} ({PAPEIS.get(perfil['papel'])}) no portal /{portal or '-'}")
    return {"token": abrir_sessao(uid, perfil), "usuario": publico(uid, perfil)}


_ULTIMO_PEDIDO = {}

def esqueci_senha(d):
    """Pede ao Firebase Authentication o e-mail de redefinição de senha (em português)."""
    d = d if isinstance(d, dict) else {}
    email = validar_email(d.get("email"))
    if email == EMAIL.lower():
        raise ValueError("A senha do administrador principal é a do backend: troque no Console do Firebase "
                         "(Authentication > Users) e atualize o secret FIREBASE_SENHA no Colab.")
    if time.time() - _ULTIMO_PEDIDO.get(email, 0) < 60:
        raise ValueError("Já enviamos um link há menos de 1 minuto; confira sua caixa de entrada e o spam.")
    _ULTIMO_PEDIDO[email] = time.time()
    r = _http(requests.post, URL_AUTH + "sendOobCode", params={"key": API_KEY},
              json={"requestType": "PASSWORD_RESET", "email": email}, headers={"X-Firebase-Locale": "pt-BR"})
    if r.status_code != 200:
        try:
            codigo = r.json().get("error", {}).get("message", "")
        except ValueError:
            codigo = f"HTTP {r.status_code}"
        chave = codigo.split(" ")[0].split(":")[0]
        if chave not in ("EMAIL_NOT_FOUND", "USER_NOT_FOUND"):     # não revela se o e-mail existe
            raise ValueError(ERROS_CONTA.get(chave, "Não foi possível enviar o e-mail agora; tente mais tarde."))
    registrar_log(f"NOVA SENHA pedida para {email[:3]}***")
    return {"mensagem": "Se este e-mail estiver cadastrado, você vai receber um link para criar uma nova senha. "
                        "Confira também a caixa de spam."}


def sair():
    s = SESSOES.pop(_token_requisicao(), None)
    if s:
        registrar_log(f"SAIU {s['nome']}")
    return {}


def eu():
    u = usuario_atual()
    perfil = db_get(f"{NO_USUARIOS}/{u['uid']}") or {}
    return {"usuario": publico(u["uid"], perfil)}


# ------------------------------- CHAMADOS --------------------------------
def _hist(u, status, nota, tipo="status"):
    return {"tipo": tipo, "status": status, "nota": nota, "autor": u["nome"], "papel": u["papel"], "em": agora_txt()}


def _carregar(chave):
    chave_valida(chave)
    c = db_get(f"{NO_CHAMADOS}/{chave}")
    if not isinstance(c, dict):
        raise ValueError("Chamado não encontrado.")
    return c


def acoes_permitidas(u, c):
    """Regra central de permissões: o que este usuário pode fazer neste chamado."""
    st = c.get("status", "Aberto")
    tec = (c.get("tecnico") or {}).get("uid")
    acoes = []
    if u["papel"] == "cliente":
        if (c.get("solicitante") or {}).get("uid") == u["uid"]:
            if st != "Concluído":
                acoes.append("comentar")
            elif not c.get("avaliacao"):
                acoes += ["avaliar", "reabrir"]
        return acoes
    adm = u["papel"] == "admin"
    responsavel = bool(tec) and tec == u["uid"]
    if st != "Concluído":
        if not responsavel and (not tec or adm):
            acoes.append("assumir")
        if responsavel or adm:
            acoes += ["comentar", "concluir"]
        if tec and (responsavel or adm):
            acoes.append("devolver")
        if adm:
            acoes.append("atribuir")
    elif adm and not c.get("avaliacao"):
        acoes.append("reabrir")
    return acoes


def _exigir(acao, u, c):
    if acao not in acoes_permitidas(u, c):
        raise SemPermissao("Ação não permitida para o seu perfil neste chamado.")


def abrir_chamado(u, dados):
    if u["papel"] != "cliente":
        raise SemPermissao("Somente clientes abrem chamados.")
    perfil = db_get(f"{NO_USUARIOS}/{u['uid']}") or {}
    if not perfil.get("cpf") or not perfil.get("idade"):
        raise ValueError("Seu cadastro não tem CPF e idade; fale com o administrador.")
    c = validar_dados_chamado(dados)
    existentes = db_get(NO_CHAMADOS) or {}
    ativos = [ch for ch in existentes.values() if isinstance(ch, dict) and ch.get("status") != "Concluído"]

    # Regra 1: limite de chamados ativos por cliente
    meus = sum(1 for ch in ativos if (ch.get("solicitante") or {}).get("uid") == u["uid"])
    if meus >= MAX_ATIVOS_POR_CLIENTE:
        raise ValueError(f"Você já tem {meus} chamados em aberto; aguarde a conclusão de algum deles.")
    # Regra 2: não abrir dois chamados ativos para o mesmo patrimônio
    if c["patrimonio"]:
        for chave, ch in existentes.items():
            if isinstance(ch, dict) and ch.get("patrimonio") == c["patrimonio"] and ch.get("status") != "Concluído":
                raise ValueError(f"Já existe o chamado {protocolo(chave)} ativo para o patrimônio "
                                 f"{c['patrimonio']}. Acompanhe por ele.")
    # Regra 3: 60+ anos tem atendimento preferencial (prioridade sobe um nível)
    preferencial = int(perfil["idade"]) >= IDADE_PREFERENCIAL
    prioridade = c["prioridade"]
    if preferencial and prioridade != "Urgente":
        prioridade = PRIORIDADES[PRIORIDADES.index(prioridade) + 1]
    # Regra 4: prazo de atendimento (SLA) conforme a prioridade final
    abertura = agora()
    prazo = abertura + datetime.timedelta(hours=PRAZO_HORAS[prioridade])

    registro = {
        "solicitante": {"uid": u["uid"], "nome": perfil["nome"], "idade": perfil["idade"], "cpf": perfil["cpf"],
                        "email": perfil.get("email", "")},
        **{k: c[k] for k in ("tipo", "setor", "local", "patrimonio", "descricao")},
        "prioridade_informada": c["prioridade"], "prioridade": prioridade, "preferencial": preferencial,
        "status": "Aberto", "aberto_em": abertura.strftime(FORMATO), "prazo_em": prazo.strftime(FORMATO),
        "atualizado_em": abertura.strftime(FORMATO),
        "historico": {"abertura": _hist(u, "Aberto", "Chamado aberto pelo solicitante."
                                        + (" Atendimento preferencial (60+)." if preferencial else ""))},
    }
    chave = db_post(NO_CHAMADOS, registro)["name"]
    registrar_log(f"NOVO {protocolo(chave)} | {c['tipo']} | {prioridade} | {c['local']} | {perfil['nome']}")
    return {"chave": chave, "protocolo": protocolo(chave), "prioridade": prioridade,
            "preferencial": preferencial, "prazo": curta(registro["prazo_em"])}


def _mudar(chave, mudancas, entrada):
    mudancas["atualizado_em"] = agora_txt()
    db_patch(f"{NO_CHAMADOS}/{chave}", mudancas)
    db_post(f"{NO_CHAMADOS}/{chave}/historico", entrada)


def assumir(u, chave):
    c = _carregar(chave)
    _exigir("assumir", u, c)
    _mudar(chave, {"tecnico": {"uid": u["uid"], "nome": u["nome"]}, "status": "Em andamento"},
           _hist(u, "Em andamento", f"Atendimento assumido por {u['nome']}."))
    registrar_log(f"ASSUMIU {protocolo(chave)} | {u['nome']}")
    return {"status": "Em andamento"}


def atribuir(u, chave, tecnico_uid):
    c = _carregar(chave)
    _exigir("atribuir", u, c)
    perfil = db_get(f"{NO_USUARIOS}/{chave_valida(tecnico_uid)}")
    if not isinstance(perfil, dict) or perfil.get("papel") not in ("tecnico", "admin") or not perfil.get("ativo", True):
        raise ValueError("Escolha um técnico ativo.")
    _mudar(chave, {"tecnico": {"uid": tecnico_uid, "nome": perfil["nome"]}, "status": "Em andamento"},
           _hist(u, "Em andamento", f"Chamado atribuído a {perfil['nome']}."))
    registrar_log(f"ATRIBUIU {protocolo(chave)} -> {perfil['nome']}")
    return {"status": "Em andamento"}


def devolver(u, chave):
    c = _carregar(chave)
    _exigir("devolver", u, c)
    anterior = (c.get("tecnico") or {}).get("nome", "")
    _mudar(chave, {"tecnico": None, "status": "Aberto"},
           _hist(u, "Aberto", f"Chamado devolvido à fila (estava com {anterior})."))
    registrar_log(f"DEVOLVEU {protocolo(chave)} | {u['nome']}")
    return {"status": "Aberto"}


def concluir(u, chave, solucao):
    c = _carregar(chave)
    _exigir("concluir", u, c)
    # Regra 5: só conclui com a solução aplicada descrita
    solucao = validar_texto(solucao, 5, 300, "A solução aplicada")
    mudancas = {"status": "Concluído", "solucao": solucao, "concluido_em": agora_txt()}
    if not (c.get("tecnico") or {}).get("uid"):
        mudancas["tecnico"] = {"uid": u["uid"], "nome": u["nome"]}
    _mudar(chave, mudancas, _hist(u, "Concluído", "Solução: " + solucao))
    registrar_log(f"CONCLUIU {protocolo(chave)} | {u['nome']}")
    return {"status": "Concluído"}


def comentar(u, chave, texto):
    c = _carregar(chave)
    _exigir("comentar", u, c)
    texto = validar_texto(texto, 2, 300, "A mensagem")
    _mudar(chave, {}, _hist(u, c.get("status", "Aberto"), texto, tipo="comentario"))
    registrar_log(f"COMENTOU {protocolo(chave)} | {u['nome']}")
    return {}


def reabrir(u, chave, motivo):
    c = _carregar(chave)
    _exigir("reabrir", u, c)
    motivo = validar_texto(motivo, 5, 300, "O motivo da reabertura")
    anterior = (c.get("tecnico") or {}).get("nome", "")
    _mudar(chave, {"status": "Aberto", "tecnico": None, "solucao": None, "concluido_em": None},
           _hist(u, "Aberto", f"Chamado reaberto: {motivo}" + (f" (atendido antes por {anterior})" if anterior else "")))
    registrar_log(f"REABRIU {protocolo(chave)} | {u['nome']}")
    return {"status": "Aberto"}


def avaliar(u, chave, nota, comentario=""):
    c = _carregar(chave)
    _exigir("avaliar", u, c)
    if str(nota) not in ("1", "2", "3", "4", "5"):
        raise ValueError("Escolha de 1 a 5 estrelas.")
    nota = int(nota)
    comentario = " ".join(str(comentario or "").split())[:200]
    _mudar(chave, {"avaliacao": {"nota": nota, "comentario": comentario, "em": agora_txt()}},
           _hist(u, "Concluído", f"Avaliação: {nota}/5" + (f" · {comentario}" if comentario else ""), tipo="avaliacao"))
    registrar_log(f"AVALIOU {protocolo(chave)} | {nota}/5")
    return {}


def listar_chamados(u, status="Todos", busca="", escopo="todos"):
    """Consulta o Firebase e aplica, em Python, a visibilidade por perfil, filtros e indicadores."""
    dados = db_get(NO_CHAMADOS) or {}
    momento = agora()
    termo = " ".join(str(busca or "").lower().split())
    digitos = re.sub(r"\D", "", termo)
    contagem = {s: 0 for s in STATUS}
    resumo = {"fila": 0, "meus_ativos": 0, "meus_concluidos": 0, "aguardando_avaliacao": 0, "atrasados": 0}
    itens = []
    for chave in sorted(dados, reverse=True):              # chaves do Firebase são cronológicas
        c = dados[chave]
        if not isinstance(c, dict):
            continue
        sol, tec = c.get("solicitante") or {}, c.get("tecnico") or {}
        if u["papel"] == "cliente" and sol.get("uid") != u["uid"]:
            continue                                        # cliente só enxerga os próprios chamados
        st = c.get("status", "Aberto")
        contagem[st] = contagem.get(st, 0) + 1
        try:
            atrasado = st != "Concluído" and momento > datetime.datetime.strptime(c.get("prazo_em", ""), FORMATO)
        except ValueError:
            atrasado = False
        resumo["atrasados"] += atrasado
        resumo["fila"] += not tec.get("uid") and st != "Concluído"
        resumo["meus_ativos"] += tec.get("uid") == u["uid"] and st != "Concluído"
        resumo["meus_concluidos"] += tec.get("uid") == u["uid"] and st == "Concluído"
        resumo["aguardando_avaliacao"] += st == "Concluído" and not c.get("avaliacao")
        if escopo == "fila" and (tec.get("uid") or st == "Concluído"):
            continue
        if escopo == "meus" and tec.get("uid") != u["uid"]:
            continue
        if status in STATUS and st != status:
            continue
        texto = " ".join([protocolo(chave), str(sol.get("nome", "")), c.get("tipo", ""), c.get("local", ""),
                          c.get("setor", ""), c.get("patrimonio", ""), str(tec.get("nome", ""))]).lower()
        if termo and termo not in texto and not (len(digitos) >= 3 and digitos in re.sub(r"\D", "", str(sol.get("cpf", "")))):
            continue
        historico = sorted((h for h in (c.get("historico") or {}).values() if isinstance(h, dict)),
                           key=lambda h: h.get("em", ""))
        itens.append({
            "chave": chave, "protocolo": protocolo(chave),
            "nome": sol.get("nome", ""), "idade": sol.get("idade", ""), "cpf": mascarar_cpf(sol.get("cpf")),
            "email": sol.get("email", "") if u["papel"] != "cliente" else "",
            "tipo": c.get("tipo", ""), "setor": c.get("setor", ""), "local": c.get("local", ""),
            "patrimonio": c.get("patrimonio", ""), "prioridade": c.get("prioridade", ""),
            "prioridade_informada": c.get("prioridade_informada", ""), "preferencial": bool(c.get("preferencial")),
            "descricao": c.get("descricao", ""), "status": st, "atrasado": atrasado,
            "tecnico": tec.get("nome", ""), "solucao": c.get("solucao", ""), "avaliacao": c.get("avaliacao"),
            "aberto": curta(c.get("aberto_em")), "prazo": curta(c.get("prazo_em")),
            "atualizado": curta(c.get("atualizado_em")), "acoes": acoes_permitidas(u, c),
            "historico": [{"tipo": h.get("tipo", "status"), "status": h.get("status", ""), "nota": h.get("nota", ""),
                           "autor": h.get("autor", ""), "papel": PAPEIS.get(h.get("papel"), ""), "em": curta(h.get("em"))}
                          for h in historico],
        })
    return {"total": sum(contagem.values()), "encontrados": len(itens), "contagem": contagem,
            "resumo": resumo, "itens": itens[:80]}


# ------------------------- ADMINISTRAÇÃO -------------------------
def painel(u):
    """Indicadores gerenciais calculados em Python a partir do Firebase."""
    dados = db_get(NO_CHAMADOS) or {}
    usuarios = db_get(NO_USUARIOS) or {}
    momento = agora()
    contagem = {s: 0 for s in STATUS}
    atrasados, notas, tempos = 0, [], []
    por_tipo = collections.Counter()
    por_tecnico = {uid: {"nome": p.get("nome", ""), "ativos": 0, "concluidos": 0, "notas": []}
                   for uid, p in usuarios.items()
                   if isinstance(p, dict) and p.get("papel") == "tecnico" and p.get("ativo", True)}
    for c in dados.values():
        if not isinstance(c, dict):
            continue
        st = c.get("status", "Aberto")
        contagem[st] = contagem.get(st, 0) + 1
        por_tipo[c.get("tipo", "Outro")] += 1
        try:
            atrasados += st != "Concluído" and momento > datetime.datetime.strptime(c.get("prazo_em", ""), FORMATO)
        except ValueError:
            pass
        nota = (c.get("avaliacao") or {}).get("nota")
        if nota:
            notas.append(nota)
        if st == "Concluído":
            try:
                inicio = datetime.datetime.strptime(c.get("aberto_em", ""), FORMATO)
                fim = datetime.datetime.strptime(c.get("concluido_em", ""), FORMATO)
                tempos.append((fim - inicio).total_seconds() / 3600)
            except ValueError:
                pass
        tec = c.get("tecnico") or {}
        if tec.get("uid"):
            t = por_tecnico.setdefault(tec["uid"], {"nome": tec.get("nome", ""), "ativos": 0, "concluidos": 0, "notas": []})
            t["concluidos" if st == "Concluído" else "ativos"] += 1
            if nota:
                t["notas"].append(nota)
    media = lambda xs: round(sum(xs) / len(xs), 1) if xs else None
    papeis = collections.Counter(p.get("papel") for p in usuarios.values() if isinstance(p, dict))
    return {
        "contagem": contagem, "total": sum(contagem.values()), "atrasados": atrasados,
        "satisfacao": media(notas), "avaliacoes": len(notas),
        "tempo_medio_min": round(sum(tempos) / len(tempos) * 60) if tempos else None,
        "por_tipo": [{"tipo": t, "qtd": q} for t, q in por_tipo.most_common(6)],
        "por_tecnico": sorted(({"nome": t["nome"], "ativos": t["ativos"], "concluidos": t["concluidos"],
                                "satisfacao": media(t["notas"])} for t in por_tecnico.values()),
                              key=lambda t: (-t["concluidos"], t["nome"])),
        "usuarios": {nome: papeis.get(p, 0) for p, nome in PAPEIS.items()},
    }


def listar_usuarios(u):
    """Todos os usuários com o resumo de chamados de cada um (visão do super usuário)."""
    usuarios = db_get(NO_USUARIOS) or {}
    chamados = [c for c in (db_get(NO_CHAMADOS) or {}).values() if isinstance(c, dict)]
    ordem = {"admin": 0, "tecnico": 1, "cliente": 2}

    def resumo(uid, papel):
        if papel == "cliente":
            meus = [c for c in chamados if (c.get("solicitante") or {}).get("uid") == uid]
            ativos = sum(c.get("status") != "Concluído" for c in meus)
            return f"{ativos} ativo{'s' if ativos != 1 else ''} · {len(meus)} no total"
        meus = [c for c in chamados if (c.get("tecnico") or {}).get("uid") == uid]
        atendendo = sum(c.get("status") != "Concluído" for c in meus)
        return f"{atendendo} em atendimento · {len(meus) - atendendo} resolvido{'s' if len(meus) - atendendo != 1 else ''}"

    lista = [{"uid": uid, "nome": p.get("nome", ""), "email": p.get("email", ""), "papel": p.get("papel", ""),
              "papel_nome": PAPEIS.get(p.get("papel"), ""), "ativo": p.get("ativo", True),
              "criado": curta(p.get("criado_em")), "principal": p.get("email") == EMAIL, "voce": uid == u["uid"],
              "chamados": resumo(uid, p.get("papel"))}
             for uid, p in usuarios.items() if isinstance(p, dict)]
    lista.sort(key=lambda x: (ordem.get(x["papel"], 9), x["nome"].lower()))
    return {"usuarios": lista}


def listar_tecnicos(u):
    usuarios = db_get(NO_USUARIOS) or {}
    return {"tecnicos": sorted(({"uid": uid, "nome": p["nome"], "papel_nome": PAPEIS[p["papel"]]}
                                for uid, p in usuarios.items()
                                if isinstance(p, dict) and p.get("papel") in ("tecnico", "admin") and p.get("ativo", True)),
                               key=lambda t: t["nome"].lower())}


def criar_usuario(u, d):
    """O administrador cria contas de TÉCNICO ou de outro ADMINISTRADOR."""
    d = d if isinstance(d, dict) else {}
    nome, email, senha = validar_nome(d.get("nome")), validar_email(d.get("email")), validar_senha(d.get("senha"))
    papel = d.get("papel")
    if papel not in ("tecnico", "admin"):
        raise ValueError("Escolha o perfil: Técnico ou Administrador.")
    conta = conta_firebase("signUp", email, senha)
    db_put(f"{NO_USUARIOS}/{conta['localId']}", {"nome": nome, "email": email, "papel": papel,
                                                  "ativo": True, "criado_em": agora_txt()})
    registrar_log(f"USUÁRIO criado: {nome} ({PAPEIS[papel]}) por {u['nome']}")
    return {"uid": conta["localId"]}


def alterar_usuario(u, uid, d):
    chave_valida(uid)
    d = d if isinstance(d, dict) else {}
    perfil = db_get(f"{NO_USUARIOS}/{uid}")
    if not isinstance(perfil, dict):
        raise ValueError("Usuário não encontrado.")
    if uid == u["uid"]:
        raise ValueError("Você não pode alterar o seu próprio acesso.")
    if perfil.get("email") == EMAIL:
        raise ValueError("O administrador principal não pode ser alterado.")
    mudancas = {}
    if "papel" in d:
        if d["papel"] not in PAPEIS:
            raise ValueError("Perfil inválido.")
        if d["papel"] == "cliente" and not perfil.get("cpf"):
            raise ValueError("Esse usuário não tem CPF e idade cadastrados para ser cliente.")
        mudancas["papel"] = d["papel"]
    if "ativo" in d:
        mudancas["ativo"] = bool(d["ativo"])
    if not mudancas:
        raise ValueError("Nada para alterar.")
    db_patch(f"{NO_USUARIOS}/{uid}", mudancas)
    encerrar_sessoes(uid)                                    # a mudança vale no próximo login
    registrar_log(f"USUÁRIO alterado: {perfil.get('nome')} {mudancas} por {u['nome']}")
    return {}


# ------------------------- FRONTEND (index.html) -------------------------
FRONTEND_HTML = r'''__FRONTEND_HTML__'''


# ------------------------------- API (Flask) ------------------------------
app = Flask(__name__)
logging.getLogger("werkzeug").setLevel(logging.ERROR)


@app.after_request
def _cors_e_log(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, OPTIONS"
    if request.method != "OPTIONS" and request.path.startswith("/api") and request.args.get("auto") != "1":
        s = SESSOES.get(_token_requisicao())
        quem = f" · {s['nome']} ({PAPEIS[s['papel']]})" if s else ""
        consulta = f"?{request.query_string.decode()}" if request.query_string else ""
        registrar_log(f"{request.method} {request.path}{consulta} -> {resp.status_code}{quem}")
    return resp


def _responder(funcao, sucesso=200):
    try:
        return jsonify({"ok": True, **funcao()}), sucesso
    except NaoAutenticado as e:
        return jsonify({"ok": False, "erro": str(e), "sessao": False}), 401
    except SemPermissao as e:
        return jsonify({"ok": False, "erro": str(e)}), 403
    except ValueError as e:                      # validação / regra de negócio
        return jsonify({"ok": False, "erro": str(e)}), 400
    except RuntimeError as e:                    # erro no Firebase
        return jsonify({"ok": False, "erro": str(e)}), 502


def _corpo():
    return request.get_json(silent=True) or {}


@app.get("/")
@app.get("/cliente")
@app.get("/tecnico")
@app.get("/admin")
def rota_frontend():
    return FRONTEND_HTML, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.get("/api")
def rota_inicio():
    return jsonify({"ok": True, "servico": PROJETO, "rotas": [
        "POST /api/auth/cadastro", "POST /api/auth/login", "POST /api/auth/esqueci", "POST /api/auth/sair", "GET /api/eu",
        "GET /api/chamados", "POST /api/chamados", "POST /api/chamados/<chave>/<acao>",
        "GET /api/painel", "GET|POST /api/usuarios", "PATCH /api/usuarios/<uid>", "GET /api/tecnicos"]})


@app.get("/api/status")
def rota_status():
    def verificar():
        autenticar()
        return {"projeto": PROJETO, "equipe": EQUIPE, "firebase": "conectado"}
    return _responder(verificar)


@app.get("/api/opcoes")
def rota_opcoes():
    return jsonify({"ok": True, "tipos": TIPOS, "setores": SETORES, "prioridades": PRIORIDADES,
                    "prazos": PRAZO_HORAS, "status": STATUS, "idade_preferencial": IDADE_PREFERENCIAL,
                    "papeis": PAPEIS})


@app.post("/api/auth/cadastro")
def rota_cadastro():
    return _responder(lambda: cadastrar_cliente(_corpo()), sucesso=201)


@app.post("/api/auth/login")
def rota_login():
    return _responder(lambda: entrar(_corpo()))


@app.post("/api/auth/esqueci")
def rota_esqueci():
    return _responder(lambda: esqueci_senha(_corpo()))


@app.post("/api/auth/sair")
def rota_sair():
    return _responder(sair)


@app.get("/api/eu")
def rota_eu():
    return _responder(eu)


@app.get("/api/chamados")
def rota_listar():
    a = request.args
    return _responder(lambda: listar_chamados(usuario_atual(), a.get("status", "Todos"), a.get("busca", ""),
                                              a.get("escopo", "todos")))


@app.post("/api/chamados")
def rota_abrir():
    return _responder(lambda: abrir_chamado(usuario_atual(), _corpo()), sucesso=201)


ACOES = {
    "assumir":   lambda u, k, d: assumir(u, k),
    "atribuir":  lambda u, k, d: atribuir(u, k, d.get("tecnico_uid")),
    "devolver":  lambda u, k, d: devolver(u, k),
    "concluir":  lambda u, k, d: concluir(u, k, d.get("texto")),
    "comentar":  lambda u, k, d: comentar(u, k, d.get("texto")),
    "reabrir":   lambda u, k, d: reabrir(u, k, d.get("texto")),
    "avaliar":   lambda u, k, d: avaliar(u, k, d.get("nota"), d.get("texto", "")),
}


@app.post("/api/chamados/<chave>/<acao>")
def rota_acao(chave, acao):
    def executar():
        u = usuario_atual()
        if acao not in ACOES:
            raise ValueError("Ação desconhecida.")
        return ACOES[acao](u, chave, _corpo())
    return _responder(executar)


@app.get("/api/painel")
def rota_painel():
    return _responder(lambda: painel(requer("admin")))


@app.get("/api/usuarios")
def rota_usuarios():
    return _responder(lambda: listar_usuarios(requer("admin")))


@app.post("/api/usuarios")
def rota_criar_usuario():
    return _responder(lambda: criar_usuario(requer("admin"), _corpo()), sucesso=201)


@app.patch("/api/usuarios/<uid>")
def rota_alterar_usuario(uid):
    return _responder(lambda: alterar_usuario(requer("admin"), uid, _corpo()))


@app.get("/api/tecnicos")
def rota_tecnicos():
    return _responder(lambda: listar_tecnicos(requer("admin")))


# --------------------------- SERVIDOR E TÚNEL ----------------------------
def iniciar_servidor():
    """Sobe o Flask em segundo plano (pode rodar a célula de novo sem erro de porta)."""
    global _servidor
    antigo = globals().get("_servidor")
    if antigo:
        antigo.shutdown()
        antigo.server_close()
    _servidor = make_server("0.0.0.0", PORTA, app, threaded=True)
    threading.Thread(target=_servidor.serve_forever, daemon=True).start()


def abrir_tunel():
    """Túnel HTTPS gratuito da Cloudflare (sem cadastro) apontando para a porta do Flask."""
    global _tunel, URL_PUBLICA
    if globals().get("_tunel") is not None and _tunel.poll() is None and globals().get("URL_PUBLICA"):
        return URL_PUBLICA
    if not os.path.exists("cloudflared"):
        print("Baixando cloudflared...")
        urllib.request.urlretrieve(
            "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
            "cloudflared")
        os.chmod("cloudflared", 0o755)
    saida = open("cloudflared.log", "w")
    _tunel = subprocess.Popen(["./cloudflared", "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{PORTA}"],
                              stdout=saida, stderr=subprocess.STDOUT)
    URL_PUBLICA = None
    for _ in range(90):                          # até ~45 s
        time.sleep(0.5)
        texto = open("cloudflared.log").read()
        achou = re.search(r"https://(?!api\.)[-a-z0-9]+\.trycloudflare\.com", texto)
        if achou:
            URL_PUBLICA = achou.group(0)
        if URL_PUBLICA and "Registered tunnel connection" in texto:
            break
    if not URL_PUBLICA:
        raise RuntimeError("O túnel não respondeu. Rode a célula novamente.")
    return URL_PUBLICA


def monitor(segundos=2):
    """Mostra ao vivo as requisições que o backend recebe (interrompa com o botão ■)."""
    from IPython.display import clear_output
    try:
        while True:
            clear_output(wait=True)
            print(f"BACKEND: {globals().get('URL_PUBLICA') or f'http://127.0.0.1:{PORTA}'}"
                  f"   ·   sessões ativas: {len(SESSOES)}")
            print("Requisições recentes (navegador -> backend Python -> Firebase):\n")
            print("\n".join(list(LOG)[-25:]) or "(nenhuma ainda)")
            time.sleep(segundos)
    except KeyboardInterrupt:
        print("Monitor encerrado; o backend continua rodando.")


# ------------------------------- EXECUÇÃO --------------------------------
iniciar_servidor()
print(f"✅ Backend Flask rodando (porta {PORTA})")
with open("index.html", "w", encoding="utf-8") as arquivo:      # cópia do frontend nos arquivos do Colab (📁)
    arquivo.write(FRONTEND_HTML)
print("✅ Frontend salvo em /content/index.html (painel de arquivos do Colab)")
try:
    garantir_admin()
    ADMIN_COLAB = {"uid": _sessao["uid"], "nome": ADMIN_NOME, "email": EMAIL, "papel": "admin"}
    print(f"✅ Login no Firebase OK · administrador principal: {EMAIL}")
except Exception as erro:
    print(f"⚠️ {erro}")

if USAR_TUNEL:
    url = abrir_tunel()
    portais = [("cliente", "Acesso do cliente", "abre chamados e conversa com o técnico", "#2dd4bf"),
               ("tecnico", "Acesso do técnico", "atende a fila e fala direto com o cliente", "#38bdf8"),
               ("admin", "Acesso do administrador", "vê todas as OS, clientes e técnicos", "#fbbf24")]
    botoes = "".join(
        f'''<a href="{url}/{p}" target="_blank" style="display:block;text-decoration:none;color:#e6edf7;background:#111a2b;
            border:1px solid #2a3a55;border-top:3px solid {cor};border-radius:10px;padding:10px 12px;margin:8px 0">
            <b style="color:{cor}">{titulo}</b> · <span style="color:#8fa1bc">{desc}</span><br>
            <code style="color:#22d3ee">{url}/{p}</code></a>''' for p, titulo, desc, cor in portais)
    display(HTML(f"""
    <div style="font-family:Segoe UI,Arial,sans-serif;border:2px solid #0891b2;border-radius:12px;
                padding:14px 18px;max-width:780px;background:#0b1322;color:#e6edf7">
      <div style="font-size:13px;font-weight:600;color:#22d3ee">LINKS DE ACESSO · mande cada link para quem vai usar</div>
      {botoes}
      <div style="font-size:12.5px;margin-top:8px;color:#8fa1bc;line-height:1.5">
        Página com os três acessos: <a style="color:#22d3ee" href="{url}" target="_blank">{url}</a> ·
        administrador principal: <b>{EMAIL}</b><br>
        Se der erro logo no início, aguarde de 10 a 20 segundos (o endereço está propagando).</div>
    </div>"""))
