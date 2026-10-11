"""Operador identificado pelo QR do crachá (Emissor de Crachás do SST), sem biometria."""
import base64
import copy
import json

import cv2
import numpy as np
import pytest

import motor


def qr_do_cracha(nome, funcao="Separador", unidade="Guarulhos II"):
    """Mesmo formato do Emissor de Crachás: endereço da ficha + '#' + base64url do JSON."""
    dados = {"t": "n", "n": nome, "u": unidade, "f": funcao, "e": "20261011", "i": []}
    b64 = base64.urlsafe_b64encode(json.dumps(dados, ensure_ascii=False).encode()).decode().rstrip("=")
    return "https://luantavarez.github.io/sst-vencimentos/ficha.html#" + b64


def imagem_com_qr(texto, lado=260):
    qr = cv2.QRCodeEncoder.create().encode(texto)
    qr = cv2.resize(qr, (lado, lado), interpolation=cv2.INTER_NEAREST)
    img = np.full((720, 1280, 3), 200, np.uint8)
    img[200:200 + lado + 40, 500:500 + lado + 40] = 255          # crachá branco
    img[220:220 + lado, 520:520 + lado] = cv2.cvtColor(qr, cv2.COLOR_GRAY2BGR)
    return img


def test_le_o_qr_do_cracha_numa_imagem():
    op = motor.ler_cracha(imagem_com_qr(qr_do_cracha("Maria da Silva")))
    assert op == {"nome": "Maria da Silva", "funcao": "Separador", "unidade": "Guarulhos II"}


def test_sem_qr_nao_identifica():
    assert motor.ler_cracha(np.full((720, 1280, 3), 128, np.uint8)) is None
    assert motor.ler_cracha(None) is None


@pytest.mark.parametrize("texto, nome", [
    ("João Pereira", "João Pereira"),
    ("João Pereira\nMatrícula 123", "João Pereira"),
    ("https://exemplo.com/qualquer", None),          # link sem dados do crachá: não identifica
    ("https://x/ficha.html#nao-e-base64!!", None),
    ("", None),
])
def test_formatos_de_qr(texto, nome):
    op = motor.operador_do_qr(texto)
    assert (op or {}).get("nome") == nome


def test_operador_vai_em_cada_erro(tmp_path):
    cfg = copy.deepcopy(motor.PADRAO)
    cfg["pasta_resultados"] = str(tmp_path)
    s = motor.Sessao(cfg, "videos")
    erro = {"tipo": "sem_leitor", "confianca": 80}
    assert s.registrar(erro, None, "v.mp4")["operador"] == ""
    assert s.identificar({"nome": "Ana", "funcao": "", "unidade": ""})
    assert not s.identificar({"nome": "Ana", "funcao": "", "unidade": ""})  # mesmo crachá de novo: não muda
    reg = s.registrar(erro, None, "v.mp4")
    assert reg["operador"] == "Ana" and not reg["baixa_confianca"]
    assert [o["nome"] for o in s.resumo()["operadores"]] == ["Ana"]


def test_certeza_baixa_nao_vira_alerta(tmp_path):
    cfg = copy.deepcopy(motor.PADRAO)
    cfg["pasta_resultados"] = str(tmp_path)
    cfg["confianca_minima"] = 50
    s = motor.Sessao(cfg, "videos")
    assert s.registrar({"tipo": "sem_leitor", "confianca": 49}, None, "v")["baixa_confianca"]
    assert not s.registrar({"tipo": "sem_leitor", "confianca": 50}, None, "v")["baixa_confianca"]

    import integracao
    cfg["m365"].update(ativo=True, url_fluxo="https://exemplo.com/fluxo")
    integ = integracao.Integracao(lambda: cfg, pasta=tmp_path / "fila")
    s.modo = "ao_vivo"
    assert integ.erro(cfg, s, s.erros[0]) is None           # certeza baixa: não manda ao Teams/SharePoint
    assert integ.pendentes() == 0
    assert "certeza baixa" in (tmp_path / "fila" / "envios.log").read_text(encoding="utf-8")
