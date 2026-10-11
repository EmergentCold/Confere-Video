"""Gera a demonstração ilustrativa da estação de picking de 3 níveis (vídeo + áreas).

Cena desenhada a partir das fotos da operação: prateleira com vigas laranja e colunas azuis em
3 níveis (ombro, cintura e abaixo da cintura) com caixas abertas de pacotes, esteira de roletes
por gravidade, monitor no braço articulado com o leitor de mão e tapete preto do operador.

O operador mostra o QR do crachá no começo (crachá simulado) e separa 12 itens. Quatro deles
têm erros encenados, um de cada tipo. A legenda embaixo diz o que foi encenado, para comparar
com o que a IA encontrou.

    python demo/gerar_demo_3_niveis.py            -> demo/demo_esteira_3_niveis.mp4 + areas_demo_3_niveis.yaml
"""
import base64
import json
import math
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import cv2
import numpy as np
import yaml
from PIL import Image, ImageDraw, ImageFont

PASTA = Path(__file__).resolve().parent
sys.path.insert(0, str(PASTA.parent))
from motor import ffmpeg_exe  # noqa: E402

W, H, FPS = 1280, 720, 30
SR = 16000
BIPE_HZ = 2700

# ------------------------------------------------------------------ cores (BGR)
def bgr(h):
    h = h.lstrip("#")
    return (int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16))


AZUL_RACK, LARANJA, PAPELAO, PAPELAO_ESC, PAPELAO_INT = bgr("#1f4fa3"), bgr("#e8691c"), bgr("#c9a26f"), bgr("#a8814f"), bgr("#6e5232")
MARINHO, COLETE, PELE, CAPACETE = bgr("#1d2b4f"), bgr("#e9d21f"), bgr("#d9a77f"), bgr("#f4f4f4")
LUVA, BOTA, CALCA, FAIXA = bgr("#f07c1a"), bgr("#202020"), bgr("#2a2f3a"), bgr("#e6e6e6")
PACOTES = [("#c8202a", "#ffffff"), ("#1d4f9c", "#ffffff"), ("#d4a417", "#ffffff"), ("#1f7a4a", "#ffffff"),
           ("#6a2c8a", "#ffffff"), ("#b0b0b0", "#c8202a"), ("#e3e3e3", "#1d4f9c"), ("#8a1c1c", "#d4a417")]

# ------------------------------------------------------------------ geometria da cena (pixels)
X_OP = 560                              # centro do operador
PASSO = 190                             # passo para o lado até a caixa do pedido vizinho
QUADRIL_Y = 440
PRAT_X0, PRAT_X1 = 805, 1268
DX = 0                                   # monitor e leitor, afastados da caixa ao lado
NIVEIS = {  # nome, (topo das caixas, viga)
    1: ("NÍVEL 1 · OMBRO", 186, 262),
    2: ("NÍVEL 2 · CINTURA", 338, 412),
    3: ("NÍVEL 3 · ABAIXO DA CINTURA", 492, 566),
}
NOME_NIVEL = {1: "Nível 1 (ombro)", 2: "Nível 2 (cintura)", 3: "Nível 3 (abaixo da cintura)"}
ESTEIRA_Y = 466                          # face de cima dos roletes
CAIXAS = {  # x0, x1 (fundo em ESTEIRA_Y, altura 96); as de outros pedidos ficam antes, na esteira
    "outra_esq2": (150, 300), "outra_esq": (316, 470), "posto": (480, 640),
}
ETIQUETA = {"outra_esq2": "PED 4523", "outra_esq": "PED 4522", "posto": "PED 4521"}
CAIXA_ALT = 96
LEITOR = (726 + DX, 282)                     # onde a mão apresenta o item ao leitor

ALVOS = {
    "repouso": (628, 406),
    "leitor": LEITOR,
    "posto": (604, 392),
    "outra_esq": (394, 394),
    1: (862, 226), 2: (866, 376), 3: (842, 524),
}
POSTURA = {1: (8, 0), 2: (14, 10), 3: (24, 55)}  # inclinação (graus) e agachamento (px) por nível


# ------------------------------------------------------------------ texto (PIL)
def fonte(tam, negrito=True):
    nomes = (["Inter-Bold.otf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "arialbd.ttf"] if negrito
             else ["Inter-Medium.otf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf", "arial.ttf"])
    pastas = ["/usr/share/fonts/opentype/inter", "/usr/share/fonts/truetype/dejavu",
              "/usr/share/fonts/truetype/liberation", "C:/Windows/Fonts"]
    for n in nomes:
        for p in pastas:
            if Path(p, n).exists():
                return ImageFont.truetype(str(Path(p, n)), tam)
    return ImageFont.load_default()


def escrever(img, xy, texto, tam, cor="#ffffff", fundo=None, pad=6, negrito=True, ancora="la"):
    """Escreve texto com acento numa imagem BGR (in-place)."""
    f = fonte(tam, negrito)
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    d = ImageDraw.Draw(pil)
    caixa = d.textbbox(xy, texto, font=f, anchor=ancora)
    if fundo:
        d.rectangle((caixa[0] - pad, caixa[1] - pad, caixa[2] + pad, caixa[3] + pad), fill=fundo)
    d.text(xy, texto, font=f, fill=cor, anchor=ancora)
    img[:] = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    return caixa


_ROTULOS = {}


def colar_rotulo(img, centro, texto, tam, cor, fundo, pad=3, ancora="mm"):
    """Rótulo com fundo, renderizado uma vez e colado (rápido para usar em todo quadro)."""
    ch = (texto, tam, cor, fundo, pad)
    if ch not in _ROTULOS:
        tmp = np.zeros((tam * 3, len(texto) * tam + 40, 3), np.uint8)
        x0, y0, x1, y1 = escrever(tmp, (20, tam), texto, tam, cor, fundo=fundo, pad=pad)
        _ROTULOS[ch] = tmp[max(0, y0 - pad):y1 + pad + 1, max(0, x0 - pad):x1 + pad + 1].copy()
    r = _ROTULOS[ch]
    h, w = r.shape[:2]
    x = int(centro[0] - (w // 2 if ancora[0] == "m" else (w if ancora[0] == "r" else 0)))
    y = int(centro[1] - (h // 2 if ancora[1] == "m" else 0))
    img[y:y + h, x:x + w] = r


# ------------------------------------------------------------------ desenho
def ret(img, x0, y0, x1, y1, cor, borda=None, esp=1):
    cv2.rectangle(img, (int(x0), int(y0)), (int(x1), int(y1)), cor, -1, cv2.LINE_AA)
    if borda:
        cv2.rectangle(img, (int(x0), int(y0)), (int(x1), int(y1)), borda, esp, cv2.LINE_AA)


def pacote(img, x, y, w, h, cores):
    a, b = bgr(cores[0]), bgr(cores[1])
    ret(img, x, y, x + w, y + h, a, bgr("#2b2b2b"))
    cv2.rectangle(img, (int(x + 2), int(y + h * 0.45)), (int(x + w - 2), int(y + h * 0.7)), b, -1)


def caixa_aberta(img, x0, x1, y_fundo, alt, conteudo=None, recuo=26):
    """Caixa de papelão aberta vista de frente: abas atrás, interior e parede da frente."""
    yt = y_fundo - alt
    cv2.fillPoly(img, [np.array([(x0 + 4, yt), (x0 - 10, yt - 22), (x1 + 10, yt - 22), (x1 - 4, yt)], np.int32)],
                 PAPELAO_ESC, cv2.LINE_AA)
    ret(img, x0, yt, x1, yt + recuo, PAPELAO_INT)
    for i, cores in enumerate(conteudo or []):
        larg = 24
        x = x0 + 8 + (i % max(1, int((x1 - x0 - 12) // (larg + 3)))) * (larg + 3)
        pacote(img, x, yt + recuo - 15 - 3 * (i // max(1, int((x1 - x0 - 12) // (larg + 3)))), larg, 15, cores)
    ret(img, x0, yt + recuo, x1, y_fundo, PAPELAO, bgr("#8c6a3e"))
    cv2.line(img, (x0 + 6, yt + recuo + 10), (x1 - 6, yt + recuo + 10), bgr("#b38c5a"), 2, cv2.LINE_AA)


def fundo_estatico():
    img = np.zeros((H, W, 3), np.uint8)
    # parede de telha metálica e faixa de luz no alto
    ret(img, 0, 0, W, 420, bgr("#c3c6c8"))
    ret(img, 0, 0, W, 46, bgr("#e9eef1"))
    for x in range(0, W, 18):
        cv2.line(img, (x, 46), (x, 420), bgr("#b2b5b8"), 2)
    for y in (140, 300):
        cv2.line(img, (0, y), (W, y), bgr("#9a9fa4"), 3)
    # piso de concreto, faixa amarela e tapete
    ret(img, 0, 420, W, H, bgr("#bfc2c3"))
    cv2.fillPoly(img, [np.array([(0, 640), (0, 668), (420, 720), (470, 720)], np.int32)], bgr("#e7c51a"), cv2.LINE_AA)
    cv2.fillPoly(img, [np.array([(370, 560), (790, 560), (830, 720), (330, 720)], np.int32)], bgr("#1c1d1f"), cv2.LINE_AA)
    # porta-paletes azul ao fundo, à esquerda
    for x in (12, 120, 228):
        ret(img, x, 0, x + 12, 470, AZUL_RACK)
    for y in (110, 230, 350):
        ret(img, 0, y, 240, y + 9, LARANJA)
        for x in (24, 132):
            ret(img, x, y - 62, x + 86, y, bgr("#d8c7a5"), bgr("#a9946c"))
            cv2.line(img, (x, y - 31), (x + 86, y - 31), bgr("#efe5d0"), 2)
    # placa do posto
    escrever(img, (385, 72), "SEPARAÇÃO · POSTO 03", 17, "#ffffff", fundo="#1e7a3c", pad=9, ancora="mm")
    # prateleira de 3 níveis
    for x in (PRAT_X0, 1036, PRAT_X1 - 10):
        ret(img, x, 120, x + 10, 700, AZUL_RACK)
    for n, (nome, topo, viga) in NIVEIS.items():
        ret(img, PRAT_X0 - 4, viga, PRAT_X1 + 4, viga + 12, LARANJA)
        for i, x0 in enumerate(range(PRAT_X0 + 14, PRAT_X1 - 100, 112)):
            sku = PACOTES[(n * 3 + i) % len(PACOTES)]
            caixa_aberta(img, x0, x0 + 100, viga, viga - topo, [sku] * 6, recuo=30)
            ret(img, x0 + 34, viga + 2, x0 + 66, viga + 10, bgr("#ffffff"))
        escrever(img, (PRAT_X1 - 8, viga + 25), nome, 13, "#ffffff", fundo="#16202e", pad=4, ancora="rm")
    # caixas fechadas de estoque em cima
    for x0 in (PRAT_X0 + 30, PRAT_X0 + 180, PRAT_X0 + 330):
        ret(img, x0, 130, x0 + 110, 182, PAPELAO, bgr("#8c6a3e"))
        cv2.line(img, (x0, 156), (x0 + 110, 156), bgr("#b38c5a"), 2)
    # braço articulado, monitor e leitor
    cv2.line(img, (PRAT_X0 + 4, 210), (770 + DX, 205), bgr("#2b2b2b"), 8, cv2.LINE_AA)
    cv2.line(img, (770 + DX, 205), (752 + DX, 222), bgr("#2b2b2b"), 8, cv2.LINE_AA)
    ret(img, 672 + DX, 150, 790 + DX, 226, bgr("#151515"))
    ret(img, 678 + DX, 156, 784 + DX, 220, bgr("#c9e3a5"))
    for i, y in enumerate(range(162, 214, 8)):
        cv2.line(img, (684 + DX, y), (684 + DX + (70 if i % 2 else 92), y), bgr("#7f9b62"), 2)
    cv2.line(img, (PRAT_X0 + 4, 262), (760 + DX, 266), bgr("#2b2b2b"), 6, cv2.LINE_AA)
    cv2.fillPoly(img, [np.array([(x + DX, y) for x, y in ((744, 258), (776, 258), (770, 280), (750, 300), (738, 296), (746, 278))], np.int32)],
                 bgr("#333333"), cv2.LINE_AA)
    ret(img, 736 + DX, 290, 748 + DX, 300, bgr("#e02020"))
    escrever(img, (720 + DX, 330), "LEITOR", 11, "#16202e", fundo="#ffffff", pad=3, ancora="mm")
    return img


def frente_estatica():
    """Esteira de roletes por gravidade (fica na frente do operador). Devolve imagem e máscara."""
    img = np.zeros((H, W, 3), np.uint8)
    m = np.zeros((H, W), np.uint8)
    x0, x1 = 0, 800

    def r(a, b, c, d, cor):
        ret(img, a, b, c, d, cor)
        cv2.rectangle(m, (int(a), int(b)), (int(c), int(d)), 255, -1)

    for x in (60, 330, 600, 770):  # pés
        r(x, ESTEIRA_Y + 40, x + 14, 680, bgr("#3a4f8c"))
        r(x - 14, 676, x + 28, 686, bgr("#3a4f8c"))
    r(x0, ESTEIRA_Y - 4, x1, ESTEIRA_Y + 14, bgr("#8d9196"))
    for x in range(x0 + 4, x1, 15):
        cv2.line(img, (x, ESTEIRA_Y - 3), (x, ESTEIRA_Y + 13), bgr("#d6d9dc"), 6, cv2.LINE_AA)
        cv2.line(img, (x + 4, ESTEIRA_Y - 3), (x + 4, ESTEIRA_Y + 13), bgr("#6c7075"), 1)
    r(x0, ESTEIRA_Y + 14, x1, ESTEIRA_Y + 40, bgr("#5d6166"))
    for x in range(x0, x1, 28):  # fita zebrada amarela e preta
        cv2.fillPoly(img, [np.array([(x, ESTEIRA_Y + 14), (x + 14, ESTEIRA_Y + 14), (x + 6, ESTEIRA_Y + 20), (x - 8, ESTEIRA_Y + 20)], np.int32)],
                     bgr("#e7c51a"))
    return img, m


# ------------------------------------------------------------------ cinemática
def rot(p, c, ang):
    a = math.radians(ang)
    dx, dy = p[0] - c[0], p[1] - c[1]
    return (c[0] + dx * math.cos(a) - dy * math.sin(a), c[1] + dx * math.sin(a) + dy * math.cos(a))


def ik(s, alvo, l1, l2, k=1.0):
    """Dois segmentos. k=+1: cotovelo de um lado; k=-1: do outro; no meio o antebraço encurta
    (braço visto em perspectiva), então a troca de lado é contínua."""
    dx, dy = alvo[0] - s[0], alvo[1] - s[1]
    d = max(1e-6, min(math.hypot(dx, dy), l1 + l2 - 1e-3))
    a = math.atan2(dy, dx)
    b = math.acos(max(-1, min(1, (l1 * l1 + d * d - l2 * l2) / (2 * l1 * d))))
    ang = a + b * k
    e = (s[0] + l1 * math.cos(ang), s[1] + l1 * math.sin(ang))
    w = (s[0] + math.cos(a) * d, s[1] + math.sin(a) * d)
    return e, w


L1, L2, EXT = 116, 112, 0.35


def braco_para_mao(s, mao, k=1.0):
    """Acha cotovelo e punho para que o ponto 'mão' do ConfereVídeo (punho + 0,35 × antebraço) caia no alvo."""
    w = mao
    for _ in range(12):
        e, w2 = ik(s, w, L1, L2, k)
        mao_calc = (w2[0] + EXT * (w2[0] - e[0]), w2[1] + EXT * (w2[1] - e[1]))
        w = (w[0] + (mao[0] - mao_calc[0]) * 0.8, w[1] + (mao[1] - mao_calc[1]) * 0.8)
    return ik(s, w, L1, L2, k)


def desenhar_operador(img, pose):
    lean, agacha = pose["lean"], pose["agacha"]
    xo = X_OP + pose.get("dx", 0)  # dx: passo para o lado
    qc = (xo, QUADRIL_Y + agacha)

    def P(x, y):  # ponto do tronco (relativo ao quadril em pé) já inclinado
        return rot((xo + x, QUADRIL_Y + agacha + y), qc, lean)

    # pernas (aparecem por baixo da esteira)
    for lado in (-1, 1):
        q = (xo + lado * 24, QUADRIL_Y + agacha)
        tornozelo = (xo + lado * 32, 664)
        joelho, _ = ik(q, tornozelo, 115 if agacha else 112, 112, k=(1 if lado < 0 else -1))
        if not agacha:
            joelho = ((q[0] + tornozelo[0]) / 2, (q[1] + tornozelo[1]) / 2)
        for a, b in ((q, joelho), (joelho, tornozelo)):
            cv2.line(img, tuple(map(int, a)), tuple(map(int, b)), CALCA, 34, cv2.LINE_AA)
        cv2.ellipse(img, (int(tornozelo[0] + lado * 8), 672), (26, 12), 0, 0, 360, BOTA, -1, cv2.LINE_AA)
    # tronco: camisa azul-marinho e colete
    tronco = [P(-58, -210), P(58, -210), P(50, 6), P(-50, 6)]
    cv2.fillPoly(img, [np.array(tronco, np.int32)], MARINHO, cv2.LINE_AA)
    colete = [P(-50, -200), P(-14, -200), P(0, -150), P(14, -200), P(50, -200), P(44, -10), P(-44, -10)]
    cv2.fillPoly(img, [np.array(colete, np.int32)], COLETE, cv2.LINE_AA)
    for y in (-92, -60):
        cv2.line(img, tuple(map(int, P(-46, y))), tuple(map(int, P(46, y))), FAIXA, 7, cv2.LINE_AA)
    # cabeça
    pesc = P(0, -218)
    cv2.line(img, tuple(map(int, P(0, -206))), tuple(map(int, pesc)), PELE, 22, cv2.LINE_AA)
    cab = P(0, -262)
    cx, cy = int(cab[0]), int(cab[1])
    cv2.ellipse(img, (cx, cy), (31, 38), lean, 0, 360, PELE, -1, cv2.LINE_AA)
    for lado in (-1, 1):
        o = rot((cx + lado * 12, cy - 4), (cx, cy), lean)
        cv2.circle(img, (int(o[0]), int(o[1])), 4, bgr("#2a2a2a"), -1, cv2.LINE_AA)
        orelha = rot((cx + lado * 31, cy + 2), (cx, cy), lean)
        cv2.ellipse(img, (int(orelha[0]), int(orelha[1])), (6, 10), lean, 0, 360, bgr("#c99470"), -1, cv2.LINE_AA)
    nariz = rot((cx, cy + 9), (cx, cy), lean)
    cv2.circle(img, (int(nariz[0]), int(nariz[1])), 3, bgr("#b9805c"), -1, cv2.LINE_AA)
    boca = rot((cx, cy + 22), (cx, cy), lean)
    cv2.ellipse(img, (int(boca[0]), int(boca[1])), (9, 3), lean, 0, 180, bgr("#8a4a3a"), 2, cv2.LINE_AA)
    cv2.ellipse(img, (cx, cy - 14), (36, 30), lean, 180, 360, CAPACETE, -1, cv2.LINE_AA)
    aba = [rot((cx + dx, cy - 14), (cx, cy), lean) for dx in (-44, 44)]
    cv2.line(img, tuple(map(int, aba[0])), tuple(map(int, aba[1])), CAPACETE, 7, cv2.LINE_AA)
    return {"ombro_d": P(56, -200), "ombro_e": P(-56, -200), "cintura_e": P(-92, -36)}


def desenhar_braco(img, s, mao, k, segura=None):
    e, w = braco_para_mao(s, mao, k)
    s, e, w = tuple(map(int, s)), tuple(map(int, e)), tuple(map(int, w))
    cv2.line(img, s, e, MARINHO, 28, cv2.LINE_AA)
    cv2.line(img, e, w, MARINHO, 25, cv2.LINE_AA)
    cv2.circle(img, e, 14, MARINHO, -1, cv2.LINE_AA)
    # punho refletivo e luva
    ux, uy = w[0] - e[0], w[1] - e[1]
    n = max(1, math.hypot(ux, uy))
    p = (int(w[0] - ux / n * 12), int(w[1] - uy / n * 12))
    cv2.line(img, p, w, FAIXA, 25, cv2.LINE_AA)
    g = (int(w[0] + ux * 0.3), int(w[1] + uy * 0.3))
    cv2.line(img, w, g, LUVA, 22, cv2.LINE_AA)
    if segura:
        pacote(img, g[0] - 14, g[1] - 9, 28, 17, segura)
    cv2.circle(img, g, 16, LUVA, -1, cv2.LINE_AA)


# ------------------------------------------------------------------ roteiro
ITENS = [  # nível, encenação
    (1, "ok"), (2, "ok"), (3, "ok"), (1, "sem_leitor"), (2, "ok"), (3, "ok"),
    (1, "bipe_duplo"), (2, "ok"), (3, "caixa_errada"), (1, "ok"), (2, "sem_bipe"), (3, "ok"),
]
TEXTO = {
    "ok": ("correto: prateleira → leitor (1 bipe) → caixa do pedido", "#3ddc84"),
    "sem_leitor": ("ERRO encenado: colocou na caixa sem passar no leitor", "#ff6b6b"),
    "bipe_duplo": ("ERRO encenado: bipou duas vezes o mesmo item", "#ff6b6b"),
    "caixa_errada": ("ERRO encenado: colocou na caixa do pedido ao lado (PED 4522)", "#ff6b6b"),
    "sem_bipe": ("ERRO encenado: passou no leitor, mas não bipou", "#ff6b6b"),
}
T_CRACHA = (0.4, 3.2)
T_PRIMEIRO = 3.6


def suave(a):
    a = max(0.0, min(1.0, a))
    return a * a * (3 - 2 * a)


def montar_roteiro():
    """Quadros-chave da mão direita (alvo, inclinação, agachamento) + eventos."""
    chaves = [(0.0, ALVOS["repouso"], 0, 0, -1, 0)]
    eventos = {"bipes": [], "pega": [], "solta": [], "legendas": []}
    t = T_PRIMEIRO

    def k(dt, alvo, lean=0, ag=0, dx=0):
        nonlocal t
        t += dt
        chaves.append((t, alvo, lean, ag, -1 if alvo == ALVOS["repouso"] else 1, dx))

    for i, (nivel, tipo) in enumerate(ITENS):
        ini = t
        sku = PACOTES[(nivel * 3 + i % 2) % len(PACOTES)]
        lean, ag = POSTURA[nivel]
        ax, ay = ALVOS[nivel]
        alvo_prat = (ax + (i % 2) * (18 if nivel < 3 else 6), ay)
        k(0.5, ALVOS["repouso"])
        if nivel == 1:  # sobe por fora do leitor para não "passar no leitor" antes de pegar
            k(0.45, (700, 200), lean * 0.5, ag)
            k(0.5, alvo_prat, lean, ag)
        else:
            k(0.9, alvo_prat, lean, ag)
        eventos["pega"].append((t + 0.2, i, sku))
        k(0.5, alvo_prat, lean, ag)
        if tipo == "sem_leitor":  # passa por cima do leitor, direto para a caixa
            k(0.6, (690, 200), lean * 0.3, ag * 0.3)
            k(0.6, ALVOS["posto"])
        else:
            if nivel == 3:  # levanta com o item junto da prateleira e depois vai ao leitor
                k(0.4, (836, 470), lean * 0.8, ag * 0.8)
                k(0.45, (830, 300), 6, 0)
                k(0.45, ALVOS["leitor"])
            else:
                k(0.8, ALVOS["leitor"])
            if tipo != "sem_bipe":
                eventos["bipes"].append(t + 0.12)
            if tipo == "bipe_duplo":
                eventos["bipes"].append(t + 0.48)
            k(0.6, ALVOS["leitor"])
            if tipo == "caixa_errada":  # dá um passo para o lado e solta na caixa do pedido vizinho
                k(0.45, (650, 312))
                k(0.8, (650 - PASSO, 312), dx=-PASSO)
                k(0.45, ALVOS["outra_esq"], dx=-PASSO)
            else:
                k(0.8, ALVOS["posto"])
        caixa = "outra_esq" if tipo == "caixa_errada" else "posto"
        eventos["solta"].append((t + 0.22, i, caixa))
        k(0.5, chaves[-1][1], chaves[-1][2], chaves[-1][3], chaves[-1][5])
        if tipo == "caixa_errada":  # volta para o lugar
            k(0.35, (650 - PASSO, 312), dx=-PASSO)
            k(0.8, (650, 312))
        k(0.7, ALVOS["repouso"])
        eventos["legendas"].append((ini, t, i, nivel, tipo))
    return chaves, eventos, t + 1.5


def pose_em(chaves, t):
    for (t0, a0, l0, g0, k0, d0), (t1, a1, l1, g1, k1, d1) in zip(chaves, chaves[1:]):
        if t0 <= t <= t1:
            u = suave((t - t0) / max(1e-6, t1 - t0))
            return ((a0[0] + (a1[0] - a0[0]) * u, a0[1] + (a1[1] - a0[1]) * u),
                    l0 + (l1 - l0) * u, g0 + (g1 - g0) * u, k0 + (k1 - k0) * u, d0 + (d1 - d0) * u)
    _, a, l, g, k, d = chaves[-1]
    return a, l, g, k, d


def cracha_img():
    dados = base64.urlsafe_b64encode(json.dumps(
        {"t": 1, "n": "Ana Souza", "u": "Guarulhos II", "f": "Separadora", "e": "", "i": []},
        ensure_ascii=False).encode()).decode().rstrip("=")
    q = cv2.QRCodeEncoder.create().encode("https://exemplo.invalid/ficha#" + dados)
    q = cv2.resize(q, (150, 150), interpolation=cv2.INTER_NEAREST)
    c = np.full((228, 170, 3), 255, np.uint8)
    c[8:158, 10:160] = cv2.cvtColor(q, cv2.COLOR_GRAY2BGR)
    escrever(c, (85, 176), "Ana Souza", 15, "#16202e", ancora="mm")
    escrever(c, (85, 196), "Separadora", 12, "#5b6678", negrito=False, ancora="mm")
    escrever(c, (85, 216), "crachá simulado", 11, "#c8202a", ancora="mm")
    cv2.rectangle(c, (0, 0), (169, 227), bgr("#16202e"), 2)
    return c


def gerar_audio(caminho, duracao, bipes):
    rng = np.random.default_rng(7)
    n = int(duracao * SR)
    t = np.arange(n) / SR
    a = 0.012 * rng.standard_normal(n) + 0.01 * np.sin(2 * np.pi * 120 * t)  # ruído do galpão e da esteira
    for b in bipes:
        i0 = int(b * SR)
        m = int(0.13 * SR)
        tt = np.arange(m) / SR
        env = np.minimum(1, np.minimum(tt, tt[::-1]) / 0.006)
        a[i0:i0 + m] += env[: len(a[i0:i0 + m])] * (0.45 * np.sin(2 * np.pi * BIPE_HZ * tt) +
                                                       0.12 * np.sin(2 * np.pi * 2 * BIPE_HZ * tt))[: len(a[i0:i0 + m])]
    pcm = (np.clip(a, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(caminho), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def areas():
    def n(x0, y0, x1, y1):
        return [[round(x0 / W, 4), round(y0 / H, 4)], [round(x1 / W, 4), round(y0 / H, 4)],
                [round(x1 / W, 4), round(y1 / H, 4)], [round(x0 / W, 4), round(y1 / H, 4)]]
    yb = ESTEIRA_Y
    return {
        # a prateleira inteira (3 níveis) numa área só, como se marca no programa
        "prateleiras": [n(PRAT_X0, NIVEIS[1][1] - 4, PRAT_X1, NIVEIS[3][2])],
        "leitor": n(688 + DX, 262, 770 + DX, 322),
        "caixa_posto": n(CAIXAS["posto"][0], yb - CAIXA_ALT - 30, CAIXAS["posto"][1], yb),
        "outras_caixas": [n(CAIXAS[c][0], yb - CAIXA_ALT - 30, CAIXAS[c][1], yb) for c in ("outra_esq2", "outra_esq")],
        "area_operador": [],
    }


def main(saida=PASTA / "demo_esteira_3_niveis.mp4"):
    chaves, ev, dur = montar_roteiro()
    fundo = fundo_estatico()
    frente, mascara = frente_estatica()
    m3 = mascara[:, :, None] > 0
    cracha = cracha_img()
    conteudo = {k: [] for k in CAIXAS}
    conteudo["outra_esq"] = [PACOTES[1], PACOTES[4]]
    conteudo["outra_esq2"] = [PACOTES[3]]
    legendas = {}
    with tempfile.TemporaryDirectory() as tmp:
        mudo, wav = Path(tmp, "v.mp4"), Path(tmp, "a.wav")
        vw = cv2.VideoWriter(str(mudo), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
        segura = None
        pegas, soltas = list(ev["pega"]), list(ev["solta"])
        for f in range(int(dur * FPS)):
            t = f / FPS
            while pegas and t >= pegas[0][0]:
                segura = pegas.pop(0)[2]
            while soltas and t >= soltas[0][0]:
                _, i, cx = soltas.pop(0)
                if segura:
                    conteudo[cx].append(segura)
                segura = None
            mao, lean, ag, kd, dx = pose_em(chaves, t)
            img = fundo.copy()
            pts = desenhar_operador(img, {"lean": lean, "agacha": ag, "dx": dx})
            img = np.where(m3, frente, img)
            for nome, (x0, x1) in CAIXAS.items():
                caixa_aberta(img, x0, x1, ESTEIRA_Y - 4, CAIXA_ALT, conteudo[nome])
                colar_rotulo(img, ((x0 + x1) // 2, ESTEIRA_Y - 30), ETIQUETA[nome], 12, "#16202e", "#ffffff")
            # braço esquerdo: na cintura, ou mostrando o crachá no começo
            mostra = T_CRACHA[0] <= t < T_CRACHA[1]
            # ao agachar, a mão esquerda se apoia na beira da esteira (fora da caixa do pedido)
            u = min(1.0, ag / 90)
            ce = pts["cintura_e"]
            mao_e = (500, 300) if mostra else (ce[0] + (452 - ce[0]) * u, ce[1] + (470 - ce[1]) * u)
            desenhar_braco(img, pts["ombro_e"], mao_e, k=1)
            if mostra:
                img[176:404, 412:582] = cracha
            desenhar_braco(img, pts["ombro_d"], mao, k=kd, segura=segura)
            # legenda do que foi encenado
            atual = next((l for l in ev["legendas"] if l[0] <= t < l[1] + 0.4), None)
            if mostra:
                chave = ("cracha",)
            elif atual:
                chave = atual[2:]
            else:
                chave = ("vazio",)
            if chave not in legendas:
                faixa = np.zeros((44, W, 3), np.uint8)
                faixa[:] = bgr("#16202e")
                if chave[0] == "cracha":
                    escrever(faixa, (16, 22), "Início do turno: o operador mostra o QR do crachá para a câmera",
                             17, "#ffffff", ancora="lm")
                elif chave[0] != "vazio":
                    i, nivel, tipo = chave
                    escrever(faixa, (16, 22), f"Item {i + 1} de {len(ITENS)} · {NOME_NIVEL[nivel]}",
                             17, "#ffffff", ancora="lm")
                    txt, cor = TEXTO[tipo]
                    escrever(faixa, (W - 16, 22), txt, 17, cor, ancora="rm")
                legendas[chave] = faixa
            img[H - 44:] = legendas[chave]
            colar_rotulo(img, (W - 14, 10), "DEMONSTRAÇÃO ILUSTRATIVA", 12, "#ffffff", "#c8202a", pad=5, ancora="rt")
            vw.write(img)
        vw.release()
        gerar_audio(wav, dur, ev["bipes"])
        subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(mudo), "-i", str(wav),
                        "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(saida)], check=True)
    caminho_areas = saida.with_name("areas_demo_3_niveis.yaml")
    caminho_areas.write_text("# Áreas da demonstração: estação de picking com 3 níveis\n" +
                             yaml.safe_dump(areas(), sort_keys=False, allow_unicode=True), encoding="utf-8")
    gabarito = [{"item": i + 1, "nivel": n, "encenado": tp} for i, (n, tp) in enumerate(ITENS)]
    print(json.dumps({"video": str(saida), "duracao_s": round(dur, 1), "bipes": len(ev["bipes"]),
                      "gabarito": gabarito}, ensure_ascii=False))


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else PASTA / "demo_esteira_3_niveis.mp4")
