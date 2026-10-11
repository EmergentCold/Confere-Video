"""Demonstração da estação de 3 níveis: o roteiro encenado bate com as áreas e com a conferência.

Usa a mão exatamente onde o gerador a desenha (sem a IA): assim um ajuste no roteiro, nas áreas ou
no Ciclo que troque o resultado da demonstração aparece aqui, antes de gerar o vídeo de novo."""
import sys
from pathlib import Path

import yaml

import motor

sys.path.insert(0, str(Path(motor.PASTA) / "demo"))
import gerar_demo_3_niveis as g  # noqa: E402


def conferir(cfg, areas_dados):
    chaves, ev, dur = g.montar_roteiro()
    areas = motor.Areas(areas_dados, g.W, g.H)
    ciclo = motor.Ciclo(cfg, list(ev["bipes"]))
    passo = 1 / cfg["analisar_por_segundo"]
    fechados, t = [], 0.0
    while t < dur:
        mao = g.pose_em(chaves, t)[0]
        for e in ciclo.atualizar(t, {9: areas.onde(mao)}, None, {9: mao}, {9: 0.9}):
            fechados.append((round(t, 2), e["tipo"]))
        t += passo
    return ciclo, fechados, ev


def test_roteiro_da_os_12_itens_e_so_os_4_erros_encenados(cfg):
    ciclo, fechados, ev = conferir(cfg, g.areas())
    assert ciclo.n_ciclos == len(g.ITENS) == 12
    assert ciclo.n_incompletos == 0
    encenados = [tp for _, tp in g.ITENS if tp != "ok"]
    assert [tp for _, tp in fechados] == encenados
    # cada erro sai durante o item em que foi encenado
    for t, tipo in fechados:
        ini, fim, i, _, tp = next(l for l in ev["legendas"] if l[0] <= t <= l[1])
        assert tp == tipo, (t, i, tipo)


def test_tres_niveis_e_um_de_cada_erro():
    assert {n for n, _ in g.ITENS} == {1, 2, 3}
    assert sorted(tp for _, tp in g.ITENS if tp != "ok") == ["bipe_duplo", "caixa_errada", "sem_bipe", "sem_leitor"]


def test_areas_publicadas_sao_as_do_gerador():
    publicado = yaml.safe_load((Path(motor.PASTA) / "demo" / "areas_demo_3_niveis.yaml").read_text(encoding="utf-8"))
    assert publicado == g.areas()
    assert not motor.Areas.faltando(publicado)


def test_braco_alcanca_todos_os_alvos():
    chaves, _, dur = g.montar_roteiro()
    for f in range(int(dur * g.FPS)):
        mao, lean, ag, k, dx = g.pose_em(chaves, f / g.FPS)
        quadril = (g.X_OP + dx, g.QUADRIL_Y + ag)
        ombro = g.rot((g.X_OP + dx + 56, g.QUADRIL_Y + ag - 200), quadril, lean)
        e, w = g.braco_para_mao(ombro, mao, k)
        desenhada = (w[0] + g.EXT * (w[0] - e[0]), w[1] + g.EXT * (w[1] - e[1]))
        assert abs(desenhada[0] - mao[0]) < 3 and abs(desenhada[1] - mao[1]) < 3, f / g.FPS
