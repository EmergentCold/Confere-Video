"""
ConfereVídeo - motor de análise
================================
Acompanha a mão do operador entre as áreas marcadas (prateleira -> leitor -> caixa)
e, opcionalmente, o som do bipe. Para cada erro grava um recorte do vídeo.

Usado pelo programa com janela (app.py) e pela linha de comando:
    python motor.py video.mp4 [pasta ...]
    python motor.py --ao-vivo 0            # câmera/webcam/GoPro (webcam) nº 0
    python motor.py --ao-vivo rtsp://...   # câmera IP
"""
from __future__ import annotations

import base64
import bisect
import csv
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import wave
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np
import yaml

from integracao import PADRAO_M365, sigla

os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

PASTA = Path(__file__).resolve().parent
EXTENSOES = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".3gp"}
NOME_PRODUTO = "ConfereVídeo"
FALHAS_SEGUIDAS_MAX = 40  # quadros seguidos com erro (~5 s) antes de desistir da câmera ao vivo

TIPOS = {
    "sem_leitor": "Colocou na caixa sem passar no leitor",
    "caixa_errada": "Colocou em outra caixa",
    "sem_bipe": "Passou no leitor, mas não bipou",
    "bipe_duplo": "Bipe duplo para um item",
}
TIPOS_CURTO = {"sem_leitor": "Sem passar no leitor", "caixa_errada": "Outra caixa",
               "sem_bipe": "Sem bipe", "bipe_duplo": "Bipe duplo"}
AVISO = {"sem_leitor": "ERRO: NAO PASSOU NO LEITOR", "caixa_errada": "ERRO: CAIXA ERRADA",
         "sem_bipe": "ERRO: PASSOU SEM BIPAR", "bipe_duplo": "ERRO: BIPE DUPLO"}

PADRAO = {
    "empresa": "Minha Empresa",
    "unidade": "Unidade",
    "nome_local": "Esteira de separação",
    "posto": "Posto 01",
    "logo": "",
    "modelo_pose": "yolo11n-pose.pt",
    "tamanho_imagem": 640,
    "confianca_pessoa": 0.20,
    "confianca_punho": 0.30,
    "analisar_por_segundo": 8,
    "estender_mao": 0.35,
    "quadros_para_confirmar": {"prateleira": 2, "leitor": 1, "caixa_posto": 2, "outras_caixas": 2},
    "tempo_max_ciclo_seg": 20,
    "verificar": {"sem_leitor": True, "caixa_errada": True, "sem_bipe": True, "bipe_duplo": True},
    "usar_som_do_bipe": True,
    "microfone": "",
    "bipe_freq_hz": 0,
    "bipe_limiar_db": 15,
    "bipe_folga_seg": 0.6,
    "segundos_antes": 3,
    "segundos_depois": 3,
    "recorte_max_seg": 25,
    "fps_gravacao_ao_vivo": 15,
    "pasta_resultados": "resultados",
    "fonte_ao_vivo": "0",
    "automacao": {
        "iniciar_com_windows": False,   # abre sozinho quando o PC liga
        "monitorar_ao_abrir": False,    # já começa a câmera ao vivo ao abrir
        "turnos": "",                   # ex.: "06:00, 14:20, 22:35" -> um relatório por turno
        "avisar_camera_parada_min": 2,  # avisa no Teams se a câmera ficar sem imagem
        "guardar_dias": 90,             # apaga recortes mais antigos (LGPD); 0 = nunca
        "pdf_turno": True,              # gera o relatório em PDF no fim de cada turno
        "manter_pc_acordado": True,     # impede o Windows de suspender durante a câmera ao vivo
    },
    "m365": dict(PADRAO_M365),
}
ZONAS = ["prateleira", "leitor", "caixa_posto", "outras_caixas"]
CORES = {"prateleira": (60, 160, 230), "leitor": (230, 200, 0), "caixa_posto": (60, 180, 60),
         "outras_caixas": (60, 60, 220)}


# =========================================================================
# Configuração e utilidades
# =========================================================================
def mesclar(base, novo):
    out = dict(base)
    for k, v in (novo or {}).items():
        if v is None:
            continue
        out[k] = mesclar(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def ler_yaml(c):
    return (yaml.safe_load(Path(c).read_text(encoding="utf-8")) or {}) if c and Path(c).exists() else {}


def carregar_config(caminho=PASTA / "config.yaml"):
    return mesclar(PADRAO, ler_yaml(caminho))


def salvar_config(cfg, caminho=PASTA / "config.yaml"):
    Path(caminho).write_text("# Configuração do ConfereVídeo (também editável pela tela Configurações)\n" +
                             yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")


def caminho_resultados(cfg):
    p = Path(cfg["pasta_resultados"])
    return p if p.is_absolute() else PASTA / p


def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg") or "ffmpeg"


def registrar_erro(texto):
    """Anota no erro.log da pasta do programa (ele roda sem janela de comando, então é ali que o erro aparece)."""
    try:
        with open(PASTA / "erro.log", "a", encoding="utf-8") as f:
            f.write(f"\n[{datetime.now():%d/%m/%Y %H:%M:%S}]\n{texto}\n")
    except Exception:
        pass


def _run(cmd):
    kw = {"capture_output": True}
    if os.name == "nt":
        kw["creationflags"] = 0x08000000  # sem janela preta
    return subprocess.run(cmd, **kw)


def hms(s):
    s = max(0, int(s))
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def carregar_modelo(cfg):
    from ultralytics import YOLO
    m = Path(cfg["modelo_pose"])
    if not m.is_absolute() and (PASTA / m).exists():
        m = PASTA / m  # a IA vem na pasta do programa: não depende da pasta de onde ele foi aberto
    return YOLO(str(m))


# =========================================================================
# Automação: turnos, limpeza de recortes antigos, PC acordado
# =========================================================================
def ler_turnos(cfg):
    """'06:00, 14:20, 22:35' -> [(6, 0), (14, 20), (22, 35)] (ordenado, sem repetidos)."""
    txt = str((cfg.get("automacao") or {}).get("turnos", "") or "")
    hs = set()
    for h, m in re.findall(r"(\d{1,2})[:h](\d{2})", txt):
        if int(h) < 24 and int(m) < 60:
            hs.add((int(h), int(m)))
    return sorted(hs)


def turno_de(cfg, quando=None):
    """Retorna (nome, início, fim) do turno que contém 'quando'; (None, None, None) se não há turnos."""
    ts = ler_turnos(cfg)
    if not ts:
        return None, None, None
    quando = quando or datetime.now()
    dia = quando.replace(hour=0, minute=0, second=0, microsecond=0)
    marcos = []
    for d in (-1, 0, 1):
        for i, (h, m) in enumerate(ts):
            marcos.append((dia + timedelta(days=d, hours=h, minutes=m), i))
    marcos.sort()
    for (ini, i), (fim, _) in zip(marcos, marcos[1:]):
        if ini <= quando < fim:
            return f"{i + 1}º turno", ini, fim
    return None, None, None


def limpar_antigos(cfg, aviso=None):
    """Apaga sessões (recortes, fotos, relatórios) mais antigas que 'guardar_dias'."""
    dias = int((cfg.get("automacao") or {}).get("guardar_dias", 0) or 0)
    base = caminho_resultados(cfg)
    if dias <= 0 or not base.exists():
        return 0
    limite = datetime.now() - timedelta(days=dias)
    n = 0
    for d in base.iterdir():
        m = re.match(r"(\d{4}-\d\d-\d\d)_(\d{6})", d.name)
        if not (d.is_dir() and m):
            continue
        try:
            quando = datetime.strptime(m.group(1) + m.group(2), "%Y-%m-%d%H%M%S")
        except ValueError:
            continue
        if quando < limite:
            shutil.rmtree(d, ignore_errors=True)
            n += 1
    if n and aviso:
        aviso(f"Limpeza automática: {n} sessões com mais de {dias} dias apagadas.")
    return n


def manter_acordado(ligar=True):
    """No Windows, impede que o PC suspenda/desligue a tela enquanto a câmera está ligada."""
    if os.name != "nt":
        return
    try:
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED, ES_DISPLAY_REQUIRED = 0x80000000, 0x00000001, 0x00000002
        ctypes.windll.kernel32.SetThreadExecutionState(
            ES_CONTINUOUS | (ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED if ligar else 0))
    except Exception:
        pass


# =========================================================================
# Áreas
# =========================================================================
class Areas:
    def __init__(self, dados, w, h):
        def pol(p):
            return np.array([(x * w, y * h) for x, y in p], np.float32) if p and len(p) >= 3 else None

        def lista(v):
            return [q for q in (pol(p) for p in (v or [])) if q is not None]

        self.zonas = {
            "prateleira": lista(dados.get("prateleiras")),
            "leitor": [q for q in [pol(dados.get("leitor"))] if q is not None],
            "caixa_posto": [q for q in [pol(dados.get("caixa_posto"))] if q is not None],
            "outras_caixas": lista(dados.get("outras_caixas")),
        }
        self.operador = pol(dados.get("area_operador"))

    @staticmethod
    def faltando(dados):
        nomes = {"prateleiras": "prateleira", "leitor": "leitor", "caixa_posto": "caixa do posto"}
        return [n for k, n in nomes.items() if not dados.get(k)]

    def onde(self, p):
        return {z for z, pols in self.zonas.items()
                if any(cv2.pointPolygonTest(q, (float(p[0]), float(p[1])), False) >= 0 for q in pols)}

    def centro(self, z):
        return self.zonas[z][0].mean(axis=0)


# =========================================================================
# Som do bipe
# =========================================================================
NFFT, HOP, SR_AUDIO = 512, 160, 16000


def _espectro(a):
    n = 1 + max(0, (len(a) - NFFT) // HOP)
    if len(a) < NFFT:
        return np.zeros((0, NFFT // 2 + 1), np.float32)
    idx = np.arange(NFFT)[None, :] + HOP * np.arange(n)[:, None]
    return (20 * np.log10(np.abs(np.fft.rfft(a[idx] * np.hanning(NFFT)[None, :], axis=1)) + 1e-6)).astype(np.float32)


def frequencia_do_bipe(audio):
    """Frequência (Hz) que mais 'salta' do ruído: o bipe do leitor."""
    freqs = np.fft.rfftfreq(NFFT, 1 / SR_AUDIO)
    banda = (freqs >= 1000) & (freqs <= 7000)
    notas = []
    for i in range(0, len(audio), SR_AUDIO * 60):
        S = _espectro(audio[i:i + SR_AUDIO * 60])
        if len(S) >= 50:
            notas.append(np.percentile(S, 99.7, axis=0) - np.median(S, axis=0))
    if not notas:
        return 0.0
    sal = np.mean(notas, axis=0)
    sal[~banda] = -1e9
    return float(freqs[int(np.argmax(sal))])


class DetectorBipe:
    """Detecta bipes em fluxo de áudio (usado tanto em arquivo quanto ao vivo)."""

    def __init__(self, freq, limiar_db):
        k = int(round(freq / (SR_AUDIO / NFFT)))
        self.ks = slice(max(0, k - 2), k + 3)
        self.limiar = limiar_db
        self.hist = deque(maxlen=1500)
        self.ini, self.ult, self.j = None, -99, 0

    def processar(self, S, t0):
        """S: espectro (quadros x bins); t0: tempo do 1º quadro. Retorna tempos de bipes."""
        achados = []
        if not len(S):
            return achados
        e = S[:, self.ks].max(axis=1) - np.median(S, axis=1)
        self.hist.extend(e.tolist())
        base = float(np.median(self.hist))
        for i, v in enumerate(e):
            j = self.j + i
            if v > base + self.limiar:
                if self.ini is None:
                    self.ini = (j, t0 + i * HOP / SR_AUDIO)
                self.ult = j
            elif self.ini is not None and j - self.ult > 3:
                dur = (self.ult - self.ini[0] + 1) * HOP / SR_AUDIO
                if 0.03 <= dur <= 0.5:
                    achados.append(self.ini[1])
                self.ini = None
        self.j += len(e)
        return achados


def ler_audio(video):
    try:
        r = _run([ffmpeg_exe(), "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", str(SR_AUDIO),
                  "-f", "s16le", "-"])
        if r.returncode != 0 or not r.stdout:
            return None
        return np.frombuffer(r.stdout, np.int16).astype(np.float32) / 32768.0
    except Exception:
        return None


def bipes_do_arquivo(audio, cfg):
    if audio is None or len(audio) < SR_AUDIO:
        return [], 0.0
    freq = float(cfg["bipe_freq_hz"] or 0) or frequencia_do_bipe(audio)
    det = DetectorBipe(freq, cfg["bipe_limiar_db"])
    bipes = []
    bloco = SR_AUDIO * 30
    for i in range(0, len(audio), bloco):
        trecho = audio[i:i + bloco + NFFT - HOP]
        S = _espectro(trecho)
        S = S[: (bloco // HOP)] if i + bloco < len(audio) else S
        bipes += det.processar(S, i / SR_AUDIO)
    return bipes, freq


def esquecer_bipes(bipes, antes_de):
    """Apaga da lista (em ordem de tempo) os bipes anteriores a 'antes_de', sem trocar o objeto:
    o Ciclo lê a mesma lista enquanto o microfone escreve nela."""
    k = bisect.bisect_left(bipes, antes_de)
    if k:
        del bipes[:k]


class MicrofoneAoVivo:
    """Escuta o microfone do PC, detecta bipes e guarda os últimos segundos de áudio para os recortes."""

    def __init__(self, cfg, aviso=print):
        self.cfg = cfg
        self.aviso = aviso
        self.bipes = []
        self.freq = float(cfg["bipe_freq_hz"] or 0)
        self.det = DetectorBipe(self.freq, cfg["bipe_limiar_db"]) if self.freq else None
        self.calib = []
        self.buf = deque()  # (t_inicio, bloco)
        self.fila = queue.Queue()
        self.resto, self.t_resto = np.zeros(0, np.float32), None
        self.stream = None
        self.ativo = False

    @staticmethod
    def dispositivos():
        try:
            import sounddevice as sd
            return [(i, d["name"]) for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0]
        except Exception:
            return []

    def iniciar(self):
        import sounddevice as sd
        dev = self.cfg.get("microfone") or None
        if isinstance(dev, str) and dev.strip().isdigit():
            dev = int(dev)

        def cb(indata, frames, tinfo, status):
            self.fila.put((time.time() - frames / SR_AUDIO, indata[:, 0].copy()))

        self.stream = sd.InputStream(samplerate=SR_AUDIO, channels=1, dtype="float32", blocksize=1600,
                                     device=dev, callback=cb)
        self.stream.start()
        self.ativo = True
        threading.Thread(target=self._trabalho, daemon=True).start()
        if not self.freq:
            self.aviso("Microfone: descobrindo o som do bipe nos primeiros 20 s (bipe algumas vezes)...")

    def parar(self):
        self.ativo = False
        try:
            if self.stream:
                self.stream.stop()
                self.stream.close()
        except Exception:
            pass

    def _trabalho(self):
        while self.ativo:
            try:
                t, bloco = self.fila.get(timeout=0.5)
            except queue.Empty:
                continue
            self.buf.append((t, bloco))
            while self.buf and t - self.buf[0][0] > self.cfg["recorte_max_seg"] + 15:
                self.buf.popleft()
            if self.t_resto is None:
                self.t_resto = t
            self.resto = np.concatenate([self.resto, bloco])
            S = _espectro(self.resto)
            n = len(S)
            if not n:
                continue
            t0 = self.t_resto
            self.resto = self.resto[n * HOP:]
            self.t_resto = t0 + n * HOP / SR_AUDIO
            if self.det is None:
                self.calib.append(S)
                if sum(len(x) for x in self.calib) * HOP / SR_AUDIO >= 20:
                    tudo = np.concatenate(self.calib)
                    sal = np.percentile(tudo, 99.7, axis=0) - np.median(tudo, axis=0)
                    freqs = np.fft.rfftfreq(NFFT, 1 / SR_AUDIO)
                    sal[(freqs < 1000) | (freqs > 7000)] = -1e9
                    self.freq = float(freqs[int(np.argmax(sal))])
                    self.det = DetectorBipe(self.freq, self.cfg["bipe_limiar_db"])
                    self.calib = []
                    self.aviso(f"Microfone: bipe em ~{self.freq:.0f} Hz")
                continue
            self.bipes += self.det.processar(S, t0)
            # ao vivo o programa fica dias ligado: só interessam os bipes do item atual
            esquecer_bipes(self.bipes, t - self.cfg["tempo_max_ciclo_seg"] - 60)

    def audio_entre(self, a, b):
        partes = []
        for t, bl in list(self.buf):
            fim = t + len(bl) / SR_AUDIO
            if fim < a or t > b:
                continue
            i0 = max(0, int((a - t) * SR_AUDIO))
            i1 = min(len(bl), int((b - t) * SR_AUDIO))
            partes.append(bl[i0:i1])
        return np.concatenate(partes) if partes else None

    @staticmethod
    def calibrar(segundos=10, dispositivo=None):
        import sounddevice as sd
        dev = int(dispositivo) if isinstance(dispositivo, str) and dispositivo.isdigit() else (dispositivo or None)
        a = sd.rec(int(segundos * SR_AUDIO), samplerate=SR_AUDIO, channels=1, dtype="float32", device=dev)
        sd.wait()
        a = a[:, 0]
        freq = frequencia_do_bipe(a)
        n = len(DetectorBipe(freq, 15).processar(_espectro(a), 0)) if freq else 0
        return freq, n


# =========================================================================
# Ciclo da mão: prateleira -> leitor -> caixa
# =========================================================================
class Ciclo:
    """Segue a mão que pegou o item: prateleira -> leitor -> caixa.

    - só a mão que pegou na prateleira conta para leitor e caixa (a outra mão
      parada perto do leitor não vale como "passou no leitor");
    - cada área tolera 1 quadro de falha (contador com histerese);
    - uma nova pegada na prateleira sempre inicia um novo item (um item cuja
      soltura não foi vista não se mistura com o próximo).
    """

    def __init__(self, cfg, bipes=None):
        self.cfg = cfg
        self.bipes = bipes  # lista (pode crescer ao vivo) ou None
        self.k = cfg["quadros_para_confirmar"]
        self.cont = {}      # (mao, zona) -> contador
        self.disparou = {}  # (mao, zona) -> já disparou nesta entrada
        self.n_ciclos = 0
        self.n_ok = 0
        self.n_incompletos = 0
        self.escala = None  # diagonal da imagem (pixels) para limitar o salto da mão
        self.reset()

    def reset(self):
        self.estado, self.t_ini, self.passou_leitor, self.trilha, self.ativa = "livre", None, False, [], None

    def _novos(self, zonas_por_mao):
        """Dispara uma zona quando a mão esteve nela em k dos últimos k+1 quadros
        (tolera 1 quadro de falha); rearma depois de 2 quadros seguidos fora."""
        novos = {}
        maos = set(zonas_por_mao) | {m for m, _ in self.cont}
        for m in maos:
            zs = zonas_por_mao.get(m, set())
            for z in ZONAS:
                ch = (m, z)
                hist = self.cont.setdefault(ch, deque(maxlen=self.k[z] + 1))
                hist.append(z in zs)
                if len(hist) >= 2 and not hist[-1] and not hist[-2]:
                    self.disparou[ch] = False
                if sum(hist) >= self.k[z] and hist[-1] and not self.disparou.get(ch):
                    self.disparou[ch] = True
                    novos.setdefault(m, set()).add(z)
        return novos

    def _iniciar(self, t, mao, ponto):
        if self.estado == "carregando":
            self.n_incompletos += 1
        self.reset()
        self.estado, self.t_ini, self.ativa = "carregando", t, mao
        self.trilha = [(t, ponto)] if ponto is not None else []

    def atualizar(self, t, zonas_mao, ponto=None, pontos_por_mao=None):
        """zonas_mao: {id_mao: set(zonas)} (ou um set simples = uma mão só)."""
        if isinstance(zonas_mao, set):
            zonas_mao = {0: zonas_mao}
            pontos_por_mao = {0: ponto} if ponto is not None else {}
        pontos_por_mao = pontos_por_mao or {}
        erros = []
        # a IA pode trocar "mão esquerda"/"mão direita" quando o braço cruza o corpo:
        # segue a mão ativa pela continuidade do movimento
        if self.estado == "carregando" and self.trilha and pontos_por_mao:
            ult = self.trilha[-1][1]
            m_perto = min(pontos_por_mao, key=lambda m: (pontos_por_mao[m][0] - ult[0]) ** 2 + (pontos_por_mao[m][1] - ult[1]) ** 2)
            d = ((pontos_por_mao[m_perto][0] - ult[0]) ** 2 + (pontos_por_mao[m_perto][1] - ult[1]) ** 2) ** 0.5
            if self.escala is None or d <= self.escala * 0.18:
                self.ativa = m_perto
        novos = self._novos(zonas_mao)
        if self.estado == "carregando":
            p = pontos_por_mao.get(self.ativa, ponto)
            if p is not None:
                self.trilha.append((t, p))
            if t - self.t_ini > self.cfg["tempo_max_ciclo_seg"]:
                self.n_incompletos += 1
                self.reset()
        # pegou na prateleira: sempre começa um item novo
        for m, zs in novos.items():
            if "prateleira" in zs:
                self._iniciar(t, m, pontos_por_mao.get(m, ponto))
                break
        if self.estado == "livre":
            for m, zs in novos.items():
                if "leitor" in zs:  # prateleira não vista: começa no leitor
                    self._iniciar(t, m, pontos_por_mao.get(m, ponto))
                    self.passou_leitor = True
                    break
            return erros
        zs = novos.get(self.ativa, set())
        if "leitor" in zs:
            self.passou_leitor = True
        destino = "caixa_posto" if "caixa_posto" in zs else ("outras_caixas" if "outras_caixas" in zs else None)
        if destino:
            v = self.cfg["verificar"]
            info = {"t_ini": self.t_ini, "t": t, "trilha": list(self.trilha)}
            if destino == "outras_caixas" and v["caixa_errada"]:
                erros.append(dict(info, tipo="caixa_errada"))
            if not self.passou_leitor and v["sem_leitor"]:
                erros.append(dict(info, tipo="sem_leitor"))
            if self.passou_leitor and self.bipes is not None:
                f = self.cfg["bipe_folga_seg"]
                n = sum(1 for b in list(self.bipes) if self.t_ini - f <= b <= t + f)
                info["bipes"] = n
                if n == 0 and v["sem_bipe"]:
                    erros.append(dict(info, tipo="sem_bipe"))
                elif n >= 2 and v["bipe_duplo"]:
                    erros.append(dict(info, tipo="bipe_duplo"))
            self.n_ciclos += 1
            if not erros:
                self.n_ok += 1
            self.reset()
        return erros


# =========================================================================
# Análise de um quadro (pose + áreas + desenho)
# =========================================================================
class Analisador:
    def __init__(self, cfg, areas_dados, modelo, bipes=None):
        self.cfg, self.dados, self.modelo = cfg, areas_dados, modelo
        self.ciclo = Ciclo(cfg, bipes)
        self.areas = None
        self.aviso_txt, self.aviso_ate = None, -1e18
        self.primeiro = True

    def novo_video(self):
        self.primeiro = True
        self.ciclo.reset()

    def _operador(self, res):
        if res.boxes is None or not len(res.boxes) or res.keypoints is None or res.keypoints.conf is None:
            return None
        caixas = res.boxes.xyxy.cpu().numpy()
        confs = res.boxes.conf.cpu().numpy()
        kxy, kcf = res.keypoints.xy.cpu().numpy(), res.keypoints.conf.cpu().numpy()
        alvo = (self.areas.centro("leitor") + self.areas.centro("caixa_posto")) / 2
        melhor, md = None, 1e18
        for i, (b, c) in enumerate(zip(caixas, confs)):
            if c < self.cfg["confianca_pessoa"]:
                continue
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            if self.areas.operador is not None and cv2.pointPolygonTest(self.areas.operador, (float(cx), float(cy)), False) < 0:
                continue
            d = (cx - alvo[0]) ** 2 + (cy - alvo[1]) ** 2
            if d < md:
                melhor, md = i, d
        return None if melhor is None else {"caixa": caixas[melhor], "kxy": kxy[melhor], "kcf": kcf[melhor]}

    def _maos(self, op):
        maos = []
        if op is None:
            return maos
        kxy, kcf, c = op["kxy"], op["kcf"], self.cfg
        for punho, cot in ((9, 7), (10, 8)):
            if kcf[punho] < c["confianca_punho"]:
                continue
            p = kxy[punho].astype(float)
            if kcf[cot] >= c["confianca_punho"]:
                p = p + c["estender_mao"] * (p - kxy[cot])
            maos.append((punho, p))
        return maos

    def processar(self, quadro, t, rotulo=""):
        h, w = quadro.shape[:2]
        self._ultimo_t = t
        if self.areas is None or self._tam != (w, h):
            self.areas, self._tam = Areas(self.dados, w, h), (w, h)
        res = self.modelo.track(quadro, persist=not self.primeiro, imgsz=self.cfg["tamanho_imagem"],
                                conf=self.cfg["confianca_pessoa"], verbose=False, tracker="bytetrack.yaml")[0]
        self.primeiro = False
        op = self._operador(res)
        maos_id = self._maos(op)
        maos = [p for _, p in maos_id]
        zonas = {i: self.areas.onde(p) for i, p in maos_id}
        pontos = {i: p for i, p in maos_id}
        trilha = list(self.ciclo.trilha)
        self.ciclo.escala = (w * w + h * h) ** 0.5
        erros = self.ciclo.atualizar(t, zonas, None, pontos)
        if erros:
            self.aviso_txt = " + ".join(AVISO[e["tipo"]] for e in erros)
            self.aviso_ate = t + 2.5
        img = self.desenhar(quadro, op, maos, rotulo, trilha if erros else None)
        return img, erros

    def desenhar(self, img, op, maos, rotulo, trilha_erro=None):
        out = img.copy()
        esp = max(2, img.shape[1] // 640)
        cam = out.copy()
        for z, pols in self.areas.zonas.items():
            for q in pols:
                cv2.fillPoly(cam, [q.astype(np.int32)], CORES[z])
        out = cv2.addWeighted(cam, 0.2, out, 0.8, 0)
        for z, pols in self.areas.zonas.items():
            for q in pols:
                cv2.polylines(out, [q.astype(np.int32)], True, CORES[z], esp, cv2.LINE_AA)
        if op is not None:
            k, c = op["kxy"], op["kcf"]
            for a, b in ((5, 7), (7, 9), (6, 8), (8, 10), (5, 6)):
                if c[a] > 0.3 and c[b] > 0.3:
                    cv2.line(out, tuple(map(int, k[a])), tuple(map(int, k[b])), (240, 240, 240), esp, cv2.LINE_AA)
        ci = self.ciclo
        pontos = trilha_erro if trilha_erro is not None else (ci.trilha if ci.estado == "carregando" else [])
        cor = (40, 40, 230) if trilha_erro is not None else ((230, 200, 0) if ci.passou_leitor else (255, 255, 255))
        for _, p in pontos[-80:]:
            cv2.circle(out, (int(p[0]), int(p[1])), esp + 1, cor, -1, cv2.LINE_AA)
        for m in maos:
            cv2.circle(out, (int(m[0]), int(m[1])), esp * 4, (0, 220, 255), esp, cv2.LINE_AA)
        esc = max(0.6, img.shape[1] / 1600)

        def caixa_txt(txt, y, fundo, escala=esc):
            (tw, th), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, escala, 2)
            cv2.rectangle(out, (8, y), (22 + tw, y + th + 14), fundo, -1)
            cv2.putText(out, txt, (15, y + th + 6), cv2.FONT_HERSHEY_SIMPLEX, escala, (255, 255, 255), 2, cv2.LINE_AA)
            return th + 20

        st = "aguardando"
        if ci.estado == "carregando":
            st = "pegou > " + ("passou no leitor > " if ci.passou_leitor else "NAO passou no leitor > ") + "..."
        y = 8 + caixa_txt(st, 8, (30, 30, 30))
        if self.aviso_txt and self._ultimo_t <= self.aviso_ate:
            caixa_txt(self.aviso_txt, y, (40, 40, 220), esc * 1.1)
        (tw, th), _ = cv2.getTextSize(rotulo, cv2.FONT_HERSHEY_SIMPLEX, esc, 2)
        cv2.rectangle(out, (8, out.shape[0] - th - 22), (22 + tw, out.shape[0] - 8), (30, 30, 30), -1)
        cv2.putText(out, rotulo, (15, out.shape[0] - 15), cv2.FONT_HERSHEY_SIMPLEX, esc, (255, 255, 255), 2, cv2.LINE_AA)
        return out

    _ultimo_t = 0.0
    _tam = None


# =========================================================================
# Gravação de recortes
# =========================================================================
def _salvar_wav(caminho, audio):
    with wave.open(str(caminho), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR_AUDIO)
        w.writeframes((np.clip(audio, -1, 1) * 32000).astype(np.int16).tobytes())


def gravar_quadros(quadros, saida, audio=None):
    """quadros: lista (t, jpg). Gera mp4 H.264 (com áudio, se houver)."""
    if len(quadros) < 2:
        return False
    dur = max(0.5, quadros[-1][0] - quadros[0][0])
    fps = min(30.0, max(2.0, (len(quadros) - 1) / dur))
    with tempfile.TemporaryDirectory() as tmp:
        for i, (_, jpg) in enumerate(quadros):
            Path(tmp, f"{i:05d}.jpg").write_bytes(jpg)
        cmd = [ffmpeg_exe(), "-v", "error", "-y", "-framerate", f"{fps:.3f}", "-i", str(Path(tmp, "%05d.jpg"))]
        if audio is not None and len(audio) > SR_AUDIO // 4:
            _salvar_wav(Path(tmp, "a.wav"), audio)
            cmd += ["-i", str(Path(tmp, "a.wav")), "-c:a", "aac", "-b:a", "96k", "-shortest"]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
                "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-movflags", "+faststart", str(saida)]
        return _run(cmd).returncode == 0


def cortar_video(video, ini, fim, saida):
    cmd = [ffmpeg_exe(), "-v", "error", "-y", "-ss", f"{ini:.2f}", "-i", str(video), "-t", f"{fim - ini:.2f}",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(saida)]
    return _run(cmd).returncode == 0


def jpg(img, largura=1280, qualidade=82):
    if img.shape[1] > largura:
        img = cv2.resize(img, None, fx=largura / img.shape[1], fy=largura / img.shape[1])
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, qualidade])[1].tobytes()


# =========================================================================
# Sessão: guarda erros, contagens e gera relatório
# =========================================================================
class Sessao:
    def __init__(self, cfg, modo, turno=None):
        self.cfg, self.modo = cfg, modo
        self.inicio = datetime.now()
        self.fim = None
        self.turno = turno or ""
        self.id = f"{sigla(cfg.get('posto'))}-{self.inicio:%Y%m%d-%H%M%S}" + ("-DEMO" if modo == "demo" else "")
        self.pasta = caminho_resultados(cfg) / f"{self.inicio:%Y-%m-%d_%H%M%S}_{modo}"
        (self.pasta / "recortes").mkdir(parents=True, exist_ok=True)
        (self.pasta / "fotos").mkdir(parents=True, exist_ok=True)
        self.erros, self.fontes = [], []
        self.ciclos = self.ok = 0
        self.periodo = [None, None]
        self.lock = threading.Lock()
        self.gravando = 0  # recortes ainda sendo gravados

    def esperar_gravacoes(self, limite=90):
        t0 = time.time()
        while self.gravando > 0 and time.time() - t0 < limite:
            time.sleep(0.2)

    def finalizar(self, pdf=True):
        """Fecha a sessão: relatório HTML e (opcional) PDF. Retorna (html, pdf)."""
        self.fim = self.fim or datetime.now()
        html = self.salvar()
        arq_pdf = None
        if pdf:
            try:
                from relatorio_pdf import gerar_pdf
                arq_pdf = gerar_pdf(self.resumo(), self.pasta, self.pasta / "relatorio.pdf", self.cfg.get("logo"))
            except Exception as e:  # o PDF nunca pode derrubar a câmera
                (self.pasta / "erro_pdf.txt").write_text(str(e), encoding="utf-8")
        return html, arq_pdf

    def marcar_periodo(self, quando):
        if quando is None:
            return
        a, b = self.periodo
        self.periodo = [quando if a is None or quando < a else a, quando if b is None or quando > b else b]

    def registrar(self, erro, quando, fonte, t_video=None):
        with self.lock:
            n = len(self.erros) + 1
            reg = {"n": n, "tipo": erro["tipo"], "base": f"{n:04d}_{erro['tipo']}", "id": f"{self.id}-{n:03d}",
                   "quando": quando.strftime("%d/%m/%Y %H:%M:%S") if quando else "",
                   "quando_iso": quando.astimezone().isoformat(timespec="seconds") if quando else "",
                   "hora": quando.hour if quando else None, "fonte": fonte,
                   "t_video": hms(t_video) if t_video is not None else "", "bipes": erro.get("bipes"),
                   "original": "", "marcado": "", "duracao": 0}
            self.erros.append(reg)
        self.marcar_periodo(quando)
        return reg

    def foto(self, reg, img):
        cv2.imwrite(str(self.pasta / "fotos" / f"{reg['base']}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 85])

    def resumo(self):
        return {"produto": NOME_PRODUTO, "empresa": self.cfg["empresa"], "unidade": self.cfg["unidade"],
                "local": self.cfg["nome_local"], "posto": self.cfg["posto"], "modo": self.modo,
                "id": self.id, "turno": self.turno,
                "inicio": self.inicio.strftime("%d/%m/%Y %H:%M"),
                "fim": self.fim.strftime("%d/%m/%Y %H:%M") if self.fim else "",
                "gerado": datetime.now().strftime("%d/%m/%Y %H:%M"),
                "periodo": [p.strftime("%d/%m/%Y %H:%M") if p else "" for p in self.periodo],
                "ciclos": self.ciclos, "ok": self.ok, "erros": self.erros, "fontes": self.fontes}

    def salvar(self):
        from relatorio import gerar_html
        r = self.resumo()
        with self.lock:
            (self.pasta / "resumo.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
            with open(self.pasta / "erros.csv", "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow(["nº", "código", "empresa", "unidade", "posto", "turno", "data/hora", "erro", "origem",
                            "momento no vídeo", "bipes ouvidos", "recorte original", "recorte marcado", "foto"])
                for e in self.erros:
                    w.writerow([e["n"], e.get("id", ""), r["empresa"], r["unidade"], r["posto"], r["turno"],
                                e["quando"], TIPOS[e["tipo"]],
                                e["fonte"], e["t_video"], "" if e["bipes"] is None else e["bipes"],
                                e["original"], e["marcado"], f"fotos/{e['base']}.jpg"])
            logo = ""
            lp = self.cfg.get("logo")
            if lp and Path(lp).exists():
                ext = Path(lp).suffix.lower().strip(".").replace("jpg", "jpeg")
                logo = f"data:image/{ext};base64," + base64.b64encode(Path(lp).read_bytes()).decode()
            (self.pasta / "relatorio.html").write_text(gerar_html(r, logo), encoding="utf-8")
        return self.pasta / "relatorio.html"


# =========================================================================
# Modo 1: vídeos gravados (GoPro / celular)
# =========================================================================
def inicio_gravacao(video, duracao):
    try:
        r = subprocess.run([ffmpeg_exe(), "-i", str(video)], capture_output=True, text=True, errors="ignore",
                           creationflags=0x08000000 if os.name == "nt" else 0)
        m = re.search(r"creation_time\s*:\s*(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)", r.stderr)
        if m:
            dt = datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S")
            if re.match(r"^(GH|GX|GOPR|GP)", Path(video).name, re.I):
                return dt
            return dt.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
    except Exception:
        pass
    try:
        return datetime.fromtimestamp(Path(video).stat().st_mtime) - timedelta(seconds=duracao)
    except OSError:
        return None


def ordenar_gopro(p):
    m = re.match(r"^(G[HX])(\d\d)(\d{4})", p.stem, re.I)
    if m:
        return (m.group(3), int(m.group(2)), p.name)
    m = re.match(r"^GOPR(\d{4})", p.stem, re.I)
    if m:
        return (m.group(1), 0, p.name)
    m = re.match(r"^GP(\d\d)(\d{4})", p.stem, re.I)
    if m:
        return (m.group(2), int(m.group(1)), p.name)
    return ("~", 0, p.name)


def listar_videos(entradas):
    vids = []
    for e in entradas:
        p = Path(e)
        if p.is_dir():
            vids += sorted((x for x in p.iterdir() if x.suffix.lower() in EXTENSOES), key=ordenar_gopro)
        elif p.exists():
            vids.append(p)
    return vids


def analisar_videos(videos, cfg, areas_dados, modelo, ev=print, parar=None, preview=None, integracao=None):
    """ev(tipo, dados) recebe eventos: 'log', 'progresso', 'erro', 'contagem'. Retorna a Sessao.
    integracao: integracao.Integracao (opcional) para mandar os erros e o resumo ao Microsoft 365."""
    if callable(ev) and ev is print:
        ev = lambda tipo, d=None: print(tipo, d if not isinstance(d, dict) else {k: v for k, v in d.items() if k != "img"})
    sessao = Sessao(cfg, "videos")
    parar = parar or threading.Event()
    total_quadros = 0
    infos = []
    for v in videos:
        cap = cv2.VideoCapture(str(v))
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        infos.append((v, n, cap.get(cv2.CAP_PROP_FPS) or 30))
        total_quadros += n
        cap.release()
    feitos = 0
    an = None
    for v, n_quadros, fps in infos:
        if parar.is_set():
            break
        sessao.fontes.append(Path(v).name)
        dur = n_quadros / fps if n_quadros else 0
        ev("log", f"Analisando {Path(v).name} ({hms(dur)})")
        bipes = None
        if cfg["usar_som_do_bipe"] and (cfg["verificar"]["sem_bipe"] or cfg["verificar"]["bipe_duplo"]):
            bipes, freq = bipes_do_arquivo(ler_audio(v), cfg)
            if len(bipes) < 3:
                ev("log", "  Som: quase nenhum bipe ouvido, verificação de bipe desligada neste vídeo")
                bipes = None
            else:
                ev("log", f"  Som: bipe em ~{freq:.0f} Hz, {len(bipes)} bipes ouvidos")
        if an is None:
            an = Analisador(cfg, areas_dados, modelo, bipes)
        else:
            an.ciclo.bipes = bipes
        an.novo_video()
        c0, ok0 = an.ciclo.n_ciclos, an.ciclo.n_ok
        inicio_real = inicio_gravacao(v, dur)
        passo = max(1, round(fps / cfg["analisar_por_segundo"]))
        buf, pend = deque(), []
        cap = cv2.VideoCapture(str(v))
        idx = 0
        sessao.marcar_periodo(inicio_real)

        def fechar_pend(t, forcar=False):
            for reg in [p for p in pend if forcar or t >= p["_fim"]]:
                qs = [(tt, j) for tt, j in buf if reg["_ini"] <= tt <= reg["_fim"]]
                saida = sessao.pasta / "recortes" / f"{reg['base']}_marcado.mp4"
                if gravar_quadros(qs, saida):
                    reg["marcado"] = f"recortes/{saida.name}"
                pend.remove(reg)
                sessao.salvar()
                if integracao:
                    integracao.erro(cfg, sessao, reg)

        while cap.grab():
            if parar.is_set():
                break
            if idx % passo == 0:
                ok, q = cap.retrieve()
                if not ok:
                    break
                t = idx / fps
                rot = f"{cfg['posto']} | {Path(v).name} | {hms(t)}"
                an._ultimo_t = t
                img, erros = an.processar(q, t, rot)
                buf.append((t, jpg(img, 960, 78)))
                while buf and t - buf[0][0] > cfg["recorte_max_seg"] + 2:
                    buf.popleft()
                for e in erros:
                    quando = inicio_real + timedelta(seconds=t) if inicio_real else None
                    reg = sessao.registrar(e, quando, Path(v).name, t)
                    sessao.foto(reg, img)
                    ini = max(0.0, e["t_ini"] - cfg["segundos_antes"])
                    fim = t + cfg["segundos_depois"]
                    ini = max(ini, fim - cfg["recorte_max_seg"])
                    reg.update(_ini=ini, _fim=fim, duracao=round(fim - ini))
                    saida = sessao.pasta / "recortes" / f"{reg['base']}_original.mp4"
                    if cortar_video(v, ini, fim, saida):
                        reg["original"] = f"recortes/{saida.name}"
                    pend.append(reg)
                    ev("erro", {"reg": reg, "img": img})
                sessao.ciclos = an.ciclo.n_ciclos
                sessao.ok = an.ciclo.n_ok
                fechar_pend(t)
                if preview:
                    preview(img)
                ev("progresso", (feitos + idx) / max(1, total_quadros))
                ev("contagem", (sessao.ciclos, len(sessao.erros), sessao.ok))
            idx += 1
        fechar_pend(1e12, forcar=True)
        if inicio_real:
            sessao.marcar_periodo(inicio_real + timedelta(seconds=dur))
        cap.release()
        feitos += n_quadros
        ev("log", f"  {an.ciclo.n_ciclos - c0} itens conferidos, {an.ciclo.n_ciclos - c0 - (an.ciclo.n_ok - ok0)} com erro")
    for r in sessao.erros:
        for k in ("_ini", "_fim"):
            r.pop(k, None)
    rel, pdf = sessao.finalizar(pdf=(cfg.get("automacao") or {}).get("pdf_turno", True))
    if integracao:
        integracao.sessao(cfg, sessao, pdf)
    ev("fim", str(rel))
    return sessao


# =========================================================================
# Modo 2: ao vivo (câmera USB / GoPro como webcam / câmera IP / vídeo como demonstração)
# =========================================================================
class AoVivo(threading.Thread):
    """Câmera ao vivo: analisa continuamente e grava só os trechos com erro.

    Automações:
    - fecha um relatório por turno (cfg automacao.turnos) e abre o próximo sozinho;
    - reconecta a câmera e avisa (Teams/e-mail) se ficar sem imagem;
    - mantém o PC acordado e apaga sessões antigas (cfg automacao.guardar_dias);
    - manda cada erro e o resumo de cada turno ao Microsoft 365 (integracao).
    """

    def __init__(self, fonte, cfg, areas_dados, modelo, ev=print, preview=None, modo="ao_vivo", integracao=None):
        self.modo = modo
        super().__init__(daemon=True)
        self.fonte, self.cfg, self.dados, self.modelo = str(fonte).strip(), cfg, areas_dados, modelo
        self.ev = ev if ev is not print else (lambda t, d=None: print(t, d if not isinstance(d, dict) else ""))
        self.preview = preview
        self.integracao = integracao
        self.parar_ev = threading.Event()
        self.lock = threading.Lock()
        self.ultimo, self.cont_q = None, 0
        self.orig = deque()   # (t, jpg) na velocidade da câmera
        self.marc = deque()   # (t, jpg) quadros marcados
        self.mic = None
        self.audio_arquivo = None
        self.sessao = None
        self.eh_arquivo = Path(self.fonte).suffix.lower() in EXTENSOES and Path(self.fonte).exists()
        self.t_ultimo_quadro = time.time()
        self.cam_alertada = False
        self._fim_turno = None
        self._base = (0, 0)
        self._pend = []       # erros esperando os segundos "depois" para gravar o recorte

    @property
    def auto(self):
        return self.cfg.get("automacao") or {}

    def parar(self):
        self.parar_ev.set()

    # ---- leitura contínua da câmera (reconecta sozinha) ----
    def _leitor(self):
        cap, ultimo_buf = None, 0
        intervalo_buf = 1.0 / self.cfg["fps_gravacao_ao_vivo"]
        t_inicio_arq = None
        while not self.parar_ev.is_set():
            if cap is None or not cap.isOpened():
                src = int(self.fonte) if self.fonte.isdigit() else self.fonte
                cap = cv2.VideoCapture(src, cv2.CAP_DSHOW) if (isinstance(src, int) and os.name == "nt") else cv2.VideoCapture(src)
                if isinstance(src, int):
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
                if not cap.isOpened():
                    self.ev("log", "Câmera não conectou. Tentando de novo em 5 s...")
                    self.parar_ev.wait(5)
                    continue
                self.ev("log", "Câmera conectada.")
                fps_arq = cap.get(cv2.CAP_PROP_FPS) or 30
                t_inicio_arq = time.time()
                self.t0_arquivo = t_inicio_arq
                n_lidos = 0
            ok, q = cap.read()
            if not ok:
                if self.eh_arquivo:
                    self.ev("log", "Fim do vídeo de demonstração.")
                    self.parar_ev.set()
                    break
                self.ev("log", "Sinal da câmera perdido, reconectando...")
                cap.release()
                cap = None
                self.parar_ev.wait(2)
                continue
            agora = time.time()
            if self.eh_arquivo:  # toca o vídeo na velocidade real
                n_lidos += 1
                alvo = t_inicio_arq + n_lidos / fps_arq
                if alvo > agora:
                    time.sleep(alvo - agora)
                agora = alvo
            with self.lock:
                self.ultimo, self.t_ultimo = q, agora
                self.cont_q += 1
                self.t_ultimo_quadro = time.time()
            if agora - ultimo_buf >= intervalo_buf:
                ultimo_buf = agora
                self.orig.append((agora, jpg(q, 1280, 80)))
                while self.orig and agora - self.orig[0][0] > self.cfg["recorte_max_seg"] + 8:
                    self.orig.popleft()
        if cap is not None:
            cap.release()

    def _audio_entre(self, a, b):
        if self.mic:
            return self.mic.audio_entre(a, b)
        if self.audio_arquivo is not None:
            i0 = max(0, int((a - self.t0_arquivo) * SR_AUDIO))
            i1 = max(0, int((b - self.t0_arquivo) * SR_AUDIO))
            return self.audio_arquivo[i0:i1]
        return None

    # ---- recortes ----
    def _gravar(self, reg, ini, fim, sessao):
        def tarefa():
            try:
                orig = [(t, j) for t, j in list(self.orig) if ini <= t <= fim]
                marc = [(t, j) for t, j in list(self.marc) if ini <= t <= fim]
                audio = self._audio_entre(ini, fim)
                o = sessao.pasta / "recortes" / f"{reg['base']}_original.mp4"
                m = sessao.pasta / "recortes" / f"{reg['base']}_marcado.mp4"
                if gravar_quadros(orig, o, audio):
                    reg["original"] = f"recortes/{o.name}"
                if gravar_quadros(marc, m, audio):
                    reg["marcado"] = f"recortes/{m.name}"
                sessao.salvar()
                self.ev("recorte", reg)
                if self.integracao:
                    self.integracao.erro(self.cfg, sessao, reg)
            finally:
                with sessao.lock:
                    sessao.gravando -= 1
        threading.Thread(target=tarefa, daemon=True).start()

    # ---- sessões e turnos ----
    def _nova_sessao(self, an=None):
        nome, _, fim = turno_de(self.cfg) if self.modo == "ao_vivo" else (None, None, None)
        s = Sessao(self.cfg, self.modo, nome)
        s.fontes.append("Câmera " + (self.fonte if not self.eh_arquivo else Path(self.fonte).name + " (demonstração)"))
        self._base = (an.ciclo.n_ciclos, an.ciclo.n_ok) if an else (0, 0)
        self._fim_turno = fim
        return s

    def _fechar_sessao(self, sessao, final=False):
        """Espera os recortes, gera HTML/PDF e manda o resumo ao Microsoft 365."""
        sessao.fim = sessao.fim or datetime.now()

        def tarefa():
            sessao.esperar_gravacoes()
            rel, pdf = sessao.finalizar(pdf=self.auto.get("pdf_turno", True))
            if self.integracao:
                self.integracao.sessao(self.cfg, sessao, pdf)
            self.ev("sessao_fechada", {"pasta": str(sessao.pasta), "relatorio": str(rel), "turno": sessao.turno,
                                       "ciclos": sessao.ciclos, "erros": len(sessao.erros)})
            return rel
        if final:
            return tarefa()
        threading.Thread(target=tarefa, daemon=True).start()
        return sessao.pasta / "relatorio.html"

    def _vigiar_camera(self):
        """Avisa uma vez quando a câmera fica sem imagem e outra quando volta."""
        if self.eh_arquivo:
            return
        lim = max(30.0, float(self.auto.get("avisar_camera_parada_min", 2) or 2) * 60)
        parado = time.time() - self.t_ultimo_quadro
        posto = self.cfg.get("posto", "posto")
        if parado > lim and not self.cam_alertada:
            self.cam_alertada = True
            quanto = f"{int(parado)} s" if parado < 90 else f"{int(parado // 60)} min"
            txt = (f"A câmera do {posto} está sem imagem há {quanto}. "
                   "O programa continua tentando reconectar sozinho.")
            self.ev("alerta", txt)
            if self.integracao:
                self.integracao.alerta(self.cfg, "Câmera sem imagem", txt, "attention")
        elif parado < 5 and self.cam_alertada:
            self.cam_alertada = False
            txt = f"A câmera do {posto} voltou a mandar imagem. A conferência continua."
            self.ev("alerta", txt)
            if self.integracao:
                self.integracao.alerta(self.cfg, "Câmera voltou", txt, "good")

    def _quadro(self, an, q, tq, pend):
        """Analisa um quadro da câmera: marca erros, agenda os recortes e atualiza a tela."""
        cfg = self.cfg
        an._ultimo_t = tq
        rot = f"{cfg['posto']} | {datetime.fromtimestamp(tq):%d/%m/%Y %H:%M:%S}"
        img, erros = an.processar(q, tq, rot)
        self.marc.append((tq, jpg(img, 960, 78)))
        while self.marc and tq - self.marc[0][0] > cfg["recorte_max_seg"] + 8:
            self.marc.popleft()
        s = self.sessao
        for e in erros:
            reg = s.registrar(e, datetime.fromtimestamp(tq), "ao vivo")
            s.foto(reg, img)
            ini = max(e["t_ini"] - cfg["segundos_antes"], tq - cfg["recorte_max_seg"])
            fim = tq + cfg["segundos_depois"]
            reg["duracao"] = round(fim - ini)
            with s.lock:
                s.gravando += 1
            pend.append((reg, ini, fim, s))
            self.ev("erro", {"reg": reg, "img": img, "pasta": str(s.pasta)})
        s.ciclos, s.ok = an.ciclo.n_ciclos - self._base[0], an.ciclo.n_ok - self._base[1]
        s.marcar_periodo(datetime.fromtimestamp(tq))
        for p in [p for p in pend if tq >= p[2]]:
            pend.remove(p)
            self._gravar(*p)
        if self.preview:
            self.preview(img)
        self.ev("contagem", (s.ciclos, len(s.erros), s.ok))
        if time.time() - self._ult_salvo > 60:
            self._ult_salvo = time.time()
            s.salvar()

    def _limpeza(self):
        threading.Thread(target=limpar_antigos, args=(self.cfg, lambda m: self.ev("log", m)), daemon=True).start()

    def run(self):
        try:
            self._executar()
        except Exception:
            self._parou_com_erro(traceback.format_exc())

    def _parou_com_erro(self, detalhes):
        """A conferência parou sozinha: salva o que já foi visto e avisa (tela, Teams e e-mail)."""
        registrar_erro(detalhes)
        self.parar_ev.set()
        if self.mic:
            self.mic.parar()
        manter_acordado(False)
        rel = ""
        try:
            for p in self._pend:  # erros já marcados: grava os recortes com o que está na memória
                self._gravar(*p)
            self._pend = []
            if self.sessao:
                rel = self._fechar_sessao(self.sessao, final=True)
        except Exception:
            registrar_erro(traceback.format_exc())
        self.ev("fim", str(rel))
        txt = (f"A conferência do {self.cfg.get('posto', 'posto')} parou por um erro inesperado. "
               "Abra o ConfereVídeo e ligue a câmera de novo. Detalhes no arquivo erro.log.")
        self.ev("alerta", txt)
        if self.integracao and not self.eh_arquivo:
            self.integracao.alerta(self.cfg, "Conferência parou", txt, "attention")

    def _executar(self):
        cfg = self.cfg
        if self.auto.get("manter_pc_acordado", True) and not self.eh_arquivo:
            manter_acordado(True)
        self._limpeza()
        ult_limpeza = time.time()
        self.sessao = self._nova_sessao()
        bipes = None
        querem_bipe = cfg["usar_som_do_bipe"] and (cfg["verificar"]["sem_bipe"] or cfg["verificar"]["bipe_duplo"])
        if querem_bipe and self.eh_arquivo:
            self.audio_arquivo = ler_audio(self.fonte)
            b, freq = bipes_do_arquivo(self.audio_arquivo, cfg)
            if len(b) >= 3:
                bipes = []  # preenchido com o tempo real ao tocar
                self._bipes_arquivo = b
                self.ev("log", f"Som do vídeo: bipe em ~{freq:.0f} Hz")
        elif querem_bipe:
            try:
                self.mic = MicrofoneAoVivo(cfg, aviso=lambda m: self.ev("log", m))
                self.mic.iniciar()
                bipes = self.mic.bipes
                self.ev("log", "Microfone ligado: ouvindo os bipes.")
            except Exception as e:
                self.mic = None
                self.ev("log", f"Sem microfone ({e}). Seguindo só com a imagem.")
        an = Analisador(cfg, self.dados, self.modelo, bipes)
        # aquece a IA antes de ligar a câmera (a 1ª análise é sempre mais lenta)
        try:
            self.modelo.predict(np.zeros((720, 1280, 3), np.uint8), imgsz=cfg["tamanho_imagem"], verbose=False)
        except Exception:
            pass
        self.t_ultimo_quadro = time.time()
        threading.Thread(target=self._leitor, daemon=True).start()
        intervalo = 1.0 / cfg["analisar_por_segundo"]
        pend, ult_cont, falhas, ult_log_falha = self._pend, -1, 0, 0.0
        self._ult_salvo = ult_vigia = time.time()
        while not self.parar_ev.is_set():
            if time.time() - ult_vigia >= 1:
                ult_vigia = time.time()
                self._vigiar_camera()
                if self._fim_turno and datetime.now() >= self._fim_turno:
                    antiga = self.sessao
                    self.sessao = self._nova_sessao(an)
                    self._fechar_sessao(antiga)
                    self.ev("turno", {"turno": self.sessao.turno, "anterior": antiga.turno,
                                      "pasta": str(self.sessao.pasta)})
                if time.time() - ult_limpeza > 6 * 3600:
                    ult_limpeza = time.time()
                    self._limpeza()
            with self.lock:
                q, tq, c = self.ultimo, getattr(self, "t_ultimo", 0), self.cont_q
            if q is None or c == ult_cont:
                time.sleep(0.01)
                continue
            ult_cont = c
            t0 = time.time()
            if self.eh_arquivo and bipes is not None and hasattr(self, "_bipes_arquivo"):
                limite = tq - self.t0_arquivo
                while self._bipes_arquivo and self._bipes_arquivo[0] <= limite:
                    bipes.append(self.t0_arquivo + self._bipes_arquivo.pop(0))
            # um quadro com problema não pode desligar a conferência do turno;
            # só desiste (e avisa) se a falha se repetir por vários segundos seguidos
            try:
                self._quadro(an, q, tq, pend)
                falhas = 0
            except Exception:
                falhas += 1
                if time.time() - ult_log_falha > 600:  # no máximo 1 registro a cada 10 min no erro.log
                    ult_log_falha = time.time()
                    registrar_erro("Falha ao analisar um quadro (a conferência continua):\n" + traceback.format_exc())
                if falhas >= FALHAS_SEGUIDAS_MAX:
                    raise
            espera = intervalo - (time.time() - t0)
            if espera > 0:
                time.sleep(espera)
        for p in pend:
            self._gravar(*p)
        self._pend = []
        if self.mic:
            self.mic.parar()
        rel = self._fechar_sessao(self.sessao, final=True)
        manter_acordado(False)
        self.ev("fim", str(rel))


# =========================================================================
# Linha de comando
# =========================================================================
def main():
    import argparse
    ap = argparse.ArgumentParser(description="ConfereVídeo - conferência da separação por vídeo")
    ap.add_argument("videos", nargs="*")
    ap.add_argument("--ao-vivo", metavar="FONTE")
    ap.add_argument("--segundos", type=float, default=0, help="ao vivo: parar depois de N segundos")
    ap.add_argument("--config", default=str(PASTA / "config.yaml"))
    ap.add_argument("--areas", default=str(PASTA / "areas.yaml"))
    a = ap.parse_args()
    cfg = carregar_config(a.config)
    areas = ler_yaml(a.areas)
    falta = Areas.faltando(areas)
    if falta:
        sys.exit(f"Falta marcar: {', '.join(falta)}")
    modelo = carregar_modelo(cfg)
    integ = None
    if (cfg.get("m365") or {}).get("ativo"):
        from integracao import Integracao
        integ = Integracao(lambda: cfg, log=print)
        integ.iniciar()
    if a.ao_vivo:
        av = AoVivo(a.ao_vivo, cfg, areas, modelo, integracao=integ)
        av.start()
        try:
            t0 = time.time()
            while av.is_alive():
                time.sleep(0.5)
                if a.segundos and time.time() - t0 > a.segundos:
                    av.parar()
        except KeyboardInterrupt:
            av.parar()
        av.join(120)
    else:
        analisar_videos(listar_videos(a.videos), cfg, areas, modelo, integracao=integ)
    if integ:  # dá um tempo para a fila sair; o que sobrar vai na próxima vez
        t0 = time.time()
        while integ.pendentes() and time.time() - t0 < 60:
            integ._acorda.set()
            time.sleep(1)


if __name__ == "__main__":
    main()
