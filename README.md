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

## Testes

Os testes conferem as regras de erro, a detecção do bipe, os turnos, a limpeza automática e a
câmera ao vivo (tocando o vídeo de demonstração com uma IA de mentira). Não precisam de câmera nem da IA.

```
pip install numpy opencv-python-headless pyyaml pillow fpdf2 pytest
python -m pytest -q tests
```

Eles também rodam sozinhos no GitHub (aba **Actions**) a cada envio.
