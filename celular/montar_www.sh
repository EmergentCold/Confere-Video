#!/usr/bin/env bash
# Monta a pasta www/ do aplicativo a partir da versão web (web/index.html):
# a página, a IA, o motor da IA (onnxruntime-web) e o vídeo de demonstração.
set -euo pipefail
cd "$(dirname "$0")"
rm -rf www && mkdir -p www/ort
{
  printf '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
  printf '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
  printf '<style>:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}body{margin:0}img{max-width:100%%}[hidden]{display:none!important}</style>'
  printf '</head><body>'
  cat ../web/index.html
  printf '</body></html>'
} > www/index.html
ORT=node_modules/onnxruntime-web/dist
cp "$ORT/ort.wasm.min.js" www/
cp "$ORT/ort-wasm-simd-threaded.mjs" "$ORT/ort-wasm-simd-threaded.wasm" www/ort/
base64 -w0 ../web/yolo11n-pose.onnx > www/yolo11n-pose.onnx.txt
cp ../demo/demo_esteira_cigarros.mp4 www/demo.mp4
du -sh www
