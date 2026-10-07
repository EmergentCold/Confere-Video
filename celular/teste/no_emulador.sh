#!/usr/bin/env bash
# Roda dentro do emulador Android (workflow "Aplicativo Android").
set -euo pipefail
adb install -r celular/ConfereVideo.apk
node celular/teste/testar_app.js
