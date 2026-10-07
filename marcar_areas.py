"""
Marca as áreas do posto no vídeo. Faça uma vez para cada posição da câmera.

    python marcar_areas.py video.mp4
    python marcar_areas.py video.mp4 --segundo 30

Teclas:
    1  prateleira / de onde pega os itens   (pode marcar várias)
    2  leitor (onde o item é bipado)
    3  caixa do posto (a abertura da caixa que está sendo montada)
    4  outras caixas (vizinhas na esteira)  (pode marcar várias - opcional)
    5  área do operador (opcional: onde ele fica em pé)

    Clique esquerdo = ponto   Clique direito / Z = desfaz
    N = nova forma do mesmo tipo   C = limpa o tipo atual
    ENTER ou S = salva   ESC = sai sem salvar
"""
import argparse
from pathlib import Path

import cv2
import numpy as np
import yaml

CAMADAS = {
    ord("1"): ("prateleiras", "Prateleira (de onde pega)", (60, 160, 230), True),
    ord("2"): ("leitor", "Leitor", (230, 200, 0), False),
    ord("3"): ("caixa_posto", "Caixa do posto", (60, 180, 60), False),
    ord("4"): ("outras_caixas", "Outras caixas", (60, 60, 220), True),
    ord("5"): ("area_operador", "Area do operador (opcional)", (180, 180, 180), False),
}
ORDEM = [ord(c) for c in "12345"]
QUADRO = None
dados = {}
atual = ORDEM[0]


def formas(tecla):
    return dados.setdefault(CAMADAS[tecla][0], [[]])


def desfazer():
    f = formas(atual)
    if f[-1]:
        f[-1].pop()
    elif len(f) > 1:
        f.pop()


def clique(ev, x, y, flags, escala):
    if ev == cv2.EVENT_LBUTTONDOWN:
        formas(atual)[-1].append((x / escala, y / escala))
    elif ev == cv2.EVENT_RBUTTONDOWN:
        desfazer()


def carregar(caminho, w, h):
    if not Path(caminho).exists():
        return
    a = yaml.safe_load(Path(caminho).read_text(encoding="utf-8")) or {}
    for chave, _, _, multi in CAMADAS.values():
        v = a.get(chave) or []
        if v:
            lista = v if multi else [v]
            dados[chave] = [[(x * w, y * h) for x, y in f] for f in lista] + [[]]


def salvar(caminho, w, h):
    out = {}
    for chave, _, _, multi in CAMADAS.values():
        val = [[[round(x / w, 4), round(y / h, 4)] for x, y in f] for f in dados.get(chave, []) if len(f) >= 3]
        out[chave] = val if multi else (val[0] if val else [])
    Path(caminho).write_text("# Gerado por marcar_areas.py (coordenadas em fração da imagem)\n" +
                             yaml.safe_dump(out, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"Áreas salvas em {caminho}")
    try:
        Path(caminho).with_name("areas_quadro.jpg").write_bytes(cv2.imencode(".jpg", QUADRO)[1].tobytes())
    except Exception:
        pass
    for k in ("prateleiras", "leitor", "caixa_posto"):
        if not out[k]:
            print(f"  ATENÇÃO: '{k}' não foi marcado - é obrigatório")


def main():
    global atual
    ap = argparse.ArgumentParser()
    ap.add_argument("fonte")
    ap.add_argument("--segundo", type=float, default=0)
    ap.add_argument("--areas", default=str(Path(__file__).resolve().parent / "areas.yaml"))
    a = ap.parse_args()
    if Path(a.fonte).suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp"):
        quadro = cv2.imread(a.fonte)
        ok = quadro is not None
    else:
        fonte = int(a.fonte) if a.fonte.isdigit() else a.fonte
        cap = cv2.VideoCapture(fonte)
        if a.segundo:
            cap.set(cv2.CAP_PROP_POS_MSEC, a.segundo * 1000)
        ok, quadro = cap.read()
        cap.release()
    if not ok:
        print("Não consegui ler o vídeo.")
        return
    global QUADRO
    QUADRO = quadro
    h, w = quadro.shape[:2]
    escala = min(1.0, 1280 / w, 760 / h)
    base = cv2.resize(quadro, (int(w * escala), int(h * escala)))
    carregar(a.areas, w, h)
    jan = "Marcar areas do posto"
    cv2.namedWindow(jan)
    cv2.setMouseCallback(jan, clique, escala)
    while True:
        img = base.copy()
        cam = img.copy()
        for t in ORDEM:
            chave, _, cor, _ = CAMADAS[t]
            for f in dados.get(chave, []):
                pts = np.array([(int(x * escala), int(y * escala)) for x, y in f], np.int32)
                if len(pts) >= 3:
                    cv2.fillPoly(cam, [pts], cor)
                if len(pts) >= 2:
                    cv2.polylines(img, [pts], len(pts) >= 3, cor, 2)
                for p in pts:
                    cv2.circle(img, tuple(int(v) for v in p), 4, cor, -1)
        img = cv2.addWeighted(cam, 0.25, img, 0.75, 0)
        _, nome, cor, multi = CAMADAS[atual]
        leg = [f"Marcando: {nome}",
               "1 prateleira  2 leitor  3 caixa do posto  4 outras caixas  5 operador",
               ("N nova forma  " if multi else "") + "Z desfaz  C limpa  ENTER salva  ESC sai"]
        for i, l in enumerate(leg):
            y = 24 + i * 24
            cv2.putText(img, l, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 4, cv2.LINE_AA)
            cv2.putText(img, l, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, cor if i == 0 else (255, 255, 255), 1, cv2.LINE_AA)
        cv2.imshow(jan, img)
        k = cv2.waitKey(20) & 0xFF
        if k == 255:
            continue
        if k == 27:
            print("Saiu sem salvar.")
            break
        if k in (13, 10, ord("s"), ord("S")):
            salvar(a.areas, w, h)
            break
        if k in CAMADAS:
            atual = k
        elif k in (ord("z"), ord("Z")):
            desfazer()
        elif k in (ord("c"), ord("C")):
            dados[CAMADAS[atual][0]] = [[]]
        elif k in (ord("n"), ord("N")) and multi and formas(atual)[-1]:
            formas(atual).append([])
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
