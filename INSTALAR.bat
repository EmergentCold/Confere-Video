@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Instalando o ConfereVideo
echo ==================================================
echo   ConfereVideo - instalacao
echo ==================================================
python --version >nul 2>&1
if errorlevel 1 (
  echo.
  echo Python nao encontrado.
  echo 1. Baixe o Python 3.11 ou 3.12 em https://www.python.org/downloads/
  echo 2. Na instalacao, marque "Add python.exe to PATH"
  echo 3. Rode este INSTALAR.bat de novo
  pause
  exit /b 1
)
echo Instalando os componentes (pode levar alguns minutos na primeira vez)...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Algo deu errado na instalacao. Se a rede da empresa bloqueia downloads, fale com a TI.
  pause
  exit /b 1
)
echo.
echo Criando o atalho na area de trabalho...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0criar_atalho.ps1"
echo.
echo Verificando este PC (cerca de 1 minuto)...
python diagnostico.py
start "" notepad "%~dp0diagnostico.txt"
echo.
echo Pronto! Abra pelo atalho "ConfereVideo" na area de trabalho.
echo O resultado da verificacao abriu no Bloco de Notas (diagnostico.txt).
pause
