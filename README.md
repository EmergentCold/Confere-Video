# ConfereVídeo

Conferência da separação por vídeo. O sistema acompanha a mão do operador entre
**prateleira → leitor → caixa**, ouve o **bipe** do leitor e grava **só os trechos com erro**
(sem passar no leitor, caixa errada, sem bipe, bipe duplo).

- Guia de uso: [`GUIA.md`](GUIA.md)
- Microsoft 365 (SharePoint, Teams, Outlook, Power Automate, Power Apps): [`Microsoft365/GUIA_MICROSOFT_365.html`](Microsoft365/GUIA_MICROSOFT_365.html)

## Estrutura

| Arquivo | Papel |
|---|---|
| `app.py` | Programa com janela (Tkinter) |
| `motor.py` | Análise: IA de pose (YOLO11), regras de erro, bipe, recortes, sessões e turnos |
| `marcar_areas.py` | Marca as áreas do posto no vídeo/câmera |
| `integracao.py` | Envio ao Power Automate com fila em disco |
| `power_platform.py` | Gera os fluxos do Power Automate |
| `relatorio.py` / `relatorio_pdf.py` | Relatório do turno em HTML e PDF |
| `diagnostico.py` | Verificação do PC |
| `config.yaml` | Configuração do posto |

## Instalar (Windows)

**Jeito fácil (sem Python):** baixe o `ConfereVideo_Instalador.exe` na página
[Releases](../../releases) do repositório e dê dois cliques. Ele instala na pasta do usuário
(não pede administrador) e cria o atalho na área de trabalho. Cada instalador é testado num
Windows limpo antes de ser publicado (instala e roda a demonstração). Para montar o instalador
no próprio PC: `powershell -ExecutionPolicy Bypass -File instalador\montar.ps1`.

**Com Python:**

1. Python 3.11 ou 3.12 com "Add python.exe to PATH".
2. Dois cliques em `INSTALAR.bat`.
3. Abrir pelo atalho **ConfereVideo** na área de trabalho.

Linha de comando:

```
python motor.py video.mp4          # analisa um vídeo gravado
python motor.py --ao-vivo 0        # câmera nº 0
python marcar_areas.py video.mp4   # marca as áreas
python diagnostico.py              # verifica o PC
```

## Versão web e aplicativo Android

- **Arquivo único** (`ConfereVideo.html`, em [Releases](../../releases)): o sistema inteiro em um
  arquivo de ~21 MB, para baixar, anexar e abrir com dois cliques no Chrome ou no Edge, sem
  instalar nada. Montado por `web/montar_arquivo_unico.py` (workflow **Arquivo único**).
- `web/index.html`: o ConfereVídeo no navegador (confere vídeos gravados, sem instalar nada). Usa a
  mesma IA (`web/yolo11n-pose.onnx`, o `yolo11n-pose.pt` exportado para ONNX) e as mesmas regras do
  `motor.py`, reescritas em JavaScript, e chega ao mesmo resultado na demonstração.
- `celular/`: aplicativo Android (Capacitor) com a versão web dentro, mais o botão de gravar pela
  câmera do celular. O workflow **Aplicativo Android** monta o `ConfereVideo.apk`, instala num
  emulador, confere a demonstração e publica em [Releases](../../releases).

Para montar o aplicativo no próprio PC (Node 22, JDK 21 e Android SDK):
`cd celular && npm ci && npm run sync && cd android && ./gradlew assembleDebug`.

## Testes

Os testes conferem as regras de erro, a detecção do bipe, os turnos, a limpeza automática e a
câmera ao vivo (tocando o vídeo de demonstração com uma IA de mentira). Não precisam de câmera nem da IA.

```
pip install numpy opencv-python-headless pyyaml pillow fpdf2 pytest
python -m pytest -q tests
```

Eles também rodam sozinhos no GitHub (aba **Actions**) a cada envio.
