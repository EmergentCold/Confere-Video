"""Detecção do bipe do leitor no áudio (DetectorBipe / bipes_do_arquivo)."""
import numpy as np
import pytest

from motor import SR_AUDIO, DetectorBipe, HOP, _espectro, bipes_do_arquivo, frequencia_do_bipe


def audio_com_bipes(tempos, dur=40.0, freq=3200.0, dur_bipe=0.12, ruido=0.02, semente=1):
    rng = np.random.default_rng(semente)
    a = (rng.standard_normal(int(dur * SR_AUDIO)) * ruido).astype(np.float32)
    n = int(dur_bipe * SR_AUDIO)
    tt = np.arange(n) / SR_AUDIO
    tom = (0.3 * np.sin(2 * np.pi * freq * tt)).astype(np.float32)
    for t in tempos:
        i = int(t * SR_AUDIO)
        a[i:i + n] += tom
    return a


TEMPOS = [2.0, 5.5, 9.0, 12.3, 16.0, 19.8, 23.1, 27.4, 31.0, 35.2]


def test_descobre_a_frequencia_do_bipe():
    a = audio_com_bipes(TEMPOS, freq=3200)
    assert frequencia_do_bipe(a) == pytest.approx(3200, abs=SR_AUDIO / 512)


def test_acha_todos_os_bipes_no_tempo_certo(cfg):
    a = audio_com_bipes(TEMPOS)
    bipes, freq = bipes_do_arquivo(a, cfg)
    assert len(bipes) == len(TEMPOS)
    assert np.allclose(bipes, TEMPOS, atol=0.05)


def test_bipe_duplo_rapido_conta_dois(cfg):
    tempos = TEMPOS + [TEMPOS[3] + 0.3]
    bipes, _ = bipes_do_arquivo(audio_com_bipes(tempos), cfg)
    assert len(bipes) == len(tempos)


def test_som_longo_nao_e_bipe(cfg):
    # um apito de 1,5 s na mesma frequência (alarme, empilhadeira) não conta como bipe
    a = audio_com_bipes(TEMPOS)
    extra = audio_com_bipes([20.5], dur_bipe=1.5, ruido=0)
    bipes, _ = bipes_do_arquivo(a + extra, cfg)
    assert len(bipes) == len(TEMPOS)


def test_audio_curto_ou_vazio(cfg):
    assert bipes_do_arquivo(None, cfg) == ([], 0.0)
    assert bipes_do_arquivo(np.zeros(100, np.float32), cfg) == ([], 0.0)


def test_detector_em_blocos_igual_ao_arquivo_inteiro():
    # ao vivo o áudio chega em pedaços: o resultado tem que ser o mesmo
    a = audio_com_bipes(TEMPOS)
    inteiro = DetectorBipe(3200, 15).processar(_espectro(a), 0)
    det = DetectorBipe(3200, 15)
    em_blocos, i = [], 0
    passo = HOP * 10
    while i + 512 <= len(a):
        trecho = a[i:i + passo + 512 - HOP]
        S = _espectro(trecho)[:10]
        em_blocos += det.processar(S, i / SR_AUDIO)
        i += passo
    assert len(em_blocos) == len(inteiro) == len(TEMPOS)
    assert np.allclose(em_blocos, inteiro, atol=1e-6)
