"""Relatório HTML do ConfereVídeo (abre no navegador, imprime em PDF)."""
import html
from collections import Counter

TIPOS = {
    "sem_leitor": "Colocou na caixa sem passar no leitor",
    "caixa_errada": "Colocou em outra caixa",
    "sem_bipe": "Passou no leitor, mas não bipou",
    "bipe_duplo": "Bipe duplo para um item",
}
COR_TIPO = {"sem_leitor": "#c2410c", "caixa_errada": "#7c3aed", "sem_bipe": "#0e7490", "bipe_duplo": "#b91c1c"}
MODOS = {"ao_vivo": "Câmera ao vivo", "videos": "Vídeos gravados", "demo": "Demonstração"}

CSS = """
:root{--ink:#16202e;--muted:#5b6678;--line:#e3e7ee;--bg:#f4f6f9;--card:#fff;--brand:#0f4c81;--ok:#15803d;--bad:#b91c1c}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 "Segoe UI",system-ui,-apple-system,Roboto,Arial,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding-inline:20px;padding-block:0 40px}
header.top{background:var(--ink);color:#fff}
header.top .wrap{display:flex;gap:20px;align-items:center;padding-block:22px;flex-wrap:wrap}
.logo{height:46px;max-width:180px;object-fit:contain;background:#fff;border-radius:6px;padding:4px}
.marca{font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:#9fb3cc}
h1{margin:2px 0 0;font-size:26px;line-height:1.2}
.sub{color:#c9d5e3;font-size:14px}
.modo{margin-left:auto;background:#ffffff1a;border:1px solid #ffffff33;border-radius:999px;padding:4px 12px;font-size:13px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px;margin-top:22px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px}
.kpi .v{font-size:34px;font-weight:700;font-variant-numeric:tabular-nums;line-height:1.1}
.kpi .l{color:var(--muted);font-size:13px;text-transform:uppercase;letter-spacing:.06em}
.kpi.bad .v{color:var(--bad)} .kpi.ok .v{color:var(--ok)}
section{margin-top:26px}
h2{font-size:17px;margin:0 0 12px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.dois{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media (max-width:820px){.dois{grid-template-columns:1fr}}
.painel{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px;min-width:0}
.barra{display:grid;grid-template-columns:minmax(0,1fr) 46px;gap:10px;align-items:center;margin:8px 0}
.barra .t{font-size:14px}
.barra .trilho{grid-column:1/2;height:10px;background:#eef1f5;border-radius:6px;overflow:hidden}
.barra .enc{height:100%;border-radius:6px}
.barra .n{grid-row:1/3;grid-column:2;text-align:right;font-weight:700;font-variant-numeric:tabular-nums}
.horas{display:flex;align-items:flex-end;gap:6px;height:150px;padding-top:10px;overflow-x:auto}
.hora{flex:1 0 26px;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;height:100%;gap:4px}
.hora .col{width:100%;background:var(--brand);border-radius:4px 4px 0 0;min-height:2px}
.hora .q{font-size:12px;font-weight:700;font-variant-numeric:tabular-nums}
.hora .h{font-size:11px;color:var(--muted)}
.filtros{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.filtros button{border:1px solid var(--line);background:var(--card);border-radius:999px;padding:6px 12px;font:inherit;font-size:13px;cursor:pointer}
.filtros button.on{background:var(--ink);color:#fff;border-color:var(--ink)}
.filtros button:focus-visible,.trocar button:focus-visible{outline:2px solid var(--brand);outline-offset:2px}
.lista{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:14px}
.erro{background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden;display:flex;flex-direction:column}
.erro video,.erro img.foto{width:100%;aspect-ratio:16/9;background:#000;display:block;object-fit:contain}
.erro img.foto{display:none}
.erro .info{padding:12px 14px;display:grid;gap:4px}
.tag{display:inline-block;font-size:12px;font-weight:700;color:#fff;border-radius:4px;padding:2px 8px;justify-self:start}
.erro .tit{font-weight:700}
.meta{color:var(--muted);font-size:13px;font-variant-numeric:tabular-nums}
.trocar{display:flex;gap:6px;margin-top:6px;flex-wrap:wrap}
.trocar button,.trocar a{border:1px solid var(--line);background:#fff;border-radius:6px;padding:4px 10px;font:inherit;font-size:13px;cursor:pointer;color:var(--ink);text-decoration:none}
.trocar button.on{border-color:var(--brand);color:var(--brand);font-weight:600}
.vazio{background:var(--card);border:1px dashed var(--line);border-radius:10px;padding:30px;text-align:center;color:var(--muted)}
footer{margin-top:28px;color:var(--muted);font-size:13px;border-top:1px solid var(--line);padding-top:12px}
@media print{
  body{background:#fff} header.top{background:#fff;color:var(--ink);border-bottom:2px solid var(--ink)}
  .sub,.marca{color:var(--muted)} .modo{border-color:var(--line)}
  .filtros,.trocar{display:none} .erro video{display:none} .erro img.foto{display:block}
  .erro,.painel,.kpi{break-inside:avoid}
}
"""

JS = """
document.querySelectorAll('.filtros button').forEach(b=>b.addEventListener('click',()=>{
  document.querySelectorAll('.filtros button').forEach(x=>x.classList.remove('on'));b.classList.add('on');
  const t=b.dataset.t;document.querySelectorAll('.erro').forEach(e=>{e.hidden=!(t==='todos'||e.dataset.t===t)});
}));
document.querySelectorAll('.trocar button').forEach(b=>b.addEventListener('click',()=>{
  const card=b.closest('.erro');const v=card.querySelector('video');
  card.querySelectorAll('.trocar button').forEach(x=>x.classList.remove('on'));b.classList.add('on');
  v.src=b.dataset.src;v.load();v.play().catch(()=>{});
}));
"""


def _e(s):
    return html.escape(str(s or ""))


def gerar_html(r, logo_data=""):
    erros = r["erros"]
    ciclos, ok = r["ciclos"], r["ok"]
    taxa = f"{ok / ciclos * 100:.1f}%".replace(".", ",") if ciclos else "—"
    cont = Counter(e["tipo"] for e in erros)
    maxc = max(cont.values()) if cont else 1
    barras = "".join(
        f"<div class='barra'><span class='t'>{_e(TIPOS[k])}</span><span class='n'>{cont.get(k, 0)}</span>"
        f"<div class='trilho'><div class='enc' style='width:{cont.get(k, 0) / maxc * 100:.0f}%;background:{COR_TIPO[k]}'></div></div></div>"
        for k in TIPOS if cont.get(k) or k in ("sem_leitor", "caixa_errada"))
    horas = Counter(e["hora"] for e in erros if e.get("hora") is not None)
    if horas:
        h0, h1 = min(horas), max(horas)
        mh = max(horas.values())
        cols = "".join(f"<div class='hora'><span class='q'>{horas.get(h, 0) or ''}</span>"
                       f"<div class='col' style='height:{horas.get(h, 0) / mh * 100:.0f}%'></div>"
                       f"<span class='h'>{h:02d}h</span></div>" for h in range(h0, h1 + 1))
        bloco_horas = f"<div class='horas'>{cols}</div>"
    else:
        bloco_horas = "<p class='meta'>Sem erros no período.</p>"

    filtros = "<button class='on' data-t='todos'>Todos ({})</button>".format(len(erros)) + "".join(
        f"<button data-t='{k}'>{_e(TIPOS[k])} ({v})</button>" for k, v in cont.items())
    cards = []
    for e in erros:
        marc, orig = e.get("marcado"), e.get("original")
        principal = marc or orig
        botoes = ""
        if marc:
            botoes += f"<button class='on' data-src='{_e(marc)}'>Com marcações</button>"
        if orig:
            botoes += f"<button{'' if marc else ' class=on'} data-src='{_e(orig)}'>Original (com som)</button>"
        if orig:
            botoes += f"<a href='{_e(orig)}' target='_blank'>Abrir arquivo</a>"
        momento = f" · vídeo {e['t_video']}" if e.get("t_video") else ""
        bip = f" · bipes ouvidos: {e['bipes']}" if e.get("bipes") is not None else ""
        video = (f"<video controls preload='metadata' poster='fotos/{_e(e['base'])}.jpg' src='{_e(principal)}'></video>"
                 if principal else "")
        cards.append(f"""<article class='erro' data-t='{e['tipo']}'>
{video}<img class='foto' src='fotos/{_e(e['base'])}.jpg' alt=''>
<div class='info'><span class='tag' style='background:{COR_TIPO[e['tipo']]}'>Nº {e['n']}</span>
<span class='tit'>{_e(TIPOS[e['tipo']])}</span>
<span class='meta'>{_e(e['quando'])} · {_e(e['fonte'])}{momento}{bip}</span>
<div class='trocar'>{botoes}</div></div></article>""")
    lista = "<div class='lista'>" + "\n".join(cards) + "</div>" if cards else \
        "<div class='vazio'>Nenhum erro encontrado neste período.</div>"
    per = " a ".join(p for p in r["periodo"] if p) or r["gerado"]
    logo = f"<img class='logo' src='{logo_data}' alt=''>" if logo_data else ""
    fontes = ", ".join(_e(f) for f in r["fontes"][:6]) + (" …" if len(r["fontes"]) > 6 else "")
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Conferência {_e(r['posto'])} · {_e(r['gerado'])}</title><style>{CSS}</style></head><body>
<header class="top"><div class="wrap">{logo}
<div><div class="marca">{_e(r['empresa'])} · {_e(r['unidade'])}</div>
<h1>Relatório de conferência da separação</h1>
<div class="sub">{_e(r['local'])} · {_e(r['posto'])}{(' · ' + _e(r['turno'])) if r.get('turno') else ''} · {_e(per)}</div></div>
<span class="modo">{_e(MODOS.get(r['modo'], r['modo']))}</span></div></header>
<main class="wrap">
<div class="kpis">
<div class="kpi"><div class="v">{ciclos}</div><div class="l">Itens conferidos</div></div>
<div class="kpi bad"><div class="v">{len(erros)}</div><div class="l">Erros com recorte</div></div>
<div class="kpi ok"><div class="v">{taxa}</div><div class="l">Itens sem erro</div></div>
<div class="kpi"><div class="v">{len(r['fontes'])}</div><div class="l">{'Vídeos analisados' if r['modo'] == 'videos' else 'Câmeras'}</div></div>
</div>
<section class="dois">
<div class="painel"><h2>Erros por tipo</h2>{barras}</div>
<div class="painel"><h2>Erros por hora</h2>{bloco_horas}</div>
</section>
<section><h2>Recortes dos erros</h2><div class="filtros">{filtros}</div>{lista}</section>
<footer>Origem: {fontes}. Gerado em {_e(r['gerado'])} pelo ConfereVídeo. Detecção automática por vídeo:
confirme cada recorte antes de qualquer tratativa. Para PDF, use Imprimir &gt; Salvar como PDF no navegador.</footer>
</main><script>{JS}</script></body></html>"""
