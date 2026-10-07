"""
ConfereVídeo · verificação do PC
================================
Confere se este computador está pronto para rodar o ConfereVídeo e diz o que falta.
Funciona mesmo quando faltam componentes (cada teste é independente).

    python diagnostico.py            -> mostra na tela e salva diagnostico.txt
    (ou pelo botão "Verificar este PC" na tela Configurações)
"""
from __future__ import annotations

import importlib
import json
import os
import platform
import shutil
import socket
import ssl
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

PASTA = Path(__file__).resolve().parent
os.environ.setdefault("OPENCV_LOG_LEVEL", "OFF")             # sem mensagens técnicas ao procurar câmeras
os.environ.setdefault("OPENCV_VIDEOIO_PRIORITY_OBSENSOR", "0")
os.environ.setdefault("OPENCV_VIDEOIO_PRIORITY_GSTREAMER", "0")
OK, AVISO, FALHA, INFO = "OK", "ATENÇÃO", "FALTA", "INFO"
PACOTES = [  # (módulo, nome para instalar, obrigatório)
    ("cv2", "opencv-python", True), ("numpy", "numpy", True), ("yaml", "pyyaml", True),
    ("ultralytics", "ultralytics", True), ("torch", "torch", True), ("lap", "lap", True),
    ("imageio_ffmpeg", "imageio-ffmpeg", True), ("PIL", "pillow", True), ("fpdf", "fpdf2", True),
    ("sounddevice", "sounddevice", False), ("tkinter", "tkinter (vem com o Python)", True),
]


class Diagnostico:
    def __init__(self, progresso=None):
        self.itens = []  # (grupo, situação, texto, como resolver)
        self.progresso = progresso or (lambda txt: None)
        self.cfg = {}

    def add(self, grupo, sit, texto, resolver=""):
        self.itens.append((grupo, sit, texto, resolver))

    # ------------------------------------------------------------------ testes
    def sistema(self):
        g = "Computador"
        self.add(g, INFO, f"{platform.system()} {platform.release()} ({platform.version()}) · {platform.machine()}")
        v = sys.version_info
        txt = f"Python {v.major}.{v.minor}.{v.micro} em {sys.executable}"
        if (v.major, v.minor) < (3, 10):
            self.add(g, FALHA, txt, "Instale o Python 3.11 ou 3.12 (python.org) e rode o INSTALAR.bat de novo.")
        elif (v.major, v.minor) > (3, 13):
            self.add(g, AVISO, txt, "Versão muito nova: se der erro na instalação, use o Python 3.12.")
        else:
            self.add(g, OK, txt)
        try:
            cpus = os.cpu_count() or 0
            self.add(g, INFO, f"{cpus} núcleos de processador")
        except Exception:
            pass
        try:
            livre = shutil.disk_usage(self._pasta_resultados_existente()).free / 1024 ** 3
            sit = OK if livre >= 5 else (AVISO if livre >= 1 else FALHA)
            self.add(g, sit, f"Espaço livre no disco dos resultados: {livre:.1f} GB",
                     "" if sit == OK else "Libere espaço ou diminua os dias guardados na tela Automação.")
        except Exception as e:
            self.add(g, AVISO, f"Não consegui medir o espaço em disco ({e})")

    def pacotes(self):
        g = "Componentes"
        faltam = []
        for mod, nome, obrig in PACOTES:
            self.progresso(f"Conferindo {nome}...")
            try:
                m = importlib.import_module(mod)
                ver = getattr(m, "__version__", "") or getattr(m, "TkVersion", "")
                self.add(g, OK, f"{nome} {ver}".strip())
            except Exception as e:
                (faltam.append(nome) if obrig else None)
                self.add(g, FALHA if obrig else AVISO, f"{nome}: não instalado ({type(e).__name__})",
                         "Rode o INSTALAR.bat de novo." if obrig else
                         "Sem ele o programa não ouve o bipe (só imagem). Rode o INSTALAR.bat de novo.")
        try:
            import torch
            if torch.cuda.is_available():
                self.add(g, OK, f"Placa de vídeo para a IA: {torch.cuda.get_device_name(0)}")
            else:
                self.add(g, INFO, "Sem placa de vídeo NVIDIA: a IA roda no processador (use a precisão Rápida).")
        except Exception:
            pass
        try:
            import imageio_ffmpeg
            exe = imageio_ffmpeg.get_ffmpeg_exe()
            r = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=20,
                               creationflags=0x08000000 if os.name == "nt" else 0)
            self.add(g, OK if r.returncode == 0 else FALHA, "Gravador de vídeo (ffmpeg): " +
                     (r.stdout.split("\n")[0][:60] if r.returncode == 0 else "não funcionou"),
                     "" if r.returncode == 0 else "Rode o INSTALAR.bat de novo.")
        except Exception as e:
            self.add(g, FALHA, f"Gravador de vídeo (ffmpeg) indisponível ({type(e).__name__})", "Rode o INSTALAR.bat de novo.")

    def configuracao(self):
        g = "Programa"
        try:
            import yaml  # noqa: F401
        except Exception:
            self.add(g, FALHA, "Sem o pyyaml não dá para ler a configuração nem as áreas", "Rode o INSTALAR.bat de novo.")
            return
        try:
            import yaml
            p = PASTA / "config.yaml"
            self.cfg = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}
            self.add(g, OK, f"Configuração: {self.cfg.get('empresa', '?')} · {self.cfg.get('unidade', '?')} · "
                            f"{self.cfg.get('posto', '?')}")
        except Exception as e:
            self.add(g, FALHA, f"config.yaml não pôde ser lido ({e})", "Apague o config.yaml: o programa cria outro.")
        try:
            import yaml
            a = PASTA / "areas.yaml"
            dados = (yaml.safe_load(a.read_text(encoding="utf-8")) or {}) if a.exists() else {}
            nomes = {"prateleiras": "prateleira", "leitor": "leitor", "caixa_posto": "caixa do posto"}
            falta = [n for k, n in nomes.items() if not dados.get(k)]
            if falta:
                self.add(g, AVISO, "Áreas do posto ainda não marcadas: " + ", ".join(falta),
                         "Tela Áreas do posto > Marcar usando a câmera ao vivo (com a câmera já no lugar).")
            else:
                self.add(g, OK, "Áreas do posto marcadas")
        except Exception as e:
            self.add(g, AVISO, f"Não consegui ler as áreas ({e})")
        for m in ("yolo11n-pose.pt", "yolo11s-pose.pt"):
            p = PASTA / m
            self.add(g, OK if p.exists() and p.stat().st_size > 1e6 else FALHA,
                     f"Modelo da IA {m}" + ("" if p.exists() else ": arquivo não encontrado"),
                     "" if p.exists() else "Copie a pasta do programa inteira de novo (o arquivo vem no zip).")
        demo = PASTA / "demo" / "demo_esteira_cigarros.mp4"
        self.add(g, OK if demo.exists() else AVISO, "Vídeo de demonstração" + ("" if demo.exists() else " não encontrado"))
        try:
            pasta = self._pasta_resultados()
            pasta.mkdir(parents=True, exist_ok=True)
            t = pasta / ".teste_escrita"
            t.write_text("ok")
            t.unlink()
            self.add(g, OK, f"Pasta dos resultados com permissão de gravação: {pasta}")
        except Exception as e:
            self.add(g, FALHA, f"Não consigo gravar na pasta dos resultados ({e})",
                     "Escolha outra pasta em Configurações > Pasta dos resultados.")

    def ia(self):
        g = "Inteligência artificial"
        self.progresso("Testando a IA (cerca de 30 segundos)...")
        try:
            import numpy as np
            from ultralytics import YOLO
            modelo = (self.cfg or {}).get("modelo_pose", "yolo11n-pose.pt")
            tam = int((self.cfg or {}).get("tamanho_imagem", 640))
            y = YOLO(str(PASTA / modelo))
            img = (np.random.default_rng(0).random((720, 1280, 3)) * 255).astype("uint8")
            y.predict(img, imgsz=tam, verbose=False)
            n, t0 = 8, time.time()
            for _ in range(n):
                y.predict(img, imgsz=tam, verbose=False)
            ms = (time.time() - t0) / n * 1000
            por_seg = 1000 / ms
            meta = float((self.cfg or {}).get("analisar_por_segundo", 8))
            if por_seg >= meta * 1.3:
                self.add(g, OK, f"A IA analisa {por_seg:.0f} imagens por segundo ({ms:.0f} ms cada) · o programa usa {meta:.0f}")
            elif por_seg >= meta * 0.8:
                self.add(g, AVISO, f"A IA analisa {por_seg:.0f} imagens por segundo, no limite ({meta:.0f} necessárias)",
                         "Feche outros programas pesados. Se perder erros, use um PC mais forte.")
            else:
                self.add(g, FALHA, f"A IA analisa só {por_seg:.1f} imagens por segundo ({meta:.0f} necessárias)",
                         "Use a precisão Rápida em Configurações ou um PC mais forte (i5 de 8ª geração ou superior).")
        except Exception as e:
            self.add(g, FALHA, f"A IA não rodou ({type(e).__name__}: {str(e)[:120]})", "Rode o INSTALAR.bat de novo.")

    def cameras(self):
        g = "Câmera"
        try:
            import cv2
        except Exception:
            self.add(g, FALHA, "Sem o OpenCV não dá para testar a câmera", "Rode o INSTALAR.bat de novo.")
            return
        try:
            cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
        except Exception:
            pass
        fonte = str((self.cfg or {}).get("fonte_ao_vivo", "0")).strip()
        achadas = []
        for i in range(4):
            self.progresso(f"Procurando câmeras ({i + 1}/4)...")
            cap = cv2.VideoCapture(i, cv2.CAP_DSHOW) if os.name == "nt" else cv2.VideoCapture(i)
            try:
                if cap.isOpened():
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
                    ok, q = cap.read()
                    if ok and q is not None:
                        achadas.append((i, q.shape[1], q.shape[0], cap.get(cv2.CAP_PROP_FPS) or 0))
            finally:
                cap.release()
        if achadas:
            for i, w, h, fps in achadas:
                sit = OK if w >= 1280 else AVISO
                self.add(g, sit, f"Câmera {i}: {w}x{h}" + (f" a {fps:.0f} fps" if fps else ""),
                         "" if sit == OK else "Resolução baixa: prefira 1280x720 ou mais (GoPro: 1080p).")
        if fonte.isdigit():
            if any(i == int(fonte) for i, *_ in achadas):
                self.add(g, OK, f"A câmera configurada ({fonte}) responde")
            else:
                self.add(g, AVISO,
                         f"A câmera configurada ({fonte}) não respondeu" + ("" if achadas else " e nenhuma câmera está ligada agora"),
                         "Para a câmera ao vivo: ligue a câmera (GoPro: modo webcam, cabo USB), escolha o número "
                         "certo na tela Câmera ao vivo e verifique de novo. Para analisar vídeos gravados não precisa.")
        elif fonte.lower().startswith("rtsp"):
            self.progresso("Testando a câmera IP...")
            cap = cv2.VideoCapture(fonte)
            ok = cap.isOpened() and cap.read()[0]
            cap.release()
            seguro = urlparse(fonte)._replace(netloc=urlparse(fonte).hostname or "").geturl()
            self.add(g, OK if ok else FALHA, f"Câmera IP {seguro}: " + ("responde" if ok else "não respondeu"),
                     "" if ok else "Confira endereço, usuário e senha da câmera e se o PC está na mesma rede.")
        elif not achadas:
            self.add(g, AVISO, "Nenhuma câmera USB encontrada agora",
                     "Normal se a câmera ainda não foi ligada. GoPro: ligue no modo webcam pelo cabo USB.")

    def microfone(self):
        g = "Microfone"
        try:
            import sounddevice as sd
            disp = [(i, d["name"]) for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0]
        except Exception as e:
            self.add(g, AVISO, f"Não consegui listar os microfones ({type(e).__name__})",
                     "Sem microfone o programa confere só pela imagem (sem bipe duplo e sem bipe).")
            return
        if not disp:
            self.add(g, AVISO, "Nenhum microfone encontrado",
                     "Ligue um microfone USB perto do leitor, ou use o da webcam.")
            return
        for i, n in disp[:6]:
            self.add(g, INFO, f"Microfone {i}: {n}")
        conf = str((self.cfg or {}).get("microfone", "")).strip()
        if conf.isdigit() and int(conf) not in [i for i, _ in disp]:
            self.add(g, AVISO, f"O microfone configurado ({conf}) não está ligado",
                     "Escolha o microfone na tela Câmera ao vivo e use Testar bipe (10 s).")
        else:
            self.add(g, OK, "Microfone disponível. Faça o Testar bipe (10 s) com o leitor do posto.")

    def microsoft365(self):
        g = "Microsoft 365"
        m = (self.cfg or {}).get("m365") or {}
        if not m.get("ativo"):
            self.add(g, INFO, "Envio para o Microsoft 365 desligado (opcional)")
            return
        url = str(m.get("url_fluxo", "")).strip()
        host = urlparse(url).hostname
        if not host:
            self.add(g, FALHA, "Envio ligado, mas sem o endereço (URL) do fluxo",
                     "Cole a URL do gatilho do fluxo 2 na tela Microsoft 365.")
            return
        self.progresso("Testando a conexão com o Power Automate...")
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        try:
            t0 = time.time()
            with socket.create_connection((host, 443), timeout=8) as s:
                with ssl.create_default_context().wrap_socket(s, server_hostname=host):
                    pass
            self.add(g, OK, f"O PC alcança o Power Automate ({host}, {(time.time() - t0) * 1000:.0f} ms)")
        except Exception as e:
            self.add(g, FALHA, f"O PC não alcança {host} ({type(e).__name__})",
                     "Peça à TI para liberar o acesso a *.powerplatform.com e *.logic.azure.com (porta 443)."
                     + (f" Há proxy configurado: {proxy}" if proxy else ""))
        fila = PASTA / "fila_envio"
        pend = len(list(fila.glob("*.json"))) if fila.exists() else 0
        falh = len(list((fila / "falhou").glob("*.json"))) if (fila / "falhou").exists() else 0
        self.add(g, OK if not pend and not falh else AVISO, f"Fila de envios: {pend} esperando, {falh} recusados",
                 "" if not falh else "Corrija a causa (veja fila_envio\\envios.log) e use Reenviar o que falhou.")
        for campo, rot in (("site_sharepoint", "site do SharePoint"), ("emails_gestor", "e-mail do gestor"),
                           ("emails_supervisores", "e-mails dos supervisores")):
            if not str(m.get(campo, "")).strip():
                self.add(g, AVISO, f"Falta preencher o {rot}", "Tela Microsoft 365.")

    def automacao(self):
        g = "Automação"
        a = (self.cfg or {}).get("automacao") or {}
        if a.get("iniciar_com_windows"):
            p = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "ConfereVideo_iniciar.vbs"
            self.add(g, OK if p.exists() else FALHA, "Abrir com o Windows: " + ("atalho criado" if p.exists() else "atalho não encontrado"),
                     "" if p.exists() else "Tela Automação > desmarque e marque de novo > Salvar.")
        else:
            self.add(g, INFO, "Abrir com o Windows: desligado")
        self.add(g, INFO, "Turnos: " + (a.get("turnos") or "não configurados (um relatório ao parar)"))
        self.add(g, INFO, f"Guardar recortes por {a.get('guardar_dias', 90)} dias")

    # ------------------------------------------------------------------ geral
    def _pasta_resultados(self):
        p = Path(str((self.cfg or {}).get("pasta_resultados", "resultados")))
        return p if p.is_absolute() else PASTA / p

    def _pasta_resultados_existente(self):
        p = self._pasta_resultados()
        while not p.exists() and p != p.parent:
            p = p.parent
        return p

    def rodar(self, testar_ia=True, testar_camera=True):
        for nome, fn in (("sistema", self.sistema), ("pacotes", self.pacotes), ("config", self.configuracao),
                         ("ia", self.ia if testar_ia else None), ("camera", self.cameras if testar_camera else None),
                         ("mic", self.microfone), ("m365", self.microsoft365), ("auto", self.automacao)):
            if fn is None:
                continue
            try:
                fn()
            except Exception as e:  # um teste nunca derruba os outros
                self.add("Geral", AVISO, f"O teste '{nome}' não terminou ({type(e).__name__}: {e})")
        return self

    def resumo(self):
        falhas = [i for i in self.itens if i[1] == FALHA]
        avisos = [i for i in self.itens if i[1] == AVISO]
        if falhas:
            return f"FALTA RESOLVER {len(falhas)} ponto(s) antes de usar."
        if avisos:
            return f"PRONTO PARA USAR, com {len(avisos)} ponto(s) de atenção."
        return "PRONTO PARA USAR."

    def texto(self):
        linhas = ["ConfereVídeo · verificação do PC", f"{datetime.now():%d/%m/%Y %H:%M} · {socket.gethostname()}",
                  "", "RESULTADO: " + self.resumo(), ""]
        marca = {OK: "[ OK ]", AVISO: "[ !! ]", FALHA: "[FALTA]", INFO: "[ -- ]"}
        grupo = None
        for g, sit, txt, res in self.itens:
            if g != grupo:
                linhas += ["", g.upper()]
                grupo = g
            linhas.append(f"  {marca[sit]} {txt}")
            if res and sit in (AVISO, FALHA):
                linhas.append(f"          -> {res}")
        acoes = []
        for g, s, t, r in sorted(self.itens, key=lambda i: i[1] != FALHA):
            if s in (FALHA, AVISO) and r and r not in acoes:
                acoes.append(r)
        if acoes:
            linhas += ["", "O QUE FAZER", *[f"  {n}. {r}" for n, r in enumerate(acoes, 1)]]
        linhas += ["", "Mande este arquivo (diagnostico.txt) para quem dá suporte ao ConfereVídeo, se precisar."]
        return "\n".join(linhas) + "\n"

    def salvar(self, caminho=None):
        caminho = Path(caminho or PASTA / "diagnostico.txt")
        caminho.write_text(self.texto(), encoding="utf-8-sig")
        (caminho.with_suffix(".json")).write_text(json.dumps(
            [{"grupo": g, "situacao": s, "texto": t, "resolver": r} for g, s, t, r in self.itens],
            ensure_ascii=False, indent=1), encoding="utf-8")
        return caminho


def main():
    try:  # console do Windows em UTF-8 para os acentos
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    d = Diagnostico(progresso=lambda t: print("  ...", t, flush=True))
    print("ConfereVídeo · verificando este PC (cerca de 1 minuto)\n", flush=True)
    d.rodar(testar_ia="--sem-ia" not in sys.argv, testar_camera="--sem-camera" not in sys.argv)
    arq = d.salvar()
    print("\n" + d.texto())
    print(f"Salvo em {arq}")
    return 1 if any(s == FALHA for _, s, _, _ in d.itens) else 0


if __name__ == "__main__":
    sys.exit(main())
