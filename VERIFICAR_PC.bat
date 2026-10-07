@echo off
chcp 65001 >nul
cd /d "%~dp0"
title ConfereVideo - verificando este PC
echo Verificando este PC (cerca de 1 minuto)...
python diagnostico.py
start "" notepad "%~dp0diagnostico.txt"
pause
