#!/usr/bin/env bash
# Roda dentro do emulador Android (workflow "Aplicativo Android").
set -uo pipefail
adb install -r celular/ConfereVideo.apk || exit 1
adb logcat -c
if node celular/teste/testar_app.js; then exit 0; fi
echo "=== O teste falhou. Log do Android (app, WebView e falhas) ==="
adb logcat -d | grep -iE "conferevideo|chromium|capacitor|console|crash|FATAL|AndroidRuntime|lowmemory|killed" | tail -150
exit 1
