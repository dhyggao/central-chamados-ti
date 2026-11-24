"""Teste ponta a ponta no navegador (Playwright): portais, temas e acessibilidade.

    pip install playwright && playwright install chromium
    python tests/test_ui.py      (capturas de tela em tests/saida/)
"""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import os
from harness import *
import harness as harness4
from playwright.sync_api import sync_playwright
SAIDA = RAIZ / "tests" / "saida"; SAIDA.mkdir(exist_ok=True)
erros = []
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=os.environ.get("CHROME_PATH") or None)
    ctx = b.new_context(viewport={"width": 1400, "height": 900}, device_scale_factor=1.3)
    pg = ctx.new_page(); pg.on("pageerror", lambda e: erros.append(str(e)))

    def tema(t=None, cores=None, texto=None):
        pg.click("#btn-aparencia"); pg.wait_for_selector("#menu-aparencia:not([hidden])")
        if t: pg.click(f".seg[data-grupo=tema] [data-valor={t}]")
        if cores: pg.click(f".seg[data-grupo=cores] [data-valor={cores}]")
        if texto: pg.click(f".seg[data-grupo=texto] [data-valor={texto}]")
        pg.keyboard.press("Escape"); pg.wait_for_timeout(150)
    def msg_login(): pg.wait_for_selector("#login-msg:not([hidden])"); return pg.inner_text("#login-msg")
    def login(email, senha, esperar=True):
        pg.fill("#l-email", email); pg.fill("#l-senha", senha); pg.click("#b-entrar")
        if esperar: pg.wait_for_selector("#tela-app:not([hidden])"); pg.wait_for_timeout(400)
    def sair(): pg.click("#sair"); pg.wait_for_selector("#tela-login:not([hidden])")
    def linha(t): return pg.locator("#lista tr.ch", has_text=t).first
    def acao(rot): pg.locator("tr.det button", has_text=rot).first.click(); pg.wait_for_timeout(700)

    # --- página inicial com os três acessos
    pg.goto(API + "/"); pg.wait_for_selector(".pilula.ok")
    print("Cartões:", pg.locator(".portal h2").all_inner_texts(), "| links:", pg.locator(".portal .link").all_inner_texts())
    pg.screenshot(path=str(SAIDA / "01_inicio_escuro.png"))
    tema("claro"); pg.screenshot(path=str(SAIDA / "02_inicio_claro.png"))
    pg.click("#btn-aparencia"); pg.wait_for_timeout(150); pg.screenshot(path=str(SAIDA / "03_menu_aparencia.png")); pg.keyboard.press("Escape")

    # --- admin cria técnico; técnico não entra no /admin
    pg.goto(API + "/admin"); pg.wait_for_selector("#tela-login:not([hidden])")
    print("Admin: abas de cadastro visíveis?", pg.is_visible("#abas-login"), "| título:", pg.inner_text("#login-titulo"))
    login("admin@exemplo.com", "senha-admin-teste")
    pg.click("#abas [data-vista=usuarios]"); pg.wait_for_selector("#lista-usuarios tr")
    pg.fill("#n-nome", "Carlos Souza"); pg.fill("#n-email", "carlos@ciesa.br"); pg.fill("#n-senha", "tecnico123"); pg.click("#b-criar"); pg.wait_for_selector("#msg-usuario.ok")
    sair()
    login("carlos@ciesa.br", "tecnico123", esperar=False); print("Técnico no /admin ->", msg_login())

    # --- cliente: cadastro, chamado, esqueci a senha
    pg.goto(API + "/cliente"); pg.wait_for_selector("#tela-login:not([hidden])")
    print("Cliente: abas de cadastro visíveis?", pg.is_visible("#abas-login"))
    pg.screenshot(path=str(SAIDA / "04_login_cliente_claro.png"))
    pg.click("#abas-login [data-aba=cadastro]"); pg.fill("#c-nome", "Maria da Silva"); pg.fill("#c-idade", "32"); pg.type("#c-cpf", "52998224725")
    pg.fill("#c-email", "maria@ciesa.br"); pg.fill("#c-senha", "maria123"); pg.click("#b-cadastrar"); pg.wait_for_selector("#tela-app:not([hidden])")
    pg.select_option("#tipo", "Impressora / scanner"); pg.select_option("#setor", "Biblioteca"); pg.fill("#local", "Balcão de empréstimo")
    pg.fill("#descricao", "Impressora puxa duas folhas e trava com erro E02."); pg.click("#enviar"); pg.wait_for_selector("#msg.ok")
    pg.select_option("#tipo", "Rede / internet / Wi-Fi"); pg.select_option("#setor", "Laboratório de informática"); pg.fill("#local", "Laboratório 03")
    pg.click("#prios label:has(input[value='Urgente'])"); pg.fill("#descricao", "Sem internet em todo o laboratório 03."); pg.click("#enviar")
    pg.wait_for_function("document.querySelectorAll('#lista tr.ch').length == 2")
    sair()
    pg.click("#ir-esqueci"); pg.fill("#e-email", "maria@ciesa.br"); pg.click("#b-esqueci"); print("Esqueci ->", msg_login(), "| e-mails:", harness4.EMAILS_ENVIADOS)
    pg.screenshot(path=str(SAIDA / "05_esqueci_claro.png"))
    pg.click("#voltar-login")
    login("carlos@ciesa.br", "tecnico123", esperar=False); print("Técnico no /cliente ->", msg_login())

    # --- técnico atende (tema claro e depois alto contraste)
    pg.goto(API + "/tecnico"); pg.wait_for_selector("#tela-login:not([hidden])")
    login("carlos@ciesa.br", "tecnico123")
    linha("Impressora").click(); acao("Assumir chamado")
    pg.fill("tr.det textarea", "Vou passar no balcão às 14h para verificar o rolete."); acao("Enviar mensagem")
    print("Técnico vê contato:", pg.locator("tr.det dd a").inner_text())
    pg.screenshot(path=str(SAIDA / "06_tecnico_claro.png"), full_page=True)
    tema("contraste"); pg.screenshot(path=str(SAIDA / "07_tecnico_contraste.png"), full_page=True)
    tema("escuro", "dalt"); pg.click("[data-escopo=todos]"); pg.wait_for_timeout(600); pg.screenshot(path=str(SAIDA / "08_tecnico_daltonismo.png"), full_page=True)
    pg.fill("tr.det textarea", "Rolete de tração limpo e papel realinhado; testada com 20 impressões."); acao("Concluir com esta solução")

    # --- dois portais abertos ao mesmo tempo no mesmo navegador
    pg2 = ctx.new_page(); pg2.on("pageerror", lambda e: erros.append(str(e)))
    pg2.goto(API + "/cliente"); pg2.wait_for_selector("#tela-login:not([hidden])")
    pg2.fill("#l-email", "maria@ciesa.br"); pg2.fill("#l-senha", "maria123"); pg2.click("#b-entrar"); pg2.wait_for_selector("#tela-app:not([hidden])")
    pg2.locator("#lista tr.ch", has_text="Impressora").click(); pg2.locator("tr.det .estrela").nth(4).click(); pg2.locator("tr.det button", has_text="Enviar avaliação").click(); pg2.wait_for_timeout(700)
    pg.reload(); pg.wait_for_selector("#tela-app:not([hidden])")
    print("Técnico continua logado na outra aba:", pg.inner_text("#u-nome"), "| cliente:", pg2.inner_text("#u-nome"))
    tema("claro", "padrao"); pg2.reload(); pg2.wait_for_selector("#tela-app:not([hidden])"); pg2.wait_for_timeout(500)
    pg2.locator("#lista tr.ch", has_text="Rede").click(); pg2.wait_for_timeout(300)
    pg2.screenshot(path=str(SAIDA / "09_cliente_claro.png"), full_page=True)

    # --- admin: clientes e técnicos, Ver OS, texto grande
    pg.goto(API + "/admin"); pg.wait_for_selector("#tela-login:not([hidden])"); login("admin@exemplo.com", "senha-admin-teste")
    pg.click("#abas [data-vista=usuarios]"); pg.wait_for_selector("#lista-usuarios tr")
    print("Usuários:", [r.split("\t")[0].split("\n")[0] + " | " + r.split("\t")[3] for r in pg.locator("#lista-usuarios tr").all_inner_texts()])
    pg.click("[data-papel=cliente]"); print("Filtro clientes:", pg.locator("#lista-usuarios tr").count())
    pg.screenshot(path=str(SAIDA / "10_admin_usuarios_claro.png"), full_page=True)
    pg.locator("#lista-usuarios tr", has_text="Maria").locator("button", has_text="Ver OS").click(); pg.wait_for_timeout(600)
    print("Ver OS da Maria:", pg.locator("#lista tr.ch").count(), "chamados | busca:", pg.input_value("#busca"))
    tema(texto="grande"); pg.click("#abas [data-vista=painel]"); pg.wait_for_timeout(600)
    pg.screenshot(path=str(SAIDA / "11_admin_painel_texto_grande.png"), full_page=True)
    tema("escuro", texto="normal")
    b.close()
print("Erros JS:", erros or "nenhum")
