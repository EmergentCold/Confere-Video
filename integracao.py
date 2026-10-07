"""
ConfereVídeo · integração com o Microsoft 365 (Power Automate, SharePoint, Teams, Outlook)
==========================================================================================
O programa envia cada acontecimento para um fluxo do Power Automate:

  erro    -> item na lista de erros do SharePoint (+ foto e recorte anexados) e cartão no Teams
  sessao  -> item na lista de turnos (+ PDF do relatório) e e-mail para o gestor
  alerta  -> cartão no Teams (câmera parada / voltou)
  teste   -> cartão no Teams ("conexão funcionando")

O corpo enviado é uma mensagem válida do Teams (type=message + attachments com o cartão),
então também funciona no modelo pronto do Teams "Postar em um canal quando uma solicitação
de webhook for recebida". Os dados para o SharePoint vão no campo extra "conferevideo".

Tudo passa por uma fila em disco (pasta fila_envio): se a internet cair ou o PC reiniciar,
nada se perde e o programa reenvia sozinho.
"""
from __future__ import annotations

import base64
import json
import re
import secrets
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from html import escape
from pathlib import Path
from urllib.parse import unquote

import cv2
import numpy as np

PASTA = Path(__file__).resolve().parent
VERSAO = 1
LINK_RECORTE = "https://conferevideo.invalid/recorte"  # o fluxo troca pelo link do anexo

TIPOS = {
    "sem_leitor": "Colocou na caixa sem passar no leitor",
    "caixa_errada": "Colocou em outra caixa",
    "sem_bipe": "Passou no leitor, mas não bipou",
    "bipe_duplo": "Bipe duplo para um item",
}
TIPOS_CURTO = {"sem_leitor": "Sem passar no leitor", "caixa_errada": "Outra caixa",
               "sem_bipe": "Sem bipe", "bipe_duplo": "Bipe duplo"}
CAMPO_TIPO = {"sem_leitor": "SemLeitor", "caixa_errada": "CaixaErrada", "sem_bipe": "SemBipe",
              "bipe_duplo": "BipeDuplo"}
ORIGEM = {"ao_vivo": "Câmera ao vivo", "videos": "Vídeo gravado", "demo": "Demonstração"}
COR_HEX = {"sem_leitor": "#c2410c", "caixa_errada": "#7c3aed", "sem_bipe": "#0e7490", "bipe_duplo": "#b91c1c"}

PADRAO_M365 = {
    "ativo": False,
    "url_fluxo": "",
    "modo": "completo",            # completo = fluxo do ConfereVídeo; alerta = modelo pronto do Teams
    "chave": "",
    "site_sharepoint": "",
    "lista_erros": "ConfereVideo_Erros",
    "lista_sessoes": "ConfereVideo_Turnos",
    "emails_supervisores": "",
    "emails_gestor": "",
    "canal_teams": "",
    "link_app": "",
    "enviar_recorte": True,
    "enviar_original": False,
    "recorte_max_mb": 15,
    "avisar_videos_gravados": False,
    "enviar_demonstracao": False,
}


# =========================================================================
# utilidades
# =========================================================================
def nova_chave():
    return secrets.token_urlsafe(18)


def iso(dt: datetime | None) -> str:
    dt = dt or datetime.now()
    return dt.astimezone().isoformat(timespec="seconds")


def lista_emails(txt: str) -> str:
    """'a@x.com, b@y.com; c@z' -> 'a@x.com;b@y.com;c@z' (só o que parece e-mail)."""
    return ";".join(e for e in re.split(r"[;,\s]+", txt or "") if "@" in e)


def canal_do_link(link: str):
    """Link do canal (Teams > ... > Obter link do canal) -> (groupId, channelId)."""
    link = (link or "").strip()
    c = re.search(r"/l/channel/([^/?#]+)", link)
    g = re.search(r"groupId=([0-9a-fA-F-]{36})", link)
    return (g.group(1) if g else "", unquote(c.group(1)) if c else "")


def sigla(txt: str) -> str:
    txt = re.sub(r"\(.*?\)", "", txt or "")  # "Posto 03 (demonstração)" -> "Posto 03"
    s = re.sub(r"[^A-Za-z0-9]", "", txt.upper()
               .translate(str.maketrans("ÁÀÂÃÉÊÍÓÔÕÚÇ", "AAAAEEIOOOUC")))
    return s[:12] or "POSTO"


def b64_arquivo(p) -> str:
    return base64.b64encode(Path(p).read_bytes()).decode("ascii")


def miniatura(img_ou_caminho, largura=480, max_bytes=26000) -> str:
    """Foto pequena como data URI (cabe no cartão do Teams e numa coluna de texto do SharePoint)."""
    img = cv2.imread(str(img_ou_caminho)) if not isinstance(img_ou_caminho, np.ndarray) else img_ou_caminho
    if img is None:
        return ""
    while True:
        e = largura / img.shape[1]
        peq = cv2.resize(img, None, fx=e, fy=e, interpolation=cv2.INTER_AREA) if e < 1 else img
        for q in (78, 70, 62, 54, 46, 38):
            b = cv2.imencode(".jpg", peq, [cv2.IMWRITE_JPEG_QUALITY, q])[1].tobytes()
            if len(b) * 4 / 3 <= max_bytes:
                return "data:image/jpeg;base64," + base64.b64encode(b).decode("ascii")
        largura = int(largura * 0.8)
        if largura < 160:
            return "data:image/jpeg;base64," + base64.b64encode(b).decode("ascii")


def destino_teams(m) -> dict:
    grupo, canal = canal_do_link(m.get("canal_teams", ""))
    return {"destinatarios": lista_emails(m.get("emails_supervisores", "")), "grupo": grupo, "canal": canal}


def mensagem(cartao, dados) -> dict:
    """Corpo no formato aceito pelo gatilho de webhook do Teams."""
    return {"type": "message",
            "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "contentUrl": None,
                             "content": cartao}],
            "conferevideo": dados}


def _base(cfg, evento) -> dict:
    m = cfg.get("m365", {})
    return {"versao": VERSAO, "evento": evento, "chave": m.get("chave", ""), "enviado_em": iso(None),
            "site": m.get("site_sharepoint", "").rstrip("/"), "notificar": True,
            "teams": destino_teams(m), "anexos": []}


# =========================================================================
# cartões do Teams (Adaptive Card 1.4)
# =========================================================================
def _cartao(cabeca_estilo, sobretitulo, titulo, corpo, acoes):
    return {"type": "AdaptiveCard", "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.4", "msteams": {"width": "Full"},
            "body": [{"type": "Container", "style": cabeca_estilo, "bleed": True, "items": [
                {"type": "TextBlock", "text": sobretitulo, "size": "Small", "weight": "Bolder", "wrap": True},
                {"type": "TextBlock", "text": titulo, "size": "Large", "weight": "Bolder", "wrap": True,
                 "spacing": "Small"}]}] + corpo,
            "actions": acoes}


def _fatos(pares):
    return {"type": "FactSet", "facts": [{"title": t, "value": str(v)} for t, v in pares if v not in (None, "")]}


def _aviso_pequeno(txt):
    return {"type": "TextBlock", "text": txt, "size": "Small", "isSubtle": True, "wrap": True}


def cartao_erro(cfg, reg, foto_uri, com_recorte, demo=False, turno=""):
    m = cfg.get("m365", {})
    corpo = []
    if foto_uri:
        corpo.append({"type": "Image", "url": foto_uri, "size": "Stretch", "altText": "Foto do momento do erro"})
    corpo.append(_fatos([("Quando", reg.get("quando")), ("Posto", cfg.get("posto")), ("Unidade", cfg.get("unidade")),
                         ("Turno", turno), ("Momento no vídeo", reg.get("t_video")),
                         ("Bipes ouvidos", reg.get("bipes")), ("Código", reg.get("id"))]))
    corpo.append(_aviso_pequeno("Detecção automática: confira o recorte antes de qualquer tratativa."))
    acoes = []
    if com_recorte:
        acoes.append({"type": "Action.OpenUrl", "title": "▶ Ver recorte", "url": LINK_RECORTE})
    if (m.get("link_app") or "").startswith("https://"):
        acoes.append({"type": "Action.OpenUrl", "title": "Fazer a tratativa", "url": m["link_app"]})
    sobre = ("DEMONSTRAÇÃO · " if demo else "") + f"ERRO NA SEPARAÇÃO · {cfg.get('posto', '')}".upper()
    return _cartao("attention", sobre, TIPOS[reg["tipo"]], corpo, acoes)


def cartao_sessao(cfg, r):
    m = cfg.get("m365", {})
    c, n, ok = r["ciclos"], len(r["erros"]), r["ok"]
    taxa = f"{ok / c * 100:.1f}%".replace(".", ",") if c else "—"
    por_tipo = {}
    for e in r["erros"]:
        por_tipo[e["tipo"]] = por_tipo.get(e["tipo"], 0) + 1
    corpo = [{"type": "ColumnSet", "columns": [
        {"type": "Column", "width": "stretch", "items": [
            {"type": "TextBlock", "text": str(c), "size": "ExtraLarge", "weight": "Bolder"},
            {"type": "TextBlock", "text": "itens conferidos", "isSubtle": True, "spacing": "None"}]},
        {"type": "Column", "width": "stretch", "items": [
            {"type": "TextBlock", "text": str(n), "size": "ExtraLarge", "weight": "Bolder", "color": "Attention"},
            {"type": "TextBlock", "text": "erros com recorte", "isSubtle": True, "spacing": "None"}]},
        {"type": "Column", "width": "stretch", "items": [
            {"type": "TextBlock", "text": taxa, "size": "ExtraLarge", "weight": "Bolder", "color": "Good"},
            {"type": "TextBlock", "text": "sem erro", "isSubtle": True, "spacing": "None"}]}]}]
    if por_tipo:
        corpo.append(_fatos([(TIPOS_CURTO[k], v) for k, v in sorted(por_tipo.items(), key=lambda x: -x[1])]))
    corpo.append(_aviso_pequeno(" a ".join(p for p in r["periodo"] if p) + " · " + ORIGEM.get(r["modo"], r["modo"])))
    acoes = []
    if (m.get("link_app") or "").startswith("https://"):
        acoes.append({"type": "Action.OpenUrl", "title": "Abrir o painel", "url": m["link_app"]})
    sobre = ("DEMONSTRAÇÃO · " if r["modo"] == "demo" else "") + \
        f"FIM DE {r.get('turno') or 'SESSÃO'} · {r['posto']}".upper()
    return _cartao("emphasis", sobre, f"{n} erro{'s' if n != 1 else ''} em {c} itens", corpo, acoes)


def cartao_alerta(cfg, titulo, texto, estilo="warning"):
    corpo = [{"type": "TextBlock", "text": texto, "wrap": True},
             _fatos([("Posto", cfg.get("posto")), ("Unidade", cfg.get("unidade")),
                     ("Quando", datetime.now().strftime("%d/%m/%Y %H:%M"))])]
    return _cartao(estilo, f"CONFEREVÍDEO · {cfg.get('posto', '')}".upper(), titulo, corpo, [])


# =========================================================================
# montagem dos envios
# =========================================================================
def montar_erro(cfg, sessao, reg, foto=None, notificar=True):
    """sessao: motor.Sessao; reg: registro do erro (já com recortes gravados)."""
    m = cfg.get("m365", {})
    pasta = Path(sessao.pasta)
    foto = foto or pasta / "fotos" / f"{reg['base']}.jpg"
    demo = sessao.modo == "demo"
    dados = _base(cfg, "erro")
    dados["notificar"] = bool(notificar)
    dados["lista"] = m.get("lista_erros") or PADRAO_M365["lista_erros"]
    dados["item"] = {k: v for k, v in {
        "Title": reg["id"],
        "TipoCodigo": reg["tipo"],
        "Tipo": TIPOS_CURTO[reg["tipo"]],
        "DataHora": reg.get("quando_iso") or iso(None),
        "Unidade": cfg.get("unidade", ""),
        "Local": cfg.get("nome_local", ""),
        "Posto": cfg.get("posto", ""),
        "Turno": getattr(sessao, "turno", "") or "",
        "Origem": ORIGEM.get(sessao.modo, sessao.modo),
        "Fonte": reg.get("fonte", ""),
        "Sessao": sessao.id,
        "Bipes": reg.get("bipes"),
        "MomentoVideo": reg.get("t_video", ""),
        "Status": "Pendente",
        "Miniatura": miniatura(foto, 480, 30000) if Path(foto).exists() else "",
    }.items() if v is not None}
    anexos, com_recorte, avisos = [], False, []
    if Path(foto).exists():
        img = cv2.imread(str(foto))
        if img is not None:
            if img.shape[1] > 1280:
                img = cv2.resize(img, None, fx=1280 / img.shape[1], fy=1280 / img.shape[1])
            anexos.append({"nome": f"{reg['id']}_foto.jpg",
                           "b64": base64.b64encode(cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 82])[1]).decode()})
    limite = float(m.get("recorte_max_mb", 15)) * 1024 * 1024
    for chave, sufixo, querer in (("marcado", "recorte", m.get("enviar_recorte", True)),
                                  ("original", "original", m.get("enviar_original", False))):
        arq = reg.get(chave)
        if not (querer and arq and (pasta / arq).exists()):
            continue
        if (pasta / arq).stat().st_size > limite:
            avisos.append(f"recorte {sufixo} maior que {m.get('recorte_max_mb')} MB não enviado")
            continue
        anexos.append({"nome": f"{reg['id']}_{sufixo}.mp4", "b64": b64_arquivo(pasta / arq)})
        com_recorte = com_recorte or sufixo == "recorte"
    if m.get("modo") == "alerta":   # modelo pronto do Teams: só o cartão, sem arquivos pesados
        anexos = []
        com_recorte = False
    dados["anexos"] = anexos
    dados["avisos"] = avisos
    turno = getattr(sessao, "turno", "")
    cartao = cartao_erro(cfg, reg, miniatura(foto, 480, 18000) if Path(foto).exists() else "", com_recorte, demo, turno)
    if len(json.dumps(cartao, ensure_ascii=False).encode()) > 26000:  # limite do Teams: ~28 KB por mensagem
        cartao = cartao_erro(cfg, reg, "", com_recorte, demo, turno)
    return mensagem(cartao, dados)


def montar_sessao(cfg, sessao, pdf=None):
    m = cfg.get("m365", {})
    r = sessao.resumo()
    dados = _base(cfg, "sessao")
    dados["lista"] = m.get("lista_sessoes") or PADRAO_M365["lista_sessoes"]
    cont = {k: 0 for k in TIPOS}
    for e in r["erros"]:
        cont[e["tipo"]] += 1
    c, ok = r["ciclos"], r["ok"]
    dados["item"] = {k: v for k, v in {
        "Title": sessao.id,
        "Inicio": iso(sessao.periodo[0] or sessao.inicio),
        "Fim": iso(sessao.periodo[1] or getattr(sessao, "fim", None) or datetime.now()),
        "Unidade": cfg.get("unidade", ""),
        "Local": cfg.get("nome_local", ""),
        "Posto": cfg.get("posto", ""),
        "Turno": getattr(sessao, "turno", "") or "",
        "Origem": ORIGEM.get(sessao.modo, sessao.modo),
        "Itens": c,
        "Erros": len(r["erros"]),
        "ItensSemErro": ok,
        "PctSemErro": round(ok / c * 100, 1) if c else None,
        **{CAMPO_TIPO[k]: v for k, v in cont.items()},
    }.items() if v is not None}
    if pdf and Path(pdf).exists() and m.get("modo") != "alerta":
        dados["anexos"] = [{"nome": f"Relatorio_{sessao.id}.pdf", "b64": b64_arquivo(pdf)}]
    para = lista_emails(m.get("emails_gestor", ""))
    if para:
        assunto = (f"ConfereVídeo · {cfg.get('posto')} · {getattr(sessao, 'turno', '') or 'sessão'} "
                   f"{sessao.inicio:%d/%m}: {len(r['erros'])} erro{'' if len(r['erros']) == 1 else 's'} em {c} itens")
        if sessao.modo == "demo":
            assunto = "[DEMONSTRAÇÃO] " + assunto
        dados["email"] = {"para": para, "assunto": assunto, "html": email_sessao_html(cfg, r)}
    return mensagem(cartao_sessao(cfg, r), dados)


def montar_alerta(cfg, titulo, texto, estilo="warning", por_email=True):
    m = cfg.get("m365", {})
    dados = _base(cfg, "alerta")
    para = lista_emails(m.get("emails_supervisores", ""))
    if por_email and para:
        dados["email"] = {"para": para, "assunto": f"ConfereVídeo · {cfg.get('posto')}: {titulo}",
                          "html": email_simples_html(cfg, titulo, texto)}
    return mensagem(cartao_alerta(cfg, titulo, texto, estilo), dados)


def montar_teste(cfg):
    dados = _base(cfg, "teste")
    return mensagem(cartao_alerta(cfg, "Conexão funcionando ✓",
                                  "Este é um teste do ConfereVídeo. Os erros deste posto vão aparecer aqui.", "good"),
                    dados)


# =========================================================================
# e-mails (HTML com estilo embutido: abre bem no Outlook)
# =========================================================================
_TD = "padding:6px 10px;border-bottom:1px solid #e3e7ee;font:14px Segoe UI,Arial,sans-serif;color:#16202e"


def _casca(cfg, titulo, sub, miolo):
    return f"""<div style="background:#f4f6f9;padding:20px 0">
<table role="presentation" cellpadding="0" cellspacing="0" width="640" align="center" style="background:#ffffff;border:1px solid #e3e7ee;border-collapse:collapse">
<tr><td style="background:#16202e;padding:18px 22px">
<div style="font:12px Segoe UI,Arial,sans-serif;letter-spacing:.1em;color:#9fb3cc;text-transform:uppercase">{escape(cfg.get('empresa', ''))} · {escape(cfg.get('unidade', ''))}</div>
<div style="font:bold 20px Segoe UI,Arial,sans-serif;color:#ffffff;margin-top:4px">{escape(titulo)}</div>
<div style="font:14px Segoe UI,Arial,sans-serif;color:#c9d5e3;margin-top:2px">{escape(sub)}</div></td></tr>
<tr><td style="padding:18px 22px">{miolo}</td></tr>
<tr><td style="padding:12px 22px;border-top:1px solid #e3e7ee;font:12px Segoe UI,Arial,sans-serif;color:#5b6678">
Enviado automaticamente pelo ConfereVídeo. Detecção automática por vídeo: confirme cada recorte antes de qualquer tratativa.</td></tr>
</table></div>"""


def email_sessao_html(cfg, r):
    m = cfg.get("m365", {})
    c, n, ok = r["ciclos"], len(r["erros"]), r["ok"]
    taxa = f"{ok / c * 100:.1f}%".replace(".", ",") if c else "—"

    def kpi(v, rot, cor):
        return (f'<td width="33%" style="padding:12px;border:1px solid #e3e7ee;text-align:left">'
                f'<div style="font:bold 28px Segoe UI,Arial,sans-serif;color:{cor}">{v}</div>'
                f'<div style="font:12px Segoe UI,Arial,sans-serif;color:#5b6678;text-transform:uppercase;letter-spacing:.06em">{rot}</div></td>')
    kpis = (f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse"><tr>'
            f'{kpi(c, "Itens conferidos", "#16202e")}{kpi(n, "Erros com recorte", "#b91c1c")}'
            f'{kpi(taxa, "Itens sem erro", "#15803d")}</tr></table>')
    cont = {}
    for e in r["erros"]:
        cont[e["tipo"]] = cont.get(e["tipo"], 0) + 1
    maxc = max(cont.values()) if cont else 1
    barras = "".join(
        f'<tr><td style="{_TD};width:52%">{escape(TIPOS[k])}</td><td style="{_TD}">'
        f'<div style="background:{COR_HEX.get(k, "#b91c1c")};height:10px;width:{max(4, int(v / maxc * 180))}px"></div></td>'
        f'<td style="{_TD};text-align:right;font-weight:bold">{v}</td></tr>'
        for k, v in sorted(cont.items(), key=lambda x: -x[1]))
    linhas = "".join(
        f'<tr><td style="{_TD}">{e["n"]}</td><td style="{_TD}">{escape(e["quando"][-8:] or e.get("t_video", ""))}</td>'
        f'<td style="{_TD}">{escape(TIPOS_CURTO[e["tipo"]])}</td>'
        f'<td style="{_TD};text-align:right">{"" if e.get("bipes") is None else e["bipes"]}</td></tr>'
        for e in r["erros"][:40])
    mais = f'<p style="font:13px Segoe UI,Arial,sans-serif;color:#5b6678">e mais {n - 40} erros no PDF anexo.</p>' if n > 40 else ""
    th = "padding:6px 10px;border-bottom:2px solid #16202e;font:bold 12px Segoe UI,Arial,sans-serif;color:#5b6678;text-align:left;text-transform:uppercase"
    tabela = (f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;margin-top:6px">'
              f'<tr><th style="{th}">Nº</th><th style="{th}">Hora</th><th style="{th}">Erro</th><th style="{th};text-align:right">Bipes</th></tr>'
              f'{linhas}</table>{mais}') if n else \
        '<p style="font:14px Segoe UI,Arial,sans-serif;color:#15803d">Nenhum erro neste período.</p>'
    h2 = "font:bold 13px Segoe UI,Arial,sans-serif;color:#5b6678;text-transform:uppercase;letter-spacing:.06em;margin:22px 0 6px"
    botao = ""
    if (m.get("link_app") or "").startswith("https://"):
        botao = (f'<p style="margin:22px 0 0"><a href="{escape(m["link_app"])}" style="background:#0f4c81;color:#ffffff;'
                 f'font:bold 14px Segoe UI,Arial,sans-serif;padding:10px 18px;text-decoration:none;border-radius:4px">'
                 f'Abrir o painel de tratativas</a></p>')
    miolo = (kpis + (f'<div style="{h2}">Erros por tipo</div><table role="presentation" width="100%" '
                     f'cellspacing="0" cellpadding="0" style="border-collapse:collapse">{barras}</table>' if cont else "")
             + f'<div style="{h2}">Erros do turno</div>{tabela}'
             + '<p style="font:13px Segoe UI,Arial,sans-serif;color:#5b6678;margin-top:16px">O relatório completo, '
               'com a foto de cada erro, está no PDF anexo. Os recortes em vídeo ficam na lista do SharePoint.</p>' + botao)
    per = " a ".join(p for p in r["periodo"] if p)
    sub = f"{r['posto']} · {r.get('turno') or ORIGEM.get(r['modo'], '')} · {per}"
    return _casca(cfg, "Resumo da conferência da separação", sub, miolo)


def email_simples_html(cfg, titulo, texto):
    miolo = f'<p style="font:15px Segoe UI,Arial,sans-serif;color:#16202e;margin:0">{escape(texto)}</p>'
    return _casca(cfg, titulo, f"{cfg.get('posto', '')} · {datetime.now():%d/%m/%Y %H:%M}", miolo)


# =========================================================================
# envio com fila em disco
# =========================================================================
def enviar_http(url, corpo: dict, timeout=120):
    dados = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=dados, method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8",
                                          "User-Agent": "ConfereVideo/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return True, r.status, r.read(2000).decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        try:
            txt = e.read(2000).decode("utf-8", "ignore")
        except Exception:
            txt = ""
        return False, e.code, txt
    except Exception as e:  # sem internet, DNS, proxy, tempo esgotado...
        return False, 0, str(e)


def url_valida(url: str) -> bool:
    url = (url or "").strip()
    return url.startswith("https://") or url.startswith(("http://127.0.0.1", "http://localhost"))


def explicar(status, txt):
    if status == 0:
        return f"sem conexão com a internet ou o endereço não responde ({txt[:120]})"
    return {400: "o fluxo recusou os dados (400)", 401: "o fluxo pede login: no gatilho, escolha 'Qualquer pessoa' (401)",
            403: "acesso negado pelo fluxo (403)", 404: "endereço do fluxo não encontrado: confira a URL (404)",
            413: "envio grande demais para o fluxo (413)", 429: "muitos envios seguidos, aguardando (429)"}.get(
        status, f"o fluxo respondeu com erro {status}")


class Integracao:
    """Fila de envios para o Power Automate. Seguro para usar de várias threads."""

    PERMANENTES = (400, 413)

    def __init__(self, obter_cfg, pasta=None, log=None):
        self.obter_cfg = obter_cfg
        self.pasta = Path(pasta or PASTA / "fila_envio")
        (self.pasta / "falhou").mkdir(parents=True, exist_ok=True)
        self.log = log or (lambda msg: None)
        self._acorda, self._parar = threading.Event(), threading.Event()
        self._thread = None
        self.ultimo_ok = None
        self.ultimo_erro = ""
        self.enviados = 0
        self._espera = 0

    # ---- estado ----
    @property
    def m(self):
        return (self.obter_cfg() or {}).get("m365", {}) or {}

    def ativo(self):
        m = self.m
        return bool(m.get("ativo")) and url_valida(str(m.get("url_fluxo", "")))

    def pendentes(self):
        return len(list(self.pasta.glob("*.json")))

    def falhas(self):
        return len(list((self.pasta / "falhou").glob("*.json")))

    def resumo_estado(self):
        if not self.ativo():
            return "Microsoft 365 desligado"
        p = self.pendentes()
        txt = "Microsoft 365 ligado"
        if self.ultimo_ok:
            txt += f" · último envio {self.ultimo_ok:%H:%M}"
        if p:
            txt += f" · {p} na fila"
        if self.ultimo_erro and p:
            txt += f" · {self.ultimo_erro}"
        return txt

    # ---- ciclo de vida ----
    def iniciar(self):
        if self._thread is None or not self._thread.is_alive():
            self._parar.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True, name="envio-m365")
            self._thread.start()
        self._acorda.set()

    def parar(self):
        self._parar.set()
        self._acorda.set()

    def reenviar_falhas(self):
        n = 0
        for f in (self.pasta / "falhou").glob("*.json"):
            f.replace(self.pasta / f.name)
            n += 1
        self._espera = 0
        self._acorda.set()
        return n

    # ---- eventos ----
    def _pode(self, modo):
        if not self.ativo():
            return False
        if modo == "demo" and not self.m.get("enviar_demonstracao"):
            return False
        return True

    def erro(self, cfg, sessao, reg):
        if not self._pode(sessao.modo):
            return None
        notificar = sessao.modo != "videos" or bool(self.m.get("avisar_videos_gravados"))
        try:
            return self.enfileirar(montar_erro(cfg, sessao, reg, notificar=notificar), f"erro_{reg.get('id', '')}")
        except Exception as e:
            self.log(f"Microsoft 365: não consegui preparar o envio do erro ({e})")

    def sessao(self, cfg, sessao, pdf=None):
        if not self._pode(sessao.modo):
            return None
        if not sessao.ciclos and not sessao.erros:   # turno sem movimento: não manda e-mail vazio
            self._registrar(f"resumo {sessao.id} sem itens: não enviado")
            return None
        try:
            return self.enfileirar(montar_sessao(cfg, sessao, pdf), f"sessao_{sessao.id}")
        except Exception as e:
            self.log(f"Microsoft 365: não consegui preparar o resumo ({e})")

    def alerta(self, cfg, titulo, texto, estilo="warning"):
        if not self.ativo():
            return None
        return self.enfileirar(montar_alerta(cfg, titulo, texto, estilo), "alerta")

    def testar(self, cfg=None):
        """Envio direto (sem fila) para o botão 'Testar envio'."""
        cfg = cfg or self.obter_cfg()
        url = str(cfg.get("m365", {}).get("url_fluxo", "")).strip()
        if not url_valida(url):
            return False, "Cole o endereço (URL) do fluxo, que começa com https://"
        ok, st, txt = enviar_http(url, montar_teste(cfg), timeout=40)
        return ok, ("Enviado. Confira o Teams em alguns segundos." if ok else explicar(st, txt))

    def enfileirar(self, corpo, nome="envio"):
        nome = re.sub(r"[^A-Za-z0-9_-]", "", nome)[:60]
        arq = self.pasta / f"{time.time_ns()}_{nome}.json"
        tmp = arq.with_suffix(".tmp")
        tmp.write_text(json.dumps(corpo, ensure_ascii=False), encoding="utf-8")
        tmp.replace(arq)
        self._acorda.set()
        return arq

    def _registrar(self, linha):
        try:
            with open(self.pasta / "envios.log", "a", encoding="utf-8") as f:
                f.write(f"{datetime.now():%d/%m/%Y %H:%M:%S}  {linha}\n")
        except Exception:
            pass

    def processar_fila(self):
        """Envia o que estiver na fila. Retorna True se esvaziou."""
        url = str(self.m.get("url_fluxo", "")).strip()
        for arq in sorted(self.pasta.glob("*.json")):
            if self._parar.is_set():
                return False
            try:
                corpo = json.loads(arq.read_text(encoding="utf-8"))
            except Exception:
                arq.replace(self.pasta / "falhou" / arq.name)
                continue
            ok, st, txt = enviar_http(url, corpo)
            if ok:
                arq.unlink(missing_ok=True)
                self.enviados += 1
                self.ultimo_ok, self.ultimo_erro, self._espera = datetime.now(), "", 0
                self._registrar(f"OK {st}  {arq.name}")
                continue
            msg = explicar(st, txt)
            self._registrar(f"FALHOU {st}  {arq.name}  {msg}")
            if st in self.PERMANENTES:
                arq.replace(self.pasta / "falhou" / arq.name)
                self.ultimo_erro = msg
                self.log(f"Microsoft 365: {msg}. O envio foi separado na pasta fila_envio/falhou.")
                continue
            self.ultimo_erro = msg
            self._espera = min(900, max(30, self._espera * 2))
            self.log(f"Microsoft 365: {msg}. Tento de novo em {self._espera} s.")
            return False
        return True

    def _loop(self):
        while not self._parar.is_set():
            self._acorda.wait(timeout=self._espera or 30)
            self._acorda.clear()
            if self._parar.is_set():
                break
            if self.ativo() and self.pendentes():
                self.processar_fila()
