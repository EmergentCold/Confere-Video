# Monta o ConfereVideo.exe (PyInstaller) e o instalador ConfereVideo_Instalador.exe (Inno Setup).
# Precisa de Windows com Python 3.12. Na pasta do projeto:
#   powershell -ExecutionPolicy Bypass -File instalador\montar.ps1
# O instalador sai em dist\ConfereVideo_Instalador.exe.
param([string]$Versao = "1.0.0")
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
if ($LASTEXITCODE) { throw "Falhou ao instalar os componentes (pip)." }
# a IA usa operações do torchvision (NMS): confere antes de montar que elas funcionam com este torch
python -c "import torch, torchvision; torchvision.ops.nms(torch.zeros((1, 4)), torch.zeros(1), 0.5); print('torch', torch.__version__, '| torchvision', torchvision.__version__)"
if ($LASTEXITCODE) { throw "O torchvision instalado não funciona com este torch." }

# --contents-directory . : as bibliotecas ficam ao lado do .exe, então a "pasta do programa"
# (config.yaml, demo\, resultados\...) é a mesma pasta do ConfereVideo.exe
python -m PyInstaller app.py --name ConfereVideo --windowed --icon icone.ico --contents-directory . `
    --noconfirm --clean `
    --collect-all ultralytics --collect-all torchvision --collect-all imageio_ffmpeg --collect-data _sounddevice_data `
    --hidden-import lap --copy-metadata lap --copy-metadata torch
if ($LASTEXITCODE) { throw "Falhou ao montar o ConfereVideo.exe (PyInstaller)." }

$dist = "dist\ConfereVideo"
Copy-Item config.yaml, yolo11n-pose.pt, yolo11s-pose.pt, icone.png, icone.ico, GUIA.md -Destination $dist
Copy-Item demo, Microsoft365 -Destination $dist -Recurse -Force

$iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) {
    choco install innosetup -y --no-progress
    if ($LASTEXITCODE) { throw "Falhou ao instalar o Inno Setup." }
}
& $iscc "/DVersao=$Versao" instalador\ConfereVideo.iss
if ($LASTEXITCODE) { throw "Falhou ao montar o instalador (Inno Setup)." }
Get-Item dist\ConfereVideo_Instalador.exe | Format-Table Name, @{n = "MB"; e = { [int]($_.Length / 1MB) } }
