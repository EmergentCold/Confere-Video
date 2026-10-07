"""
ConfereVídeo - programa com janela
Conferência da separação por vídeo: ao vivo (câmera) ou de vídeos gravados (GoPro/celular).
"""
import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

PASTA = Path(__file__).resolve().parent
os.chdir(PASTA)
sys.path.insert(0, str(PASTA))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image, ImageTk  # noqa: E402

import integracao  # noqa: E402
import motor  # noqa: E402
import power_platform  # noqa: E402

AUTO = "--auto" in sys.argv  # aberto pela inicialização do Windows: já liga a câmera

if os.name == "nt":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

# ---------------------------------------------------------------- aparência
C = {"ink": "#16202e", "side": "#1e2a3b", "side_on": "#2c3b52", "bg": "#f4f6f9", "card": "#ffffff",
     "line": "#dfe4ec", "muted": "#5b6678", "brand": "#0f4c81", "ok": "#15803d", "bad": "#b91c1c",
     "amar": "#f0c419"}
FONTE = "Segoe UI" if os.name == "nt" else "DejaVu Sans"


def abrir(caminho):
    caminho = str(caminho)
    try:
        if os.name == "nt":
            os.startfile(caminho)  # noqa
        elif sys.platform == "darwin":
            subprocess.Popen(["open", caminho])
        else:
            subprocess.Popen(["xdg-open", caminho])
    except Exception:
        webbrowser.open(Path(caminho).as_uri())


def pasta_inicializar():
    """Pasta 'Inicializar' do Windows (programas que abrem quando o usuário entra)."""
    appdata = os.environ.get("APPDATA")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" if appdata else None


def iniciar_com_windows(ligar):
    """Cria/remove o atalho que abre o ConfereVídeo (já monitorando) quando o PC liga."""
    p = pasta_inicializar()
    if p is None:
        return False, "Disponível só no Windows."
    arq = p / "ConfereVideo_iniciar.vbs"
    if not ligar:
        arq.unlink(missing_ok=True)
        return True, "O ConfereVídeo não abre mais sozinho com o Windows."
    pyw = Path(sys.executable).with_name("pythonw.exe")
    if not pyw.exists():
        pyw = Path(sys.executable)
    vbs = ("' Abre o ConfereVideo ja monitorando (criado pela tela Automacao)\r\n"
           "WScript.Sleep 20000  ' espera a rede e a camera subirem\r\n"
           'Set sh = CreateObject("WScript.Shell")\r\n'
           f'sh.CurrentDirectory = "{PASTA}"\r\n'
           f'sh.Run """{pyw}"" ""{PASTA / "app.py"}"" --auto", 0, False\r\n')
    p.mkdir(parents=True, exist_ok=True)
    arq.write_text(vbs, encoding="utf-16")  # UTF-16 com BOM: o Windows lê caminhos com acento
    return True, "Pronto: o ConfereVídeo vai abrir sozinho, já com a câmera ligada, sempre que o PC ligar."


def estilos(root):
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(".", font=(FONTE, 10), background=C["bg"])
    s.configure("TFrame", background=C["bg"])
    s.configure("Card.TFrame", background=C["card"])
    s.configure("TLabel", background=C["bg"], foreground=C["ink"])
    s.configure("Card.TLabel", background=C["card"])
    s.configure("Muted.TLabel", foreground=C["muted"])
    s.configure("CardMuted.TLabel", background=C["card"], foreground=C["muted"], font=(FONTE, 9))
    s.configure("H1.TLabel", font=(FONTE, 16, "bold"))
    s.configure("H2.TLabel", font=(FONTE, 11, "bold"), foreground=C["muted"])
    s.configure("KpiV.TLabel", background=C["card"], font=(FONTE, 22, "bold"))
    s.configure("KpiBad.TLabel", background=C["card"], font=(FONTE, 22, "bold"), foreground=C["bad"])
    s.configure("KpiOk.TLabel", background=C["card"], font=(FONTE, 22, "bold"), foreground=C["ok"])
    s.configure("TButton", padding=(12, 6))
    s.configure("Primary.TButton", background=C["brand"], foreground="white", font=(FONTE, 10, "bold"))
    s.map("Primary.TButton", background=[("active", "#0c3d68"), ("disabled", "#9db3c8")])
    s.configure("Go.TButton", background=C["ok"], foreground="white", font=(FONTE, 11, "bold"), padding=(18, 8))
    s.map("Go.TButton", background=[("active", "#11652f"), ("disabled", "#a7c9b3")])
    s.configure("Stop.TButton", background=C["bad"], foreground="white", font=(FONTE, 11, "bold"), padding=(18, 8))
    s.map("Stop.TButton", background=[("active", "#8f1515"), ("disabled", "#d9a7a7")])
    s.configure("Treeview", rowheight=26, font=(FONTE, 10), fieldbackground=C["card"], background=C["card"])
    s.configure("Treeview.Heading", font=(FONTE, 9, "bold"), foreground=C["muted"])
    s.configure("TCheckbutton", background=C["bg"])
    s.configure("TRadiobutton", background=C["bg"])
    s.configure("Horizontal.TProgressbar", troughcolor=C["line"], background=C["brand"])


# ---------------------------------------------------------------- componentes
class Preview(tk.Label):
    """Mostra o quadro marcado mais recente."""

    def __init__(self, master, w=800, h=450):
        self._vazio = tk.PhotoImage(width=w, height=h)
        super().__init__(master, bg="#0b1018", fg="#8a96a8", text="A imagem da câmera aparece aqui",
                         font=(FONTE, 11), image=self._vazio, compound="center", bd=0)
        self.w, self.h = w, h
        self._img = None

    def mostrar(self, bgr):
        h, w = bgr.shape[:2]
        e = min(self.w / w, self.h / h)
        rgb = cv2.cvtColor(cv2.resize(bgr, (int(w * e), int(h * e))), cv2.COLOR_BGR2RGB)
        self._img = ImageTk.PhotoImage(Image.fromarray(rgb))
        self.configure(image=self._img, text="")


class PainelResultado(ttk.Frame):
    """Indicadores + lista dos últimos erros."""

    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.pasta = None
        kp = ttk.Frame(self)
        kp.pack(fill="x")
        self.v_itens, self.v_erros, self.v_taxa = tk.StringVar(value="0"), tk.StringVar(value="0"), tk.StringVar(value="—")
        for i, (var, rot, est) in enumerate(((self.v_itens, "Itens", "KpiV.TLabel"),
                                             (self.v_erros, "Erros", "KpiBad.TLabel"),
                                             (self.v_taxa, "Sem erro", "KpiOk.TLabel"))):
            f = ttk.Frame(kp, style="Card.TFrame", padding=(12, 8))
            f.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0))
            kp.columnconfigure(i, weight=1)
            ttk.Label(f, textvariable=var, style=est).pack(anchor="w")
            ttk.Label(f, text=rot.upper(), style="CardMuted.TLabel").pack(anchor="w")
        ttk.Label(self, text="ÚLTIMOS ERROS · duplo clique abre o vídeo", style="H2.TLabel").pack(anchor="w", pady=(14, 4))
        self.lista = ttk.Treeview(self, columns=("hora", "erro"), show="headings", height=9)
        self.lista.heading("hora", text="Quando")
        self.lista.heading("erro", text="Erro")
        self.lista.column("hora", width=96, stretch=False)
        self.lista.column("erro", width=230)
        self.lista.pack(fill="both", expand=True)
        self.lista.bind("<Double-1>", self._abrir_recorte)
        self.regs = {}
        b = ttk.Frame(self)
        b.pack(fill="x", pady=(8, 0))
        self.bt_rel = ttk.Button(b, text="Abrir relatório", style="Primary.TButton", command=self.abrir_relatorio,
                                 state="disabled")
        self.bt_rel.pack(side="left")
        ttk.Button(b, text="Abrir pasta", command=lambda: self.pasta and abrir(self.pasta)).pack(side="left", padx=8)

    def limpar(self):
        self.lista.delete(*self.lista.get_children())
        self.regs.clear()
        self.v_itens.set("0"); self.v_erros.set("0"); self.v_taxa.set("—")
        self.bt_rel.configure(state="disabled")

    def contagem(self, ciclos, erros, ok):
        self.v_itens.set(str(ciclos))
        self.v_erros.set(str(erros))
        self.v_taxa.set(f"{ok / ciclos * 100:.1f}%".replace(".", ",") if ciclos else "—")

    def erro(self, reg, pasta=None):
        quando = reg["quando"][-8:] if reg["quando"] else reg.get("t_video", "")
        iid = self.lista.insert("", 0, values=(quando, motor.TIPOS_CURTO[reg["tipo"]]))
        self.regs[iid] = (reg, Path(pasta) if pasta else None)

    def _abrir_recorte(self, _e):
        sel = self.lista.selection()
        if not sel or sel[0] not in self.regs:
            return
        reg, pasta = self.regs[sel[0]]
        pasta = pasta or self.pasta
        if not pasta:
            return
        arq = reg.get("marcado") or reg.get("original")
        if arq and (pasta / arq).exists():
            abrir(pasta / arq)
        else:
            abrir(pasta / "fotos" / f"{reg['base']}.jpg")

    def abrir_relatorio(self):
        if self.pasta and (self.pasta / "relatorio.html").exists():
            abrir(self.pasta / "relatorio.html")


# ---------------------------------------------------------------- páginas
class PaginaAoVivo(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=18)
        self.app = app
        self.trab = None
        ttk.Label(self, text="Câmera ao vivo", style="H1.TLabel").pack(anchor="w")
        ttk.Label(self, text="Grava só os trechos com erro enquanto a operação acontece. O turno inteiro não é guardado.",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 10))
        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Label(top, text="Câmera:").grid(row=0, column=0, sticky="w")
        self.fonte = tk.StringVar(value=app.cfg.get("fonte_ao_vivo", "0"))
        cb = ttk.Combobox(top, textvariable=self.fonte, width=46,
                          values=["0", "1", "2", "rtsp://usuario:senha@192.168.0.100:554/Streaming/Channels/101"])
        cb.grid(row=0, column=1, sticky="w", padx=6)
        ttk.Button(top, text="Usar um vídeo como câmera…", command=self._escolher_demo).grid(row=0, column=2, padx=4)
        ttk.Label(top, text="0, 1, 2 = câmera USB ou GoPro no modo webcam · rtsp:// = câmera IP",
                  style="Muted.TLabel").grid(row=1, column=1, columnspan=2, sticky="w", padx=6)
        ttk.Label(top, text="Microfone:").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.mics = [("", "Padrão do Windows")] + [(str(i), n) for i, n in motor.MicrofoneAoVivo.dispositivos()]
        self.mic = tk.StringVar(value=self._nome_mic(app.cfg.get("microfone", "")))
        ttk.Combobox(top, textvariable=self.mic, width=46, state="readonly",
                     values=[n for _, n in self.mics] + ["Sem microfone (só imagem)"]).grid(row=2, column=1, sticky="w", padx=6, pady=(8, 0))
        ttk.Button(top, text="Testar bipe (10 s)", command=self._testar_bipe).grid(row=2, column=2, padx=4, pady=(8, 0), sticky="w")

        bt = ttk.Frame(self)
        bt.pack(fill="x", pady=12)
        self.bt_ini = ttk.Button(bt, text="▶  Iniciar", style="Go.TButton", command=self.iniciar)
        self.bt_ini.pack(side="left")
        self.bt_par = ttk.Button(bt, text="■  Parar", style="Stop.TButton", command=self.parar, state="disabled")
        self.bt_par.pack(side="left", padx=8)
        self.bt_demo = ttk.Button(bt, text="▶  Ver demonstração", style="Primary.TButton", command=self.demonstracao)
        self.bt_demo.pack(side="left", padx=(8, 0))
        self.status = tk.StringVar(value="Parado.")
        ttk.Label(bt, textvariable=self.status, style="Muted.TLabel").pack(side="left", padx=12)
        self.m365 = tk.StringVar(value="")
        self.lb_m365 = ttk.Label(self, textvariable=self.m365, style="Muted.TLabel", cursor="hand2")
        self.lb_m365.pack(anchor="w", pady=(0, 8))
        self.lb_m365.bind("<Button-1>", lambda e: app.ir("m365"))

        corpo = ttk.Frame(self)
        corpo.pack(fill="both", expand=True)
        self.prev = Preview(corpo, 680, 383)
        self.prev.pack(side="left", anchor="n")
        self.res = PainelResultado(corpo, app)
        self.res.pack(side="left", fill="both", expand=True, padx=(16, 0))

    def _nome_mic(self, idx):
        if idx == "nenhum":
            return "Sem microfone (só imagem)"
        for i, n in getattr(self, "mics", []):
            if i == str(idx):
                return n
        return "Padrão do Windows"

    def _mic_idx(self):
        n = self.mic.get()
        if n.startswith("Sem microfone"):
            return "nenhum"
        for i, nome in self.mics:
            if nome == n:
                return i
        return ""

    def _escolher_demo(self):
        f = filedialog.askopenfilename(title="Vídeo para demonstração",
                                       filetypes=[("Vídeos", "*.mp4 *.mov *.MP4 *.MOV *.avi *.mkv"), ("Todos", "*.*")])
        if f:
            self.fonte.set(f)

    def _testar_bipe(self):
        idx = self._mic_idx()
        if idx == "nenhum":
            return
        self.status.set("Gravando 10 s: bipe 3 ou 4 vezes no leitor...")

        def t():
            try:
                freq, n = motor.MicrofoneAoVivo.calibrar(10, idx or None)
                msg = (f"Bipe encontrado em ~{freq:.0f} Hz ({n} bipes ouvidos). Valor salvo nas configurações."
                       if n else "Não ouvi bipes. Aproxime o microfone do leitor e tente de novo.")
                if n:
                    self.app.cfg["bipe_freq_hz"] = round(freq)
                    motor.salvar_config(self.app.cfg)
            except Exception as e:
                msg = f"Não consegui usar o microfone: {e}"
            self.app.q.put(("status_vivo", msg))
        threading.Thread(target=t, daemon=True).start()

    def demonstracao(self):
        """Roda o sistema no vídeo de demonstração (posto de cigarros), com as áreas da demo.
        Não altera as áreas nem a câmera configuradas."""
        if self.app.ocupado:
            messagebox.showinfo("ConfereVídeo", "Já existe uma análise em andamento. Pare-a antes.")
            return
        video = PASTA / "demo" / "demo_esteira_cigarros.mp4"
        areas = motor.ler_yaml(PASTA / "demo" / "areas_demo.yaml")
        if not video.exists() or not areas:
            messagebox.showwarning("ConfereVídeo", "O vídeo de demonstração não está na pasta 'demo'.")
            return
        cfg = dict(self.app.cfg)
        cfg["posto"] = "Posto 03 (demonstração)"
        cfg["usar_som_do_bipe"] = True
        self._rodar(str(video), cfg, areas, "demo")

    def iniciar(self):
        if not self.app.checar_areas():
            return
        cfg = dict(self.app.cfg)
        mic = self._mic_idx()
        cfg["microfone"] = "" if mic == "nenhum" else mic
        if mic == "nenhum" and not Path(self.fonte.get()).exists():
            cfg["usar_som_do_bipe"] = False
        self.app.cfg["fonte_ao_vivo"] = self.fonte.get()
        self.app.cfg["microfone"] = mic
        motor.salvar_config(self.app.cfg)
        self._rodar(self.fonte.get(), cfg, self.app.areas(), "ao_vivo")

    def _rodar(self, fonte, cfg, areas, modo):
        self.res.limpar()
        self.bt_demo.configure(state="disabled")
        self.bt_ini.configure(state="disabled")
        self.bt_par.configure(state="normal")
        self.status.set("Carregando a IA...")
        self.app.ocupado = "vivo"

        def t():
            modelo = self.app.modelo()
            self.trab = motor.AoVivo(fonte, cfg, areas, modelo,
                                     ev=lambda tp, d=None: self.app.q.put(("vivo_" + tp, d)),
                                     preview=lambda img: self.app.novo_preview("vivo", img), modo=modo,
                                     integracao=self.app.integ)
            self.trab.start()
            self.app.q.put(("vivo_iniciado", self.trab))
        threading.Thread(target=t, daemon=True).start()

    def parar(self):
        if self.trab:
            self.status.set("Finalizando os últimos recortes...")
            self.trab.parar()
        self.bt_par.configure(state="disabled")


class PaginaVideos(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=18)
        self.app = app
        self.parar_ev = None
        ttk.Label(self, text="Vídeos gravados", style="H1.TLabel").pack(anchor="w")
        ttk.Label(self, text="Coloque os vídeos da GoPro ou do celular. O programa assiste tudo e separa só os erros.",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 10))
        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Button(top, text="Adicionar vídeos…", command=self._add_arq).pack(side="left")
        ttk.Button(top, text="Adicionar pasta da GoPro…", command=self._add_pasta).pack(side="left", padx=6)
        ttk.Button(top, text="Limpar lista", command=self._limpar).pack(side="left")
        self.lb = tk.Listbox(self, height=4, font=(FONTE, 10), relief="flat", highlightthickness=1,
                             highlightbackground=C["line"])
        self.lb.pack(fill="x", pady=8)
        self.videos = []
        bt = ttk.Frame(self)
        bt.pack(fill="x", pady=(0, 10))
        self.bt_ini = ttk.Button(bt, text="▶  Analisar", style="Go.TButton", command=self.iniciar)
        self.bt_ini.pack(side="left")
        self.bt_par = ttk.Button(bt, text="■  Cancelar", style="Stop.TButton", command=self.parar, state="disabled")
        self.bt_par.pack(side="left", padx=8)
        self.prog = ttk.Progressbar(bt, length=260, mode="determinate", maximum=1000)
        self.prog.pack(side="left", padx=12)
        self.status = tk.StringVar(value="")
        ttk.Label(bt, textvariable=self.status, style="Muted.TLabel").pack(side="left")
        corpo = ttk.Frame(self)
        corpo.pack(fill="both", expand=True)
        self.prev = Preview(corpo, 680, 383)
        self.prev.pack(side="left", anchor="n")
        self.res = PainelResultado(corpo, app)
        self.res.pack(side="left", fill="both", expand=True, padx=(16, 0))

    def _add(self, lista):
        for v in motor.listar_videos(lista):
            if str(v) not in self.videos:
                self.videos.append(str(v))
                self.lb.insert("end", f"{Path(v).name}    ({Path(v).parent})")

    def _add_arq(self):
        fs = filedialog.askopenfilenames(title="Escolha os vídeos",
                                         filetypes=[("Vídeos", "*.mp4 *.mov *.MP4 *.MOV *.avi *.mkv *.m4v"), ("Todos", "*.*")])
        self._add(fs)

    def _add_pasta(self):
        d = filedialog.askdirectory(title="Pasta com os vídeos")
        if d:
            self._add([d])

    def _limpar(self):
        self.videos.clear()
        self.lb.delete(0, "end")

    def iniciar(self):
        if not self.videos:
            messagebox.showinfo("ConfereVídeo", "Adicione pelo menos um vídeo.")
            return
        if not self.app.checar_areas():
            return
        self.res.limpar()
        self.prog["value"] = 0
        self.bt_ini.configure(state="disabled")
        self.bt_par.configure(state="normal")
        self.status.set("Carregando a IA...")
        self.parar_ev = threading.Event()
        self.app.ocupado = "videos"
        cfg = dict(self.app.cfg)

        def t():
            modelo = self.app.modelo()
            s = motor.analisar_videos([Path(v) for v in self.videos], cfg, self.app.areas(), modelo,
                                      ev=lambda tp, d=None: self.app.q.put(("vid_" + tp, d)),
                                      parar=self.parar_ev, preview=lambda img: self.app.novo_preview("vid", img),
                                      integracao=self.app.integ)
            self.app.q.put(("vid_sessao", s))
        threading.Thread(target=t, daemon=True).start()

    def parar(self):
        if self.parar_ev:
            self.parar_ev.set()
            self.status.set("Cancelando...")


class PaginaAreas(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=18)
        self.app = app
        ttk.Label(self, text="Áreas do posto", style="H1.TLabel").pack(anchor="w")
        ttk.Label(self, text=("Marque uma vez para cada posição da câmera: 1 prateleira, 2 leitor, 3 caixa do posto "
                              "(obrigatórias), 4 outras caixas e 5 área do operador (opcionais)."),
                  style="Muted.TLabel", wraplength=900).pack(anchor="w", pady=(0, 10))
        b = ttk.Frame(self)
        b.pack(fill="x")
        ttk.Button(b, text="Marcar usando um vídeo…", style="Primary.TButton", command=self.por_video).pack(side="left")
        ttk.Button(b, text="Marcar usando a câmera ao vivo", command=self.por_camera).pack(side="left", padx=8)
        self.status = tk.StringVar()
        ttk.Label(b, textvariable=self.status, style="Muted.TLabel").pack(side="left", padx=10)
        self.prev = Preview(self, 900, 506)
        self.prev.configure(text="Nenhuma área marcada ainda")
        self.prev.pack(anchor="w", pady=12)
        self.atualizar()

    def atualizar(self):
        dados = self.app.areas()
        falta = motor.Areas.faltando(dados)
        self.status.set("Tudo pronto ✓" if not falta else "Falta marcar: " + ", ".join(falta))
        foto = PASTA / "areas_quadro.jpg"
        if dados and not foto.exists():
            self.prev.configure(text="Áreas marcadas. Marque de novo por aqui para ver a imagem de referência.")
        if foto.exists() and dados:
            img = cv2.imread(str(foto))
            if img is not None:
                a = motor.Areas(dados, img.shape[1], img.shape[0])
                cam = img.copy()
                for z, pols in a.zonas.items():
                    for q in pols:
                        cv2.fillPoly(cam, [q.astype(np.int32)], motor.CORES[z])
                img = cv2.addWeighted(cam, 0.3, img, 0.7, 0)
                for z, pols in a.zonas.items():
                    for q in pols:
                        cv2.polylines(img, [q.astype(np.int32)], True, motor.CORES[z], 3)
                self.prev.mostrar(img)

    def _marcar(self, fonte):
        self.status.set("Janela de marcação aberta: clique nos cantos, ENTER salva.")

        def t():
            subprocess.run([sys.executable, str(PASTA / "marcar_areas.py"), str(fonte), "--areas", str(PASTA / "areas.yaml")])
            self.app.q.put(("areas_ok", None))
        threading.Thread(target=t, daemon=True).start()

    def por_video(self):
        f = filedialog.askopenfilename(title="Vídeo do posto",
                                       filetypes=[("Vídeos", "*.mp4 *.mov *.MP4 *.MOV *.avi *.mkv"), ("Todos", "*.*")])
        if f:
            self._marcar(f)

    def por_camera(self):
        fonte = self.app.cfg.get("fonte_ao_vivo", "0")
        self.status.set("Pegando uma imagem da câmera...")

        def t():
            src = int(fonte) if str(fonte).isdigit() else fonte
            cap = cv2.VideoCapture(src)
            ok, q = False, None
            for _ in range(15):
                ok, q = cap.read()
            cap.release()
            if not ok:
                self.app.q.put(("areas_msg", f"Não consegui abrir a câmera '{fonte}'. Ajuste na tela Câmera ao vivo."))
                return
            tmp = PASTA / "areas_camera.jpg"
            cv2.imwrite(str(tmp), q)
            self.app.q.put(("areas_marcar", tmp))
        threading.Thread(target=t, daemon=True).start()


class PaginaRelatorios(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=18)
        self.app = app
        ttk.Label(self, text="Relatórios", style="H1.TLabel").pack(anchor="w")
        ttk.Label(self, text="Cada sessão (ao vivo ou análise de vídeos) gera um relatório com os recortes dos erros.",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 10))
        cols = ("data", "tipo", "turno", "periodo", "itens", "erros", "taxa")
        self.tv = ttk.Treeview(self, columns=cols, show="headings", height=16)
        for c, t, w in (("data", "Gerado em", 140), ("tipo", "Tipo", 130), ("turno", "Turno", 80),
                        ("periodo", "Período", 250), ("itens", "Itens", 70), ("erros", "Erros", 70),
                        ("taxa", "Sem erro", 80)):
            self.tv.heading(c, text=t)
            self.tv.column(c, width=w, anchor="w" if c in ("data", "tipo", "turno", "periodo") else "e")
        self.tv.pack(fill="both", expand=True)
        self.tv.bind("<Double-1>", lambda e: self.abrir_rel())
        b = ttk.Frame(self)
        b.pack(fill="x", pady=8)
        ttk.Button(b, text="Abrir relatório", style="Primary.TButton", command=self.abrir_rel).pack(side="left")
        ttk.Button(b, text="Abrir PDF", command=self.abrir_pdf).pack(side="left", padx=(8, 0))
        ttk.Button(b, text="Abrir pasta", command=self.abrir_pasta).pack(side="left", padx=8)
        ttk.Button(b, text="Atualizar lista", command=self.atualizar).pack(side="left")
        self.pastas = {}
        self.atualizar()

    def atualizar(self):
        self.tv.delete(*self.tv.get_children())
        self.pastas.clear()
        base = motor.caminho_resultados(self.app.cfg)
        if not base.exists():
            return
        for d in sorted(base.iterdir(), reverse=True):
            j = d / "resumo.json"
            if not j.exists():
                continue
            try:
                r = json.loads(j.read_text(encoding="utf-8"))
            except Exception:
                continue
            c, ok = r.get("ciclos", 0), r.get("ok", 0)
            iid = self.tv.insert("", "end", values=(
                r.get("gerado", ""), {"ao_vivo": "Câmera ao vivo", "demo": "Demonstração"}.get(r.get("modo"), "Vídeos gravados"),
                r.get("turno", "") or "—", " a ".join(p for p in r.get("periodo", []) if p), c, len(r.get("erros", [])),
                f"{ok / c * 100:.1f}%".replace(".", ",") if c else "—"))
            self.pastas[iid] = d

    def _sel(self):
        s = self.tv.selection()
        return self.pastas.get(s[0]) if s else None

    def abrir_rel(self):
        d = self._sel()
        if d:
            abrir(d / "relatorio.html")

    def abrir_pdf(self):
        d = self._sel()
        if not d:
            return
        if not (d / "relatorio.pdf").exists():
            try:
                from relatorio_pdf import gerar_pdf
                r = json.loads((d / "resumo.json").read_text(encoding="utf-8"))
                gerar_pdf(r, d, d / "relatorio.pdf", self.app.cfg.get("logo"))
            except Exception as e:
                messagebox.showwarning("ConfereVídeo", f"Não consegui gerar o PDF: {e}")
                return
        abrir(d / "relatorio.pdf")

    def abrir_pasta(self):
        d = self._sel()
        abrir(d or motor.caminho_resultados(self.app.cfg))


class PaginaM365(ttk.Frame):
    """Microsoft 365: Power Automate, SharePoint, Teams e e-mail."""

    def __init__(self, master, app):
        super().__init__(master, padding=18)
        self.app = app
        m = app.cfg["m365"]
        if not m.get("chave"):
            m["chave"] = integracao.nova_chave()
        ttk.Label(self, text="Microsoft 365", style="H1.TLabel").pack(anchor="w")
        ttk.Label(self, text=("Cada erro vira um item na lista do SharePoint (com foto e recorte), aparece no Teams "
                              "e o gestor recebe o resumo de cada turno por e-mail com o PDF. O passo a passo está no "
                              "guia do Microsoft 365."), style="Muted.TLabel", wraplength=980).pack(anchor="w", pady=(0, 8))
        self.estado = tk.StringVar()
        ttk.Label(self, textvariable=self.estado, font=(FONTE, 10, "bold")).pack(anchor="w", pady=(0, 6))
        f = ttk.Frame(self)
        f.pack(anchor="w", fill="x")
        f.columnconfigure(1, weight=1)
        self.v = {}

        def campo(r, rot, chave, dica="", w=70):
            ttk.Label(f, text=rot).grid(row=r, column=0, sticky="w", pady=3)
            v = tk.StringVar(value=str(m.get(chave, "")))
            ttk.Entry(f, textvariable=v, width=w).grid(row=r, column=1, sticky="we", padx=8)
            if dica:
                ttk.Label(f, text=dica, style="Muted.TLabel").grid(row=r, column=2, sticky="w")
            self.v[chave] = v

        self.ativo = tk.BooleanVar(value=bool(m.get("ativo")))
        ttk.Checkbutton(f, text="Enviar para o Microsoft 365", variable=self.ativo).grid(row=0, column=0, columnspan=2, sticky="w")
        campo(1, "Endereço do fluxo (URL)", "url_fluxo", "copiado do gatilho do fluxo")
        ttk.Label(f, text="Tipo de fluxo").grid(row=2, column=0, sticky="nw", pady=3)
        self.modo = tk.StringVar(value=m.get("modo", "completo"))
        g = ttk.Frame(f)
        g.grid(row=2, column=1, columnspan=2, sticky="w", padx=8)
        ttk.Radiobutton(g, text="Completo: lista do SharePoint + Teams + e-mail (fluxo do ConfereVídeo)",
                        value="completo", variable=self.modo).pack(anchor="w")
        ttk.Radiobutton(g, text="Só alerta no canal do Teams (modelo pronto do Teams, sem lista)",
                        value="alerta", variable=self.modo).pack(anchor="w")
        ttk.Label(f, text="Chave de segurança").grid(row=3, column=0, sticky="w", pady=3)
        h = ttk.Frame(f)
        h.grid(row=3, column=1, columnspan=2, sticky="w", padx=8)
        self.v["chave"] = tk.StringVar(value=m["chave"])
        ttk.Entry(h, textvariable=self.v["chave"], width=34, state="readonly").pack(side="left")
        ttk.Button(h, text="Copiar", command=lambda: self._copiar(self.v["chave"].get())).pack(side="left", padx=6)
        ttk.Button(h, text="Gerar nova", command=self._nova_chave).pack(side="left")
        campo(4, "Site do SharePoint", "site_sharepoint", "ex.: https://empresa.sharepoint.com/sites/SST")
        campo(5, "Lista de erros", "lista_erros", "", 30)
        campo(6, "Lista de turnos", "lista_sessoes", "", 30)
        campo(7, "E-mails dos supervisores", "emails_supervisores", "alertas no Teams e cobrança diária")
        campo(8, "E-mails do gestor", "emails_gestor", "resumo do turno e da semana")
        campo(9, "Link do canal do Teams", "canal_teams", "opcional: Canal > ... > Obter link")
        campo(10, "Link do app de tratativa", "link_app", "opcional: Power Apps > Detalhes > Link")
        ttk.Label(f, text="O que enviar", style="H2.TLabel").grid(row=11, column=0, sticky="w", pady=(12, 2))
        o = ttk.Frame(f)
        o.grid(row=12, column=0, columnspan=3, sticky="w")
        self.ops = {}
        for i, (k, txt) in enumerate((("enviar_recorte", "Recorte do erro (vídeo com marcações e som)"),
                                      ("enviar_original", "Recorte original, sem marcações"),
                                      ("avisar_videos_gravados", "Avisar no Teams os erros de vídeos gravados"),
                                      ("enviar_demonstracao", "Enviar também a demonstração (marcada DEMONSTRAÇÃO)"))):
            v = tk.BooleanVar(value=bool(m.get(k)))
            ttk.Checkbutton(o, text=txt, variable=v).grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 24))
            self.ops[k] = v
        b = ttk.Frame(self)
        b.pack(anchor="w", pady=(16, 6))
        ttk.Button(b, text="Salvar", style="Primary.TButton", command=self.salvar).pack(side="left")
        ttk.Button(b, text="Testar envio", command=self.testar).pack(side="left", padx=8)
        ttk.Button(b, text="Gerar fluxos do Power Automate…", command=self.gerar).pack(side="left")
        ttk.Button(b, text="Reenviar o que falhou", command=self.reenviar).pack(side="left", padx=8)
        ttk.Button(b, text="Abrir guia", command=self.guia).pack(side="left")
        self.msg = tk.StringVar()
        ttk.Label(self, textvariable=self.msg, style="Muted.TLabel", wraplength=980).pack(anchor="w")
        self.atualizar_estado()

    def _copiar(self, txt):
        self.clipboard_clear()
        self.clipboard_append(txt)
        self.msg.set("Copiado.")

    def _nova_chave(self):
        if messagebox.askyesno("ConfereVídeo", "Gerar uma chave nova? Depois, cole a chave nova na condição "
                                               "'Conferir_chave' do fluxo 2 (Receber eventos), como mostra o guia."):
            self.v["chave"].set(integracao.nova_chave())

    def _ler(self):
        m = self.app.cfg["m365"]
        for k, v in self.v.items():
            m[k] = v.get().strip()
        m["ativo"] = self.ativo.get()
        m["modo"] = self.modo.get()
        for k, v in self.ops.items():
            m[k] = v.get()
        return m

    def salvar(self, aviso=True):
        m = self._ler()
        motor.salvar_config(self.app.cfg)
        self.app.integ.iniciar()
        self.atualizar_estado()
        if aviso:
            self.msg.set("Configurações do Microsoft 365 salvas." +
                         ("" if integracao.url_valida(m["url_fluxo"]) or not m["ativo"]
                          else " Falta o endereço (URL) do fluxo."))

    def testar(self):
        self.salvar(aviso=False)
        self.msg.set("Enviando teste...")

        def t():
            ok, txt = self.app.integ.testar(self.app.cfg)
            self.app.q.put(("m365_msg", ("✓ " if ok else "✗ ") + txt))
        threading.Thread(target=t, daemon=True).start()

    def gerar(self):
        self.salvar(aviso=False)
        m = self.app.cfg["m365"]
        falta = power_platform.faltando(m)
        if falta:
            messagebox.showwarning("ConfereVídeo", "Para gerar os fluxos, preencha: " + ", ".join(falta) + ".")
            return
        d = filedialog.askdirectory(title="Onde salvar os fluxos do Power Automate")
        if not d:
            return
        pasta = Path(d) / "ConfereVideo_fluxos"
        try:
            arqs = power_platform.gerar_pacotes(m, pasta)
        except Exception as e:
            messagebox.showerror("ConfereVídeo", f"Não consegui gerar os fluxos: {e}")
            return
        self.msg.set(f"{len(arqs)} fluxos gerados em {pasta}. No Power Automate: Meus fluxos > Importar > "
                     "Importar pacote (Herdado), um de cada vez, começando pelo 1.")
        abrir(pasta)

    def reenviar(self):
        n = self.app.integ.reenviar_falhas()
        self.msg.set(f"{n} envio(s) voltaram para a fila." if n else "Nada para reenviar.")

    def guia(self):
        g = PASTA / "Microsoft365" / "GUIA_MICROSOFT_365.html"
        if g.exists():
            abrir(g)
        else:
            messagebox.showinfo("ConfereVídeo", "O guia fica na pasta Microsoft365 do programa.")

    def atualizar_estado(self):
        i = self.app.integ
        txt = i.resumo_estado()
        if i.falhas():
            txt += f" · {i.falhas()} envio(s) recusados (use 'Reenviar o que falhou' depois de corrigir)"
        self.estado.set(("● " if i.ativo() else "○ ") + txt)


class PaginaAutomacao(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=18)
        self.app = app
        a = app.cfg["automacao"]
        ttk.Label(self, text="Automação", style="H1.TLabel").pack(anchor="w")
        ttk.Label(self, text="Deixe o posto funcionando sozinho: liga com o PC, fecha um relatório por turno, "
                             "avisa se a câmera parar e apaga recortes antigos.", style="Muted.TLabel").pack(anchor="w", pady=(0, 12))
        f = ttk.Frame(self)
        f.pack(anchor="w")
        self.b = {}

        def caixa(r, chave, txt, dica=""):
            v = tk.BooleanVar(value=bool(a.get(chave)))
            ttk.Checkbutton(f, text=txt, variable=v).grid(row=r, column=0, columnspan=2, sticky="w", pady=3)
            if dica:
                ttk.Label(f, text=dica, style="Muted.TLabel").grid(row=r, column=2, sticky="w", padx=8)
            self.b[chave] = v

        caixa(0, "iniciar_com_windows", "Abrir o ConfereVídeo quando o PC ligar", "já entra com a câmera ao vivo ligada")
        caixa(1, "monitorar_ao_abrir", "Ligar a câmera ao vivo sozinho ao abrir o programa")
        caixa(2, "manter_pc_acordado", "Não deixar o PC suspender enquanto a câmera estiver ligada")
        caixa(3, "pdf_turno", "Gerar o relatório em PDF no fim de cada turno")
        ttk.Label(f, text="Horários de troca de turno").grid(row=4, column=0, sticky="w", pady=(12, 3))
        self.turnos = tk.StringVar(value=a.get("turnos", ""))
        ttk.Entry(f, textvariable=self.turnos, width=28).grid(row=4, column=1, sticky="w", padx=8, pady=(12, 3))
        ttk.Label(f, text="ex.: 06:00, 14:20, 22:35 · vazio = um relatório só, ao parar", style="Muted.TLabel").grid(
            row=4, column=2, sticky="w", pady=(12, 3))
        ttk.Label(f, text="Avisar câmera sem imagem depois de").grid(row=5, column=0, sticky="w", pady=3)
        self.min_cam = tk.IntVar(value=int(a.get("avisar_camera_parada_min", 2) or 2))
        g = ttk.Frame(f)
        g.grid(row=5, column=1, sticky="w", padx=8)
        ttk.Spinbox(g, from_=1, to=60, width=5, textvariable=self.min_cam).pack(side="left")
        ttk.Label(g, text="min").pack(side="left", padx=4)
        ttk.Label(f, text="no Teams e por e-mail para os supervisores", style="Muted.TLabel").grid(row=5, column=2, sticky="w")
        ttk.Label(f, text="Guardar recortes e relatórios por").grid(row=6, column=0, sticky="w", pady=3)
        self.dias = tk.IntVar(value=int(a.get("guardar_dias", 90) or 0))
        h = ttk.Frame(f)
        h.grid(row=6, column=1, sticky="w", padx=8)
        ttk.Spinbox(h, from_=0, to=3650, width=6, textvariable=self.dias).pack(side="left")
        ttk.Label(h, text="dias").pack(side="left", padx=4)
        ttk.Label(f, text="0 = nunca apagar · LGPD: guarde só o necessário", style="Muted.TLabel").grid(row=6, column=2, sticky="w")
        ttk.Button(self, text="Salvar", style="Primary.TButton", command=self.salvar).pack(anchor="w", pady=16)
        self.agora = tk.StringVar()
        ttk.Label(self, textvariable=self.agora, font=(FONTE, 10, "bold")).pack(anchor="w")
        self.msg = tk.StringVar()
        ttk.Label(self, textvariable=self.msg, style="Muted.TLabel", wraplength=900).pack(anchor="w", pady=(4, 0))
        self._mostrar_turno()

    def _mostrar_turno(self):
        nome, ini, fim = motor.turno_de(self.app.cfg)
        self.agora.set(f"Agora: {nome} ({ini:%H:%M} às {fim:%H:%M})" if nome else "Turnos: não configurados.")

    def salvar(self):
        a = self.app.cfg["automacao"]
        antes = bool(a.get("iniciar_com_windows"))
        for k, v in self.b.items():
            a[k] = v.get()
        txt = self.turnos.get().strip()
        if txt and not motor.ler_turnos({"automacao": {"turnos": txt}}):
            messagebox.showwarning("ConfereVídeo", "Escreva os horários assim: 06:00, 14:20, 22:35")
            return
        a["turnos"] = ", ".join(f"{h:02d}:{m:02d}" for h, m in motor.ler_turnos({"automacao": {"turnos": txt}}))
        self.turnos.set(a["turnos"])
        a["avisar_camera_parada_min"] = max(1, int(self.min_cam.get()))
        a["guardar_dias"] = max(0, int(self.dias.get()))
        msgs = []
        if a["iniciar_com_windows"] != antes or a["iniciar_com_windows"]:
            ok, m = iniciar_com_windows(a["iniciar_com_windows"])
            msgs.append(m)
            if not ok:
                a["iniciar_com_windows"] = False
                self.b["iniciar_com_windows"].set(False)
        motor.salvar_config(self.app.cfg)
        self._mostrar_turno()
        if self.app.ocupado == "vivo":
            msgs.append("Os turnos novos valem a partir da próxima vez que a câmera for ligada.")
        self.msg.set("Salvo. " + " ".join(msgs))


class JanelaDiagnostico(tk.Toplevel):
    """Roda a verificação do PC (diagnostico.py) e mostra o resultado."""

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("ConfereVídeo · verificação do PC")
        self.geometry("900x640")
        self.configure(bg=C["bg"])
        self.transient(app)
        topo = ttk.Frame(self, padding=(16, 14, 16, 6))
        topo.pack(fill="x")
        self.res = tk.StringVar(value="Verificando este PC (cerca de 1 minuto)...")
        ttk.Label(topo, textvariable=self.res, font=(FONTE, 12, "bold")).pack(anchor="w")
        self.etapa = tk.StringVar(value="")
        ttk.Label(topo, textvariable=self.etapa, style="Muted.TLabel").pack(anchor="w")
        self.txt = tk.Text(self, font=("Consolas" if os.name == "nt" else "DejaVu Sans Mono", 10), wrap="word",
                           relief="flat", padx=12, pady=10, bg=C["card"], fg=C["ink"])
        self.txt.pack(fill="both", expand=True, padx=16)
        b = ttk.Frame(self, padding=16)
        b.pack(fill="x")
        self.bt_copiar = ttk.Button(b, text="Copiar resultado", command=self._copiar, state="disabled")
        self.bt_copiar.pack(side="left")
        self.bt_pasta = ttk.Button(b, text="Abrir o arquivo", command=lambda: abrir(PASTA / "diagnostico.txt"),
                                   state="disabled")
        self.bt_pasta.pack(side="left", padx=8)
        ttk.Button(b, text="Fechar", command=self.destroy).pack(side="right")
        self.q = queue.Queue()
        vivo = app.ocupado == "vivo"  # câmera em uso: não disputa a câmera nem a IA
        threading.Thread(target=self._rodar, args=(not vivo,), daemon=True).start()
        if vivo:
            self.etapa.set("A câmera ao vivo está ligada: o teste da câmera e da IA fica de fora desta vez.")
        self.after(150, self._loop)

    def _rodar(self, completo):
        import diagnostico
        d = diagnostico.Diagnostico(progresso=lambda t: self.q.put(("etapa", t)))
        try:
            d.rodar(testar_ia=completo, testar_camera=completo)
            d.salvar()
        except Exception as e:
            d.add("Geral", diagnostico.AVISO, f"A verificação parou: {e}")
        self.q.put(("fim", d))

    def _loop(self):
        try:
            while True:
                tipo, d = self.q.get_nowait()
                if tipo == "etapa":
                    self.etapa.set(d)
                else:
                    self.res.set(d.resumo())
                    self.etapa.set(f"Salvo em {PASTA / 'diagnostico.txt'}")
                    self.txt.delete("1.0", "end")
                    self.txt.insert("1.0", d.texto())
                    self.bt_copiar.configure(state="normal")
                    self.bt_pasta.configure(state="normal")
                    return
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(150, self._loop)

    def _copiar(self):
        self.clipboard_clear()
        self.clipboard_append(self.txt.get("1.0", "end"))
        self.etapa.set("Copiado. Cole no e-mail ou no chat para mandar.")


class PaginaConfig(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=18)
        self.app = app
        cfg = app.cfg
        ttk.Label(self, text="Configurações", style="H1.TLabel").pack(anchor="w", pady=(0, 10))
        f = ttk.Frame(self)
        f.pack(anchor="w")
        self.vars = {}

        def campo(r, rot, chave, w=40):
            ttk.Label(f, text=rot).grid(row=r, column=0, sticky="w", pady=4)
            v = tk.StringVar(value=str(cfg.get(chave, "")))
            ttk.Entry(f, textvariable=v, width=w).grid(row=r, column=1, sticky="w", padx=8)
            self.vars[chave] = v

        campo(0, "Empresa", "empresa")
        campo(1, "Unidade", "unidade")
        campo(2, "Local / operação", "nome_local")
        campo(3, "Posto", "posto", 20)
        campo(4, "Logo (imagem PNG/JPG)", "logo")
        ttk.Button(f, text="Escolher…", command=self._logo).grid(row=4, column=2, sticky="w")
        campo(5, "Pasta dos resultados", "pasta_resultados")
        ttk.Button(f, text="Escolher…", command=self._pasta).grid(row=5, column=2, sticky="w")

        ttk.Label(f, text="Verificar", style="H2.TLabel").grid(row=6, column=0, sticky="w", pady=(16, 4))
        self.chk = {}
        for i, (k, n) in enumerate(motor.TIPOS.items()):
            v = tk.BooleanVar(value=bool(cfg["verificar"].get(k, True)))
            ttk.Checkbutton(f, text=n, variable=v).grid(row=7 + i, column=0, columnspan=2, sticky="w")
            self.chk[k] = v
        self.som = tk.BooleanVar(value=bool(cfg.get("usar_som_do_bipe", True)))
        ttk.Checkbutton(f, text="Usar o som do bipe (necessário para os dois últimos)", variable=self.som).grid(
            row=11, column=0, columnspan=2, sticky="w", pady=(4, 0))

        ttk.Label(f, text="Ajustes", style="H2.TLabel").grid(row=12, column=0, sticky="w", pady=(16, 4))
        ttk.Label(f, text="Sensibilidade do bipe").grid(row=13, column=0, sticky="w")
        self.lim = tk.IntVar(value=int(cfg.get("bipe_limiar_db", 15)))
        ttk.Scale(f, from_=25, to=8, variable=self.lim, length=220).grid(row=13, column=1, sticky="w", padx=8)
        ttk.Label(f, text="← menos  |  mais →", style="Muted.TLabel").grid(row=13, column=2, sticky="w")
        ttk.Label(f, text="Segundos antes / depois no recorte").grid(row=14, column=0, sticky="w", pady=4)
        g = ttk.Frame(f)
        g.grid(row=14, column=1, sticky="w", padx=8)
        self.antes = tk.IntVar(value=int(cfg.get("segundos_antes", 3)))
        self.depois = tk.IntVar(value=int(cfg.get("segundos_depois", 3)))
        ttk.Spinbox(g, from_=1, to=15, width=5, textvariable=self.antes).pack(side="left")
        ttk.Spinbox(g, from_=1, to=15, width=5, textvariable=self.depois).pack(side="left", padx=6)
        ttk.Label(f, text="Precisão da IA").grid(row=15, column=0, sticky="w", pady=4)
        self.prec = tk.StringVar(value="preciso" if "11s" in cfg.get("modelo_pose", "") else "rapido")
        h = ttk.Frame(f)
        h.grid(row=15, column=1, sticky="w", padx=8)
        ttk.Radiobutton(h, text="Rápida (PC comum)", value="rapido", variable=self.prec).pack(side="left")
        ttk.Radiobutton(h, text="Precisa (PC com placa de vídeo)", value="preciso", variable=self.prec).pack(side="left", padx=8)
        b = ttk.Frame(self)
        b.pack(anchor="w", pady=18)
        ttk.Button(b, text="Salvar configurações", style="Primary.TButton", command=self.salvar).pack(side="left")
        ttk.Button(b, text="Verificar este PC", command=lambda: JanelaDiagnostico(self.app)).pack(side="left", padx=8)

    def _logo(self):
        f = filedialog.askopenfilename(filetypes=[("Imagens", "*.png *.jpg *.jpeg")])
        if f:
            self.vars["logo"].set(f)

    def _pasta(self):
        d = filedialog.askdirectory()
        if d:
            self.vars["pasta_resultados"].set(d)

    def salvar(self):
        cfg = self.app.cfg
        for k, v in self.vars.items():
            cfg[k] = v.get().strip()
        cfg["verificar"] = {k: v.get() for k, v in self.chk.items()}
        cfg["usar_som_do_bipe"] = self.som.get()
        cfg["bipe_limiar_db"] = int(self.lim.get())
        cfg["segundos_antes"], cfg["segundos_depois"] = int(self.antes.get()), int(self.depois.get())
        rapido = self.prec.get() == "rapido"
        novo_modelo = "yolo11n-pose.pt" if rapido else "yolo11s-pose.pt"
        if novo_modelo != cfg["modelo_pose"]:
            self.app._modelo = None
        cfg["modelo_pose"], cfg["tamanho_imagem"] = novo_modelo, (640 if rapido else 960)
        motor.salvar_config(cfg)
        self.app.cabecalho()
        messagebox.showinfo("ConfereVídeo", "Configurações salvas.")


# ---------------------------------------------------------------- aplicativo
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.cfg = motor.carregar_config()
        self.q = queue.Queue()
        self.integ = integracao.Integracao(lambda: self.cfg, log=lambda msg: self.q.put(("m365_log", msg)))
        self.integ.iniciar()
        threading.Thread(target=motor.limpar_antigos, args=(self.cfg,), daemon=True).start()
        self._modelo, self._lock_modelo = None, threading.Lock()
        self._prev, self._prev_lock = {}, threading.Lock()
        self.ocupado = None
        self.title("ConfereVídeo · Conferência da separação por vídeo")
        self.geometry("1320x840")
        self.minsize(1120, 720)
        self.configure(bg=C["bg"])
        try:
            if os.name == "nt" and (PASTA / "icone.ico").exists():
                self.iconbitmap(str(PASTA / "icone.ico"))
            else:
                self._ico = tk.PhotoImage(file=str(PASTA / "icone.png"))
                self.iconphoto(True, self._ico)
        except Exception:
            pass
        estilos(self)
        self._montar()
        self.after(60, self._loop)
        self.after(500, self._estado_m365)
        self.protocol("WM_DELETE_WINDOW", self._sair)
        threading.Thread(target=self.modelo, daemon=True).start()  # já deixa a IA carregada
        if AUTO or self.cfg["automacao"].get("monitorar_ao_abrir"):
            self.after(1500, self._auto_iniciar)

    def _auto_iniciar(self):
        """Aberto pela inicialização do Windows (ou opção 'ligar ao abrir'): liga a câmera ao vivo."""
        if motor.Areas.faltando(self.areas()) or self.ocupado:
            return
        self.ir("vivo")
        self.paginas["vivo"].iniciar()

    def _estado_m365(self):
        try:
            txt = self.integ.resumo_estado()
            self.paginas["vivo"].m365.set(("● " if self.integ.ativo() else "○ ") + txt)
            if self.paginas["m365"].winfo_ismapped():
                self.paginas["m365"].atualizar_estado()
        except Exception:
            pass
        self.after(2000, self._estado_m365)

    def _montar(self):
        topo = tk.Frame(self, bg=C["ink"], height=64)
        topo.pack(fill="x")
        cv = tk.Canvas(topo, width=40, height=40, bg=C["ink"], highlightthickness=0)
        cv.pack(side="left", padx=(18, 10), pady=12)
        cv.create_rectangle(2, 2, 38, 38, fill=C["brand"], outline="")
        cv.create_oval(9, 13, 31, 27, outline="white", width=2)
        cv.create_oval(16, 16, 24, 24, fill=C["amar"], outline="")
        t = tk.Frame(topo, bg=C["ink"])
        t.pack(side="left")
        tk.Label(t, text="ConfereVídeo", bg=C["ink"], fg="white", font=(FONTE, 15, "bold")).pack(anchor="w")
        tk.Label(t, text="Conferência da separação por vídeo", bg=C["ink"], fg="#9fb3cc", font=(FONTE, 9)).pack(anchor="w")
        self.lb_local = tk.Label(topo, bg=C["ink"], fg="#d6e0ec", font=(FONTE, 10))
        self.lb_local.pack(side="right", padx=18)
        self.cabecalho()

        corpo = tk.Frame(self, bg=C["bg"])
        corpo.pack(fill="both", expand=True)
        lado = tk.Frame(corpo, bg=C["side"], width=210)
        lado.pack(side="left", fill="y")
        lado.pack_propagate(False)
        self.conteudo = ttk.Frame(corpo)
        self.conteudo.pack(side="left", fill="both", expand=True)
        self.paginas = {
            "vivo": PaginaAoVivo(self.conteudo, self),
            "videos": PaginaVideos(self.conteudo, self),
            "areas": PaginaAreas(self.conteudo, self),
            "rel": PaginaRelatorios(self.conteudo, self),
            "m365": PaginaM365(self.conteudo, self),
            "auto": PaginaAutomacao(self.conteudo, self),
            "cfg": PaginaConfig(self.conteudo, self),
        }
        self.botoes = {}
        tk.Label(lado, text="", bg=C["side"]).pack(pady=4)
        for k, nome in (("vivo", "Câmera ao vivo"), ("videos", "Vídeos gravados"), ("areas", "Áreas do posto"),
                        ("rel", "Relatórios"), ("m365", "Microsoft 365"), ("auto", "Automação"),
                        ("cfg", "Configurações")):
            b = tk.Label(lado, text="   " + nome, bg=C["side"], fg="#cfd8e3", font=(FONTE, 11), anchor="w",
                         padx=10, pady=12, cursor="hand2")
            b.pack(fill="x")
            b.bind("<Button-1>", lambda e, k=k: self.ir(k))
            self.botoes[k] = b
        tk.Label(lado, text="Detecção automática:\nconfira sempre o recorte.", bg=C["side"], fg="#7d8ba0",
                 font=(FONTE, 8), justify="left").pack(side="bottom", anchor="w", padx=14, pady=14)
        self.ir("areas" if motor.Areas.faltando(self.areas()) else "vivo")

    def cabecalho(self):
        c = self.cfg
        self.lb_local.configure(text=f"{c['empresa']}  ·  {c['unidade']}  ·  {c['posto']}")

    def ir(self, k):
        for p in self.paginas.values():
            p.pack_forget()
        self.paginas[k].pack(fill="both", expand=True)
        for kk, b in self.botoes.items():
            b.configure(bg=C["side_on"] if kk == k else C["side"], fg="white" if kk == k else "#cfd8e3",
                        font=(FONTE, 11, "bold" if kk == k else "normal"))
        if k == "rel":
            self.paginas["rel"].atualizar()

    def areas(self):
        return motor.ler_yaml(PASTA / "areas.yaml")

    def checar_areas(self):
        falta = motor.Areas.faltando(self.areas())
        if falta:
            messagebox.showwarning("ConfereVídeo", "Antes, marque as áreas do posto: " + ", ".join(falta) + ".")
            self.ir("areas")
            return False
        if self.ocupado:
            messagebox.showinfo("ConfereVídeo", "Já existe uma análise em andamento. Pare-a antes de iniciar outra.")
            return False
        return True

    def modelo(self):
        with self._lock_modelo:
            if self._modelo is None:
                self._modelo = motor.carregar_modelo(self.cfg)
            return self._modelo

    def novo_preview(self, onde, img):
        with self._prev_lock:
            self._prev[onde] = img

    def _loop(self):
        with self._prev_lock:
            prevs, self._prev = self._prev, {}
        if "vivo" in prevs:
            self.paginas["vivo"].prev.mostrar(prevs["vivo"])
        if "vid" in prevs:
            self.paginas["videos"].prev.mostrar(prevs["vid"])
        try:
            while True:
                tipo, d = self.q.get_nowait()
                self._evento(tipo, d)
        except queue.Empty:
            pass
        self.after(60, self._loop)

    def _evento(self, tipo, d):
        pv, pd, pa = self.paginas["vivo"], self.paginas["videos"], self.paginas["areas"]
        if tipo == "status_vivo":
            pv.status.set(d)
        elif tipo == "vivo_iniciado":
            pv.status.set("Ligado. Gravando só os erros.")
            pv.res.pasta = d.sessao.pasta if d.sessao else None
        elif tipo == "vivo_log":
            pv.status.set(d)
        elif tipo == "vivo_contagem":
            pv.res.contagem(*d)
            if pv.trab and pv.trab.sessao:
                pv.res.pasta = pv.trab.sessao.pasta
        elif tipo == "vivo_erro":
            pv.res.erro(d["reg"], d.get("pasta"))
            self.bell()
        elif tipo == "vivo_turno":
            pv.res.limpar()
            pv.res.pasta = Path(d["pasta"])
            pv.status.set(f"Novo turno: {d['turno']}. O relatório do {d['anterior']} foi fechado"
                          + (" e enviado." if self.integ.ativo() else "."))
        elif tipo == "vivo_sessao_fechada":
            if self.paginas["rel"].winfo_ismapped():
                self.paginas["rel"].atualizar()
        elif tipo == "vivo_alerta":
            pv.status.set(d)
            self.bell()
        elif tipo == "m365_log":
            self.paginas["m365"].msg.set(d)
        elif tipo == "m365_msg":
            self.paginas["m365"].msg.set(d)
            self.paginas["m365"].atualizar_estado()
        elif tipo == "vivo_recorte":
            pv.res.bt_rel.configure(state="normal")
        elif tipo == "vivo_fim":
            self.ocupado = None
            pv.bt_ini.configure(state="normal")
            pv.bt_par.configure(state="disabled")
            pv.bt_demo.configure(state="normal")
            pv.status.set("Parado. Relatório salvo.")
            pv.res.bt_rel.configure(state="normal")
        elif tipo == "vid_log":
            pd.status.set(d.strip())
        elif tipo == "vid_progresso":
            pd.prog["value"] = int(d * 1000)
        elif tipo == "vid_contagem":
            pd.res.contagem(*d)
        elif tipo == "vid_erro":
            pd.res.erro(d["reg"], pd.res.pasta)
        elif tipo == "vid_sessao":
            pd.res.pasta = d.pasta
        elif tipo == "vid_fim":
            self.ocupado = None
            pd.res.pasta = Path(d).parent
            pd.bt_ini.configure(state="normal")
            pd.bt_par.configure(state="disabled")
            pd.prog["value"] = 1000
            pd.status.set("Concluído.")
            pd.res.bt_rel.configure(state="normal")
            pd.res.abrir_relatorio()
        elif tipo == "areas_ok":
            pa.atualizar()
        elif tipo == "areas_msg":
            pa.status.set(d)
        elif tipo == "areas_marcar":
            pa._marcar(d)

    def _sair(self):
        if self.ocupado == "vivo" and self.paginas["vivo"].trab:
            if not messagebox.askyesno("ConfereVídeo", "A câmera ao vivo está ligada. Parar e sair?"):
                return
            self.paginas["vivo"].status.set("Fechando o relatório do turno...")
            self.update()
            self.paginas["vivo"].trab.parar()
            self.paginas["vivo"].trab.join(60)
        elif self.ocupado == "videos":
            if not messagebox.askyesno("ConfereVídeo", "Há uma análise em andamento. Cancelar e sair?"):
                return
            self.paginas["videos"].parar_ev.set()
            time.sleep(1)
        self.integ.parar()  # o que estiver na fila vai na próxima vez que abrir
        self.destroy()


def _registrar_erro(texto):
    try:
        with open(PASTA / "erro.log", "a", encoding="utf-8") as f:
            f.write(f"\n[{datetime.now():%d/%m/%Y %H:%M:%S}]\n{texto}\n")
    except Exception:
        pass


if __name__ == "__main__":
    import traceback
    try:
        app = App()
        app.report_callback_exception = lambda *a: _registrar_erro("".join(traceback.format_exception(*a)))
        app.mainloop()
    except Exception:
        _registrar_erro(traceback.format_exc())
        try:
            messagebox.showerror("ConfereVídeo", "O programa encontrou um erro e foi fechado.\n"
                                 "Detalhes no arquivo erro.log, na pasta do programa.")
        except Exception:
            pass
