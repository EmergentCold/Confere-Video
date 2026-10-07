"""Regras do item: prateleira -> leitor -> caixa (classe Ciclo do motor)."""
from motor import Ciclo

FPS = 8  # analisar_por_segundo padrão
P, L, C, O = "prateleira", "leitor", "caixa_posto", "outras_caixas"


def rodar(ciclo, quadros, t0=0.0):
    """quadros: lista de conjuntos de áreas (uma mão) ou dicionários {mão: áreas}.
    Retorna (erros, tempo do próximo quadro)."""
    erros = []
    t = t0
    for q in quadros:
        zonas = q if isinstance(q, dict) else {0: set(q) if not isinstance(q, str) else {q}}
        erros += ciclo.atualizar(t, zonas)
        t += 1 / FPS
    return erros, t


def seq(*partes):
    """seq((P, 3), (None, 2), ...) -> lista de quadros."""
    out = []
    for z, n in partes:
        out += [set() if z is None else {z}] * n
    return out


def tipos(erros):
    return sorted(e["tipo"] for e in erros)


def test_item_certo_sem_som(cfg):
    c = Ciclo(cfg)
    erros, _ = rodar(c, seq((P, 3), (None, 3), (L, 2), (None, 3), (C, 3), (None, 3)))
    assert erros == []
    assert (c.n_ciclos, c.n_ok) == (1, 1)


def test_sem_leitor(cfg):
    c = Ciclo(cfg)
    erros, _ = rodar(c, seq((P, 3), (None, 4), (C, 3), (None, 2)))
    assert tipos(erros) == ["sem_leitor"]
    assert (c.n_ciclos, c.n_ok) == (1, 0)


def test_caixa_errada(cfg):
    c = Ciclo(cfg)
    erros, _ = rodar(c, seq((P, 3), (None, 2), (L, 2), (None, 2), (O, 3), (None, 2)))
    assert tipos(erros) == ["caixa_errada"]


def test_caixa_errada_e_sem_leitor_juntos(cfg):
    c = Ciclo(cfg)
    erros, _ = rodar(c, seq((P, 3), (None, 2), (O, 3), (None, 2)))
    assert tipos(erros) == ["caixa_errada", "sem_leitor"]


def test_verificacao_desligada_nao_acusa(cfg):
    cfg["verificar"]["sem_leitor"] = False
    c = Ciclo(cfg)
    erros, _ = rodar(c, seq((P, 3), (None, 4), (C, 3)))
    assert erros == []


def test_tolera_um_quadro_de_falha_na_caixa(cfg):
    # caixa_posto pede 2 quadros: "caixa, falha, caixa" ainda conta
    c = Ciclo(cfg)
    erros, _ = rodar(c, seq((P, 3), (None, 2), (L, 2), (None, 2), (C, 1), (None, 1), (C, 1), (None, 3)))
    assert erros == [] and c.n_ciclos == 1


def test_passar_um_quadro_so_sobre_a_caixa_nao_conta(cfg):
    c = Ciclo(cfg)
    erros, _ = rodar(c, seq((P, 3), (None, 2), (C, 1), (None, 4)))
    assert erros == [] and c.n_ciclos == 0


def test_outra_mao_parada_no_leitor_nao_vale(cfg):
    # mão 1 fica o tempo todo no leitor; a mão 0 leva o item direto para a caixa
    c = Ciclo(cfg)
    quadros = ([{0: {P}, 1: {L}}] * 3 + [{0: set(), 1: {L}}] * 3 + [{0: {C}, 1: {L}}] * 3)
    erros, _ = rodar(c, quadros)
    assert tipos(erros) == ["sem_leitor"]


def test_nova_pegada_comeca_outro_item(cfg):
    c = Ciclo(cfg)
    erros, _ = rodar(c, seq((P, 3), (None, 3), (P, 3), (None, 2), (L, 2), (None, 2), (C, 3)))
    assert erros == []
    assert c.n_incompletos == 1 and c.n_ciclos == 1


def test_ciclo_longo_demais_e_descartado(cfg):
    cfg["tempo_max_ciclo_seg"] = 2
    c = Ciclo(cfg)
    erros, _ = rodar(c, seq((P, 3), (None, 3 * FPS), (C, 3)))
    assert erros == []
    assert c.n_incompletos == 1 and c.n_ciclos == 0


def test_comeca_no_leitor_quando_nao_viu_a_prateleira(cfg):
    c = Ciclo(cfg)
    erros, _ = rodar(c, seq((L, 2), (None, 2), (C, 3)))
    assert erros == [] and c.n_ciclos == 1


def test_segue_a_mao_quando_a_ia_troca_esquerda_e_direita(cfg):
    # a mão que pegou (id 0) passa a ser chamada de id 1 no meio do caminho
    c = Ciclo(cfg)
    c.escala = 1000.0
    t, erros = 0.0, []

    def q(zonas, pontos):
        nonlocal t
        erros.extend(c.atualizar(t, zonas, None, pontos))
        t += 1 / FPS

    for _ in range(3):
        q({0: {P}, 1: set()}, {0: (100, 100), 1: (600, 600)})
    for x in (130, 160, 190):  # IA troca os nomes: a mão do item agora é a 1
        q({0: set(), 1: set()}, {0: (600, 600), 1: (x, 100)})
    for _ in range(2):
        q({0: set(), 1: {L}}, {0: (600, 600), 1: (220, 100)})
    for x in (250, 280):
        q({0: set(), 1: set()}, {0: (600, 600), 1: (x, 100)})
    for _ in range(3):
        q({0: set(), 1: {C}}, {0: (600, 600), 1: (300, 100)})
    assert erros == [] and c.n_ok == 1


# ---- bipe ----
def item_com_leitor(c, t0=0.0):
    """Item certo pela imagem: pega em t0, passa no leitor ~t0+0.6 s, solta ~t0+1.4 s."""
    return rodar(c, seq((P, 3), (None, 2), (L, 2), (None, 2), (C, 3), (None, 2)), t0)


def test_bipe_certo(cfg):
    c = Ciclo(cfg, bipes=[0.7])
    erros, _ = item_com_leitor(c)
    assert erros == [] and c.n_ok == 1


def test_sem_bipe(cfg):
    c = Ciclo(cfg, bipes=[])
    erros, _ = item_com_leitor(c)
    assert tipos(erros) == ["sem_bipe"]


def test_bipe_duplo(cfg):
    c = Ciclo(cfg, bipes=[0.7, 0.9])
    erros, _ = item_com_leitor(c)
    assert tipos(erros) == ["bipe_duplo"]
    assert erros[0]["bipes"] == 2


def test_sem_leitor_nao_confere_bipe(cfg):
    c = Ciclo(cfg, bipes=[])
    erros, _ = rodar(c, seq((P, 3), (None, 2), (C, 3)))
    assert tipos(erros) == ["sem_leitor"]
