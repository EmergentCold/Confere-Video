"""Monta o ConfereVideo.html: o ConfereVídeo inteiro em um arquivo só, para baixar, anexar e
abrir com dois cliques no navegador (como o SST Vencimentos), sem instalar nada.

    python web/montar_arquivo_unico.py ORT_DIST SAIDA.html [--demo-webm]

ORT_DIST: pasta dist do pacote onnxruntime-web (ex.: celular/node_modules/onnxruntime-web/dist).
A IA, o motor da IA (WebAssembly) e o vídeo de demonstração vão dentro da página em base64;
os dois maiores comprimidos com gzip (o navegador descomprime com DecompressionStream).
"""
import base64
import gzip
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def bloco(id_, dados, gz=False, extra=""):
    if gz:
        dados = gzip.compress(dados, 9)
    b64 = base64.b64encode(dados).decode()
    linhas = "\n".join(b64[i:i + 4096] for i in range(0, len(b64), 4096))
    return f'<script type="text/plain" id="{id_}"{" data-gz" if gz else ""}{extra}>\n{linhas}\n</script>\n'


def main():
    ort, saida = Path(sys.argv[1]), Path(sys.argv[2])
    webm = "--demo-webm" in sys.argv
    pagina = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")
    tag = '<script src="ort.wasm.min.js"></script>'
    assert pagina.count(tag) == 1
    motor_js = (ort / "ort.wasm.min.js").read_text(encoding="utf-8").replace("</script", "<\\/script")
    demo = RAIZ / "web" / "demo.webm" if webm else RAIZ / "demo" / "demo_esteira_cigarros.mp4"
    embutidos = (bloco("emb-wasm", (ort / "ort-wasm-simd-threaded.wasm").read_bytes(), gz=True)
                 + bloco("emb-mjs", (ort / "ort-wasm-simd-threaded.mjs").read_bytes())
                 + bloco("emb-modelo", (RAIZ / "web" / "yolo11n-pose.onnx").read_bytes(), gz=True)
                 + bloco("emb-demo", demo.read_bytes(), extra=f' data-tipo="{"video/webm" if webm else "video/mp4"}"'))
    pagina = pagina.replace(tag, embutidos + "<script>\n" + motor_js + "\n</script>")
    doc = ('<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
           '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
           '<style>body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style>'
           '</head><body>' + pagina + '</body></html>')
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(doc, encoding="utf-8")
    print(f"{saida} ({saida.stat().st_size / 1048576:.1f} MB)")


if __name__ == "__main__":
    main()
