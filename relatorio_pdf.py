"""Relatório do turno em PDF (vai anexo no e-mail do gestor e fica na lista do SharePoint)."""
from __future__ import annotations

import io
from collections import Counter
from pathlib import Path

from fpdf import FPDF
from PIL import Image

TIPOS = {
    "sem_leitor": "Colocou na caixa sem passar no leitor",
    "caixa_errada": "Colocou em outra caixa",
    "sem_bipe": "Passou no leitor, mas não bipou",
    "bipe_duplo": "Bipe duplo para um item",
}
COR_TIPO = {"sem_leitor": (194, 65, 12), "caixa_errada": (124, 58, 237), "sem_bipe": (14, 116, 144),
            "bipe_duplo": (185, 28, 28)}
MODOS = {"ao_vivo": "Câmera ao vivo", "videos": "Vídeos gravados", "demo": "Demonstração"}
INK, MUTED, LINE, BRAND = (22, 32, 46), (91, 102, 120), (227, 231, 238), (15, 76, 129)
OK, BAD = (21, 128, 61), (185, 28, 28)


def _t(s) -> str:
    """As fontes padrão do PDF usam Latin-1: troca o que não cabe."""
    s = str(s if s is not None else "")
    for a, b in (("—", "-"), ("–", "-"), ("“", '"'), ("”", '"'), ("’", "'"), ("…", "..."), ("✓", "ok"),
                 ("→", "->"), ("≥", ">="), ("≤", "<=")):
        s = s.replace(a, b)
    return s.encode("latin-1", "replace").decode("latin-1")


class _PDF(FPDF):
    rodape = ""

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "", 7.5)
        self.set_text_color(*MUTED)
        self.cell(0, 5, _t(self.rodape), align="L")
        self.cell(0, 5, f"página {self.page_no()} de {{nb}}", align="R")


def gerar_pdf(r: dict, pasta, saida, logo: str | None = None) -> Path:
    """r = Sessao.resumo(); pasta = pasta da sessão (para as fotos)."""
    pasta, saida = Path(pasta), Path(saida)
    pdf = _PDF(orientation="P", unit="mm", format="A4")
    pdf.rodape = (f"ConfereVídeo · {r.get('empresa', '')} · {r.get('unidade', '')} · Detecção automática por vídeo: "
                  "confirme cada recorte antes de qualquer tratativa.")
    pdf.set_auto_page_break(True, 16)
    pdf.set_margins(12, 12, 12)
    pdf.add_page()
    W = pdf.w - 24

    # ---- cabeçalho
    pdf.set_fill_color(*INK)
    pdf.rect(0, 0, pdf.w, 34, "F")
    x0 = 12
    if logo and Path(logo).exists():
        try:
            pdf.set_fill_color(255, 255, 255)
            pdf.rect(12, 7, 30, 20, "F")
            pdf.image(str(logo), x=13, y=8, w=28, h=18, keep_aspect_ratio=True)
            x0 = 47
        except Exception:
            x0 = 12
    pdf.set_xy(x0, 7)
    pdf.set_font("Helvetica", "B", 7.5)
    pdf.set_text_color(159, 179, 204)
    pdf.cell(0, 4, _t(f"{r.get('empresa', '')} · {r.get('unidade', '')}".upper()))
    pdf.set_xy(x0, 12)
    pdf.set_font("Helvetica", "B", 15)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 8, _t("Relatório de conferência da separação"))
    per = " a ".join(p for p in r.get("periodo", []) if p) or r.get("gerado", "")
    sub = " · ".join(x for x in (r.get("local"), r.get("posto"), r.get("turno"), per) if x)
    pdf.set_xy(x0, 21)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(201, 213, 227)
    pdf.cell(0, 5, _t(sub))
    modo = MODOS.get(r.get("modo"), r.get("modo", ""))
    pdf.set_font("Helvetica", "B", 8)
    lw = pdf.get_string_width(_t(modo)) + 8
    pdf.set_draw_color(120, 140, 165)
    pdf.set_xy(pdf.w - 12 - lw, 9)
    pdf.cell(lw, 6, _t(modo), border=1, align="C")
    pdf.set_y(40)

    # ---- indicadores
    erros = r.get("erros", [])
    c, ok = r.get("ciclos", 0), r.get("ok", 0)
    taxa = f"{ok / c * 100:.1f}%".replace(".", ",") if c else "-"
    kpis = [(str(c), "ITENS CONFERIDOS", INK), (str(len(erros)), "ERROS COM RECORTE", BAD),
            (taxa, "ITENS SEM ERRO", OK), (str(c - ok if c else len(erros)), "ITENS COM ERRO", INK)]
    bw = (W - 3 * 4) / 4
    y = pdf.get_y()
    for i, (v, rot, cor) in enumerate(kpis):
        x = 12 + i * (bw + 4)
        pdf.set_draw_color(*LINE)
        pdf.set_fill_color(255, 255, 255)
        pdf.rect(x, y, bw, 20, "DF")
        pdf.set_xy(x + 4, y + 3)
        pdf.set_font("Helvetica", "B", 17)
        pdf.set_text_color(*cor)
        pdf.cell(bw - 8, 8, _t(v))
        pdf.set_xy(x + 4, y + 12)
        pdf.set_font("Helvetica", "", 7)
        pdf.set_text_color(*MUTED)
        pdf.cell(bw - 8, 4, _t(rot))
    pdf.set_y(y + 26)

    # ---- erros por tipo e por hora
    def titulo(txt):
        pdf.set_font("Helvetica", "B", 8.5)
        pdf.set_text_color(*MUTED)
        pdf.cell(0, 6, _t(txt.upper()), new_x="LMARGIN", new_y="NEXT")

    y = pdf.get_y()
    meia = (W - 6) / 2
    pdf.set_xy(12, y)
    titulo("Erros por tipo")
    cont = Counter(e["tipo"] for e in erros)
    maxc = max(cont.values()) if cont else 1
    yy = pdf.get_y() + 1
    for k in TIPOS:
        if not cont.get(k) and k not in ("sem_leitor", "caixa_errada"):
            continue
        pdf.set_xy(12, yy)
        pdf.set_font("Helvetica", "", 8.5)
        pdf.set_text_color(*INK)
        pdf.cell(meia - 12, 4.5, _t(TIPOS[k]))
        pdf.set_font("Helvetica", "B", 8.5)
        pdf.cell(12, 4.5, str(cont.get(k, 0)), align="R")
        pdf.set_fill_color(238, 241, 245)
        pdf.rect(12, yy + 5, meia, 2.2, "F")
        if cont.get(k):
            pdf.set_fill_color(*COR_TIPO[k])
            pdf.rect(12, yy + 5, meia * cont[k] / maxc, 2.2, "F")
        yy += 10
    fim_esq = yy
    pdf.set_xy(12 + meia + 6, y)
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.set_text_color(*MUTED)
    pdf.cell(meia, 6, _t("ERROS POR HORA"))
    horas = Counter(e["hora"] for e in erros if e.get("hora") is not None)
    base_y, alt = y + 36, 26
    if horas:
        h0, h1 = min(horas), max(horas)
        n = h1 - h0 + 1
        mh = max(horas.values())
        cw = min(12, meia / n)
        for i, h in enumerate(range(h0, h1 + 1)):
            v = horas.get(h, 0)
            x = 12 + meia + 6 + i * cw
            hh = alt * v / mh if v else 0.4
            pdf.set_fill_color(*BRAND)
            pdf.rect(x + 0.8, base_y - hh, cw - 1.6, hh, "F")
            pdf.set_font("Helvetica", "B", 6.5)
            pdf.set_text_color(*INK)
            if v:
                pdf.set_xy(x, base_y - hh - 4)
                pdf.cell(cw, 4, str(v), align="C")
            pdf.set_font("Helvetica", "", 6)
            pdf.set_text_color(*MUTED)
            pdf.set_xy(x, base_y + 0.5)
            pdf.cell(cw, 4, f"{h:02d}h", align="C")
    else:
        pdf.set_xy(12 + meia + 6, y + 8)
        pdf.set_font("Helvetica", "", 8.5)
        pdf.cell(meia, 5, _t("Sem erros no período."))
    pdf.set_y(max(fim_esq, base_y + 6) + 4)

    # ---- tabela de erros com foto
    titulo("Erros registrados")
    cols = [("Nº", 10), ("Foto", 36), ("Quando", 34), ("Erro", 0), ("Bipes", 14), ("Código", 44)]
    fixo = sum(w for _, w in cols)
    cols = [(n, w or (W - fixo)) for n, w in cols]

    def cabecalho_tabela():
        pdf.set_font("Helvetica", "B", 7.5)
        pdf.set_text_color(*MUTED)
        pdf.set_draw_color(*INK)
        for n, w in cols:
            pdf.cell(w, 6, _t(n.upper()), border="B")
        pdf.ln(6)

    if not erros:
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(*OK)
        pdf.cell(0, 8, _t("Nenhum erro encontrado neste período."))
    else:
        cabecalho_tabela()
        ah = 21
        for e in erros:
            if pdf.get_y() + ah > pdf.h - 18:
                pdf.add_page()
                cabecalho_tabela()
            y = pdf.get_y()
            x = 12
            pdf.set_draw_color(*LINE)
            pdf.line(12, y + ah, 12 + W, y + ah)
            pdf.set_text_color(*INK)
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_xy(x, y + 8)
            pdf.cell(cols[0][1], 5, str(e["n"]))
            x += cols[0][1]
            foto = pasta / "fotos" / f"{e['base']}.jpg"
            if foto.exists():
                try:
                    im = Image.open(foto).convert("RGB")
                    im.thumbnail((480, 270))  # foto pequena (JPEG): PDF leve para o e-mail
                    buf = io.BytesIO()
                    im.save(buf, "JPEG", quality=80)
                    buf.seek(0)
                    pdf.image(buf, x=x, y=y + 1.5, w=cols[1][1] - 3, h=ah - 3, keep_aspect_ratio=True)
                except Exception:
                    pass
            x += cols[1][1]
            pdf.set_font("Helvetica", "", 8.5)
            pdf.set_xy(x, y + 6)
            pdf.multi_cell(cols[2][1] - 2, 4.2, _t(e.get("quando") or e.get("t_video", "")), align="L")
            x += cols[2][1]
            pdf.set_fill_color(*COR_TIPO.get(e["tipo"], INK))
            pdf.rect(x, y + 6, 1.6, 9, "F")
            pdf.set_xy(x + 3, y + 6)
            pdf.set_font("Helvetica", "B", 8.5)
            pdf.multi_cell(cols[3][1] - 5, 4.2, _t(TIPOS.get(e["tipo"], e["tipo"])), align="L")
            if e.get("t_video"):
                pdf.set_xy(x + 3, y + 14.5)
                pdf.set_font("Helvetica", "", 7)
                pdf.set_text_color(*MUTED)
                pdf.cell(cols[3][1] - 5, 3.5, _t(f"{e.get('fonte', '')} · momento {e['t_video']}"))
                pdf.set_text_color(*INK)
            x += cols[3][1]
            pdf.set_font("Helvetica", "", 8.5)
            pdf.set_xy(x, y + 8)
            pdf.cell(cols[4][1], 5, "" if e.get("bipes") is None else str(e["bipes"]), align="C")
            x += cols[4][1]
            pdf.set_xy(x, y + 8)
            pdf.set_font("Helvetica", "", 7)
            pdf.set_text_color(*MUTED)
            pdf.cell(cols[5][1], 5, _t(e.get("id", "")))
            pdf.set_y(y + ah)
    saida.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(saida))
    return saida
