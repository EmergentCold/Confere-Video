"""Câmera ao vivo (AoVivo) tocando o vídeo de demonstração, com uma IA de mentira."""
import threading
import time

import pytest

import motor

VIDEO = motor.PASTA / "demo" / "demo_esteira_cigarros.mp4"


class IA:
    """Faz o papel do YOLO: não vê ninguém; pode falhar em alguns quadros."""

    def __init__(self, falhar=lambda n: False):
        self.falhar, self.n = falhar, 0

    def predict(self, *a, **k):
        return []

    def track(self, *a, **k):
        self.n += 1
        if self.falhar(self.n):
            raise RuntimeError(f"falha de teste no quadro {self.n}")
        return [type("R", (), {"boxes": None, "keypoints": None})()]


@pytest.fixture
def ambiente(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(motor, "PASTA", tmp_path)  # erro.log vai para a pasta do teste
    cfg["pasta_resultados"] = str(tmp_path / "resultados")
    cfg["usar_som_do_bipe"] = False
    return cfg, motor.ler_yaml(VIDEO.parent / "areas_demo.yaml"), tmp_path


def rodar(cfg, areas, ia, segundos):
    eventos = []
    av = motor.AoVivo(str(VIDEO), cfg, areas, ia, ev=lambda t, d=None: eventos.append((t, d)), modo="demo")
    av.start()
    threading.Timer(segundos, av.parar).start()
    av.join(60)
    assert not av.is_alive()
    return av, [t for t, _ in eventos], eventos


def test_roda_e_fecha_o_relatorio(ambiente):
    cfg, areas, _ = ambiente
    av, tipos, _ = rodar(cfg, areas, IA(), 2.5)
    assert tipos[-1] == "fim" and "alerta" not in tipos
    assert (av.sessao.pasta / "relatorio.html").exists()


def test_quadro_com_falha_nao_derruba_a_conferencia(ambiente):
    cfg, areas, pasta = ambiente
    ia = IA(falhar=lambda n: n % 3 == 0)  # 1 em cada 3 quadros falha
    av, tipos, _ = rodar(cfg, areas, ia, 3)
    assert ia.n > 10
    assert tipos[-1] == "fim" and "alerta" not in tipos
    log = (pasta / "erro.log").read_text(encoding="utf-8")
    assert log.count("Falha ao analisar um quadro") == 1  # não enche o erro.log a cada quadro


def test_falha_que_se_repete_para_e_avisa(ambiente, monkeypatch):
    cfg, areas, pasta = ambiente
    monkeypatch.setattr(motor, "FALHAS_SEGUIDAS_MAX", 5)
    t0 = time.time()
    av, tipos, eventos = rodar(cfg, areas, IA(falhar=lambda n: True), 30)
    assert time.time() - t0 < 15  # parou sozinha, sem esperar o "parar"
    assert "fim" in tipos and tipos[-1] == "alerta"
    assert "parou por um erro" in eventos[-1][1]
    assert (av.sessao.pasta / "relatorio.html").exists()  # o que já tinha sido visto foi salvo
    assert "falha de teste" in (pasta / "erro.log").read_text(encoding="utf-8")


def test_parada_por_erro_grava_os_recortes_pendentes(ambiente, monkeypatch):
    cfg, areas, _ = ambiente
    monkeypatch.setattr(motor, "FALHAS_SEGUIDAS_MAX", 5)
    original = motor.Analisador.processar
    chamadas = {"n": 0}

    def processar(self, quadro, t, rotulo=""):
        chamadas["n"] += 1
        img, _ = original(self, quadro, t, rotulo)
        if chamadas["n"] == 12:  # um erro marcado...
            return img, [{"tipo": "sem_leitor", "t_ini": t - 1, "t": t, "trilha": []}]
        if chamadas["n"] > 12:   # ...e logo depois a análise quebra de vez
            raise RuntimeError("falha de teste")
        return img, []

    monkeypatch.setattr(motor.Analisador, "processar", processar)
    t0 = time.time()
    av, tipos, _ = rodar(cfg, areas, IA(), 60)
    assert time.time() - t0 < 30  # não fica esperando o recorte que nunca seria gravado
    assert tipos[-1] == "alerta"
    assert len(av.sessao.erros) == 1 and av.sessao.gravando == 0


def test_microfone_esquece_bipes_antigos():
    bipes = [1.0, 2.0, 50.0, 80.0, 81.0]
    mesma = bipes
    motor.esquecer_bipes(bipes, 60.0)
    assert bipes is mesma and bipes == [80.0, 81.0]
    motor.esquecer_bipes(bipes, 0.0)
    assert bipes == [80.0, 81.0]
