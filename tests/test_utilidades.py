"""Turnos, ordem dos arquivos da GoPro, limpeza e configuração."""
from datetime import datetime, timedelta
from pathlib import Path

import motor


def com_turnos(cfg, txt):
    cfg["automacao"]["turnos"] = txt
    return cfg


def test_ler_turnos_ordena_e_ignora_invalidos(cfg):
    com_turnos(cfg, "22:35, 06:00, 14h20, 25:00, 06:00, xx")
    assert motor.ler_turnos(cfg) == [(6, 0), (14, 20), (22, 35)]


def test_turno_do_meio_do_dia(cfg):
    com_turnos(cfg, "06:00, 14:20, 22:35")
    nome, ini, fim = motor.turno_de(cfg, datetime(2026, 10, 7, 10, 0))
    assert nome == "1º turno"
    assert (ini, fim) == (datetime(2026, 10, 7, 6, 0), datetime(2026, 10, 7, 14, 20))


def test_turno_da_noite_atravessa_a_meia_noite(cfg):
    com_turnos(cfg, "06:00, 14:20, 22:35")
    for quando, ini in ((datetime(2026, 10, 7, 23, 0), datetime(2026, 10, 7, 22, 35)),
                        (datetime(2026, 10, 8, 3, 0), datetime(2026, 10, 7, 22, 35))):
        nome, i, f = motor.turno_de(cfg, quando)
        assert nome == "3º turno" and i == ini and f == datetime(2026, 10, 8, 6, 0)


def test_sem_turnos(cfg):
    assert motor.turno_de(cfg) == (None, None, None)


def test_ordem_dos_arquivos_da_gopro():
    nomes = ["GH020124.MP4", "GH010125.MP4", "GH010124.MP4", "GX010126.MP4", "outro.mp4", "GH030124.MP4"]
    ordem = [p.name for p in sorted(map(Path, nomes), key=motor.ordenar_gopro)]
    assert ordem == ["GH010124.MP4", "GH020124.MP4", "GH030124.MP4", "GH010125.MP4", "GX010126.MP4", "outro.mp4"]


def test_limpeza_apaga_so_sessoes_antigas(cfg, tmp_path):
    cfg["pasta_resultados"] = str(tmp_path)
    cfg["automacao"]["guardar_dias"] = 30
    velha = tmp_path / f"{datetime.now() - timedelta(days=40):%Y-%m-%d_%H%M%S}_ao_vivo"
    nova = tmp_path / f"{datetime.now() - timedelta(days=5):%Y-%m-%d_%H%M%S}_ao_vivo"
    outra = tmp_path / "minha_pasta"
    for d in (velha, nova, outra):
        d.mkdir()
    assert motor.limpar_antigos(cfg) == 1
    assert not velha.exists() and nova.exists() and outra.exists()


def test_limpeza_desligada(cfg, tmp_path):
    cfg["pasta_resultados"] = str(tmp_path)
    cfg["automacao"]["guardar_dias"] = 0
    (tmp_path / "2000-01-01_000000_ao_vivo").mkdir()
    assert motor.limpar_antigos(cfg) == 0


def test_config_do_posto_completa_o_padrao(tmp_path):
    arq = tmp_path / "config.yaml"
    arq.write_text("posto: Posto 07\nverificar:\n  bipe_duplo: false\n", encoding="utf-8")
    cfg = motor.carregar_config(arq)
    assert cfg["posto"] == "Posto 07"
    assert cfg["verificar"] == {"sem_leitor": True, "caixa_errada": True, "sem_bipe": True, "bipe_duplo": False}
    assert cfg["automacao"]["guardar_dias"] == 90


def test_config_do_repositorio_carrega():
    cfg = motor.carregar_config(motor.PASTA / "config.yaml")
    assert set(motor.PADRAO) <= set(cfg)
