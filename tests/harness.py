"""Sobe o backend real (Flask) com Firebase Authentication e Realtime Database simulados em memória.

Nenhuma credencial real é usada: os valores abaixo são falsos e o Firebase é imitado.
"""
import sys, json, itertools, os, tempfile
from pathlib import Path
import requests, IPython.display

ADMIN_EMAIL, ADMIN_SENHA = "admin@exemplo.com", "senha-admin-teste"
BASE = "https://projeto-teste-default-rtdb.firebaseio.com/"
os.environ.update(FIREBASE_API_KEY="chave-de-teste", FIREBASE_DATABASE_URL=BASE.rstrip("/"),
                  FIREBASE_EMAIL=ADMIN_EMAIL, FIREBASE_SENHA=ADMIN_SENHA)
db = {}
contas = {ADMIN_EMAIL: {"senha": ADMIN_SENHA, "uid": "uidADMIN0001"}}
estado = {"negar": False}
seq = itertools.count(1)
TOKEN_BACKEND = "tok-backend"

class Resp:
    def __init__(self, code, data): self.status_code, self._d = code, data; self.text = json.dumps(data)
    def json(self): return self._d

def _partes(url):
    assert url.startswith(BASE) and url.endswith(".json"), url
    return [p for p in url[len(BASE):-5].split("/") if p]

def _no(partes, criar=False):
    atual = db
    for p in partes:
        if not isinstance(atual, dict): return None
        if p not in atual:
            if not criar: return None
            atual[p] = {}
        atual = atual[p]
    return atual

def _auth_ok(params): return not estado["negar"] and params and params.get("auth") == TOKEN_BACKEND

EMAILS_ENVIADOS = []

def fake_post(url, timeout=None, params=None, json=None, headers=None):
    if "identitytoolkit" in url:
        email, senha = json["email"], json.get("password")
        if url.endswith("signInWithPassword"):
            c = contas.get(email)
            if c and c["senha"] == senha:
                tok = TOKEN_BACKEND if email == ADMIN_EMAIL else "tok-" + c["uid"]
                return Resp(200, {"idToken": tok, "expiresIn": "3600", "localId": c["uid"]})
            return Resp(400, {"error": {"message": "INVALID_LOGIN_CREDENTIALS"}})
        if url.endswith("sendOobCode"):
            assert json["requestType"] == "PASSWORD_RESET"
            if email not in contas: return Resp(400, {"error": {"message": "EMAIL_NOT_FOUND"}})
            EMAILS_ENVIADOS.append((email, (headers or {}).get("X-Firebase-Locale"))); return Resp(200, {"email": email})
        if url.endswith("signUp"):
            if email in contas: return Resp(400, {"error": {"message": "EMAIL_EXISTS"}})
            if len(senha) < 6: return Resp(400, {"error": {"message": "WEAK_PASSWORD : Password should be at least 6 characters"}})
            uid = f"uid{next(seq):09d}"; contas[email] = {"senha": senha, "uid": uid}
            return Resp(200, {"idToken": "tok-" + uid, "expiresIn": "3600", "localId": uid})
        raise AssertionError(url)
    if not _auth_ok(params): return Resp(401, {"error": "Permission denied"})
    n = next(seq); chave = f"-OZ{n:08d}ab{chr(65 + n % 26)}{n:05d}"
    _no(_partes(url), criar=True)[chave] = json
    return Resp(200, {"name": chave})

def fake_get(url, timeout=None, params=None):
    if not _auth_ok(params): return Resp(401, {"error": "Permission denied"})
    v = _no(_partes(url))
    return Resp(200, v if v != {} else None)

def fake_put(url, timeout=None, params=None, json=None):
    if not _auth_ok(params): return Resp(401, {"error": "Permission denied"})
    partes = _partes(url); pai = _no(partes[:-1], criar=True); pai[partes[-1]] = json
    return Resp(200, json)

def fake_patch(url, timeout=None, params=None, json=None):
    if not _auth_ok(params): return Resp(401, {"error": "Permission denied"})
    no = _no(_partes(url), criar=True)
    for k, v in json.items():
        if v is None: no.pop(k, None)
        else: no[k] = v
    return Resp(200, json)

requests.post, requests.get, requests.put, requests.patch = fake_post, fake_get, fake_put, fake_patch
IPython.display.display = lambda obj: None

RAIZ = Path(__file__).resolve().parents[1]
codigo = (RAIZ / "src" / "backend_template.py").read_text(encoding="utf-8").replace(
    "__FRONTEND_HTML__", (RAIZ / "src" / "index.html").read_text(encoding="utf-8"))
codigo = codigo.replace("USAR_TUNEL   = True", "USAR_TUNEL   = False").replace("PORTA        = 5000", "PORTA        = 5077")
os.chdir(tempfile.mkdtemp())        # o backend grava uma cópia do index.html na pasta atual
ns = {"__name__": "backend"}
exec(compile(codigo, "backend.py", "exec"), ns)
API = "http://127.0.0.1:5077"
