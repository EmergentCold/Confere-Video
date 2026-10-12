"""Painel do Power BI (projeto PBIP): esquemas oficiais, campos usados x modelo, medidas, dados de exemplo.

Os validadores da Microsoft rodam quando estão instalados (no GitHub, sempre):
  - modelo TMDL lido pela biblioteca oficial do Power BI / Analysis Services (tests/validar_tmdl, .NET 8);
  - consultas Power Query (M) conferidas pelo analisador oficial de M (tests/validar_m, Node).
"""
import base64
import gzip
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import powerbi

RAIZ = Path(powerbi.__file__).resolve().parent
PROJ = RAIZ / "Microsoft365" / "PowerBI"
ESQ = RAIZ / "tests" / "esquemas_powerbi"


def ler_modelo():
    """Tabelas, colunas, medidas (com DAX) e relações lidas dos arquivos TMDL."""
    d = PROJ / "ConfereVideo.SemanticModel" / "definition"
    tabelas = {}
    for f in (d / "tables").glob("*.tmdl"):
        atual = col = None
        for linha in f.read_text(encoding="utf-8").splitlines():
            if m := re.match(r"^table (.+)$", linha):
                atual = m.group(1).strip("'")
                tabelas[atual] = {"colunas": {}, "medidas": {}}
            elif m := re.match(r"^\tcolumn (.+)$", linha):
                col = m.group(1).strip("'")
                tabelas[atual]["colunas"][col] = {}
            elif (m := re.match(r"^\t\t(\w+): (.+)$", linha)) and col:
                tabelas[atual]["colunas"][col][m.group(1)] = m.group(2)
            elif m := re.match(r"^\tmeasure (.+?) = (.+)$", linha):
                col = None
                tabelas[atual]["medidas"][m.group(1).strip("'")] = m.group(2)
            elif linha.startswith("\tpartition"):
                col = None
    rel = re.findall(r"fromColumn: (\w+)\.(\w+)\n\ttoColumn: (\w+)\.(\w+)",
                     (d / "relationships.tmdl").read_text(encoding="utf-8"))
    return tabelas, rel


def campos_dos_visuais():
    for f in (PROJ / "ConfereVideo.Report" / "definition" / "pages").rglob("visual.json"):
        texto = f.read_text(encoding="utf-8")
        for tipo, entidade, prop in re.findall(
                r'"(Column|Measure)": \{\s*"Expression": \{\s*"SourceRef": \{\s*"Entity": "([^"]+)"\s*\}\s*\},\s*'
                r'"Property": "([^"]+)"', texto):
            yield f, tipo, entidade, prop


def _sem_bytes_do_gzip(texto):
    """Os dados de exemplo vão comprimidos (gzip); a compressão pode variar entre versões do zlib,
    então a comparação usa o conteúdo descomprimido."""
    return re.sub(r'Binary\.FromText\("([^"]+)"',
                  lambda m: gzip.decompress(base64.b64decode(m.group(1))).decode("utf-8"), texto)


def test_projeto_no_repositorio_e_o_que_o_gerador_produz(tmp_path):
    gerado = tmp_path / "pbi"
    shutil.copytree(PROJ, gerado)
    powerbi.gravar(gerado)
    for rel, txt in powerbi.arquivos_projeto().items():
        assert _sem_bytes_do_gzip((PROJ / rel).read_text(encoding="utf-8")) == \
            _sem_bytes_do_gzip((gerado / rel).read_text(encoding="utf-8")), rel
    no_repo = {p.relative_to(PROJ) for p in PROJ.rglob("*") if p.is_file()}
    gerados = {p.relative_to(gerado) for p in gerado.rglob("*") if p.is_file()}
    assert no_repo == gerados, "rode: python powerbi.py"


def test_arquivos_seguem_os_esquemas_oficiais_do_power_bi():
    jsonschema = pytest.importorskip("jsonschema")
    from referencing import Registry, Resource

    def buscar(uri):
        local = ESQ / uri.split("/json-schemas/", 1)[1]
        return Resource.from_contents(json.loads(local.read_text(encoding="utf-8")))

    reg = Registry(retrieve=buscar)
    conferidos = 0
    for f in PROJ.rglob("*"):
        if f.suffix not in (".json", ".pbir", ".pbism", ".pbip") or "BaseThemes" in f.parts:
            continue
        doc = json.loads(f.read_text(encoding="utf-8"))
        if "RegisteredResources" in f.parts:  # tema do ConfereVídeo
            esquema = json.loads((ESQ / "reportThemeSchema-2.157.json").read_text(encoding="utf-8"))
        else:
            esquema = buscar(doc["$schema"]).contents
        jsonschema.Draft7Validator(esquema, registry=reg).validate(doc)
        conferidos += 1
    assert conferidos >= 40


def test_esquema_reprova_visual_com_erro():
    jsonschema = pytest.importorskip("jsonschema")
    from referencing import Registry, Resource
    reg = Registry(retrieve=lambda uri: Resource.from_contents(
        json.loads((ESQ / uri.split("/json-schemas/", 1)[1]).read_text(encoding="utf-8"))))
    f = next((PROJ / "ConfereVideo.Report" / "definition" / "pages").rglob("visual.json"))
    doc = json.loads(f.read_text(encoding="utf-8"))
    esquema = reg.get_or_retrieve(doc["$schema"]).value.contents
    doc["position"]["x"] = "esquerda"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft7Validator(esquema, registry=reg).validate(doc)


def test_todo_campo_dos_visuais_existe_no_modelo():
    tabelas, _ = ler_modelo()
    n = 0
    for f, tipo, ent, prop in campos_dos_visuais():
        assert ent in tabelas, (f, ent)
        onde = tabelas[ent]["colunas" if tipo == "Column" else "medidas"]
        assert prop in onde, f"{f.parent.name}: {ent}.{prop} ({tipo}) não existe no modelo"
        n += 1
    assert n >= 50


def test_medidas_so_usam_campos_que_existem():
    tabelas, _ = ler_modelo()
    medidas = {m for t in tabelas.values() for m in t["medidas"]}
    for t in tabelas.values():
        for nome, dax in t["medidas"].items():
            assert dax.count("(") == dax.count(")") and dax.count('"') % 2 == 0, nome
            sem_texto = re.sub(r'"[^"]*"', "", dax)
            for tab, col in re.findall(r"(\w+)\[([^\]]+)\]", sem_texto):
                assert col in tabelas[tab]["colunas"], f"{nome}: {tab}[{col}]"
            for ref in re.findall(r"(?<![\w\]])\[([^\]]+)\]", sem_texto):
                assert ref in medidas, f"{nome}: [{ref}]"


def test_relacoes_ligam_colunas_que_existem_e_chave_unica_do_lado_um():
    tabelas, rel = ler_modelo()
    assert len(rel) == 4
    for de, cde, para, cpara in rel:
        assert cde in tabelas[de]["colunas"] and cpara in tabelas[para]["colunas"]
        assert tabelas[de]["colunas"][cde]["dataType"] == tabelas[para]["colunas"][cpara]["dataType"]
    assert {(p, c) for _, _, p, c in rel} == {("Calendario", "Data"), ("PostoTurno", "PostoTurno")}


def test_dados_de_exemplo_embutidos_e_indicadores():
    erros, resumo = powerbi.dados_exemplo()
    texto = (PROJ / "ConfereVideo.SemanticModel" / "definition" / "expressions.tmdl").read_text(encoding="utf-8")
    b64 = re.search(r'Binary\.FromText\("([^"]+)"', texto).group(1)
    dados = json.loads(gzip.decompress(base64.b64decode(b64)))
    assert len(dados["erros"]["rows"]) == len(erros) and len(dados["turnos"]["rows"]) == len(resumo)
    assert all(len(r) == len(dados["erros"]["cols"]) for r in dados["erros"]["rows"])
    # as colunas que o modelo lê da lista existem nos dados de exemplo (mesmos nomes do SharePoint)
    for col in ("Title", "DataHora", "TratadoEm", "Status", "Confianca", "Operador", "OperadorOrigem"):
        assert col in dados["erros"]["cols"]
    for col in ("Title", "Inicio", "Fim", "Itens", "Erros", "ItensSemErro"):
        assert col in dados["turnos"]["cols"]
    ind = powerbi.indicadores(erros, resumo)
    assert ind["Erros alertados"] == ind["Erros pendentes"] + ind["Erros confirmados"] + ind["Falsos alarmes"]
    assert ind["Erros alertados"] <= ind["Erros detectados"] < ind["Itens conferidos"]
    assert 0 < ind["% falso alarme"] < 20 and 40 <= ind["Certeza média da IA"] <= 100
    # erros com certeza baixa não viram item da lista, mas contam no resumo do turno
    assert all(e["Confianca"] >= powerbi.CERTEZA_MINIMA for e in erros)


def test_gerar_painel_para_o_site_configurado(tmp_path):
    m = {"site_sharepoint": "https://empresa.sharepoint.com/sites/Operacao/", "lista_erros": "Erros_GRU",
         "lista_sessoes": "Turnos_GRU"}
    pbip = powerbi.gerar_painel(m, tmp_path)
    assert pbip.name == "ConfereVideo.pbip" and pbip.exists()
    exp = (tmp_path / "ConfereVideo.SemanticModel/definition/expressions.tmdl").read_text(encoding="utf-8")
    assert 'expression SiteSharePoint = "https://empresa.sharepoint.com/sites/Operacao" meta' in exp
    assert 'expression ListaErros = "Erros_GRU" meta' in exp and 'expression ListaTurnos = "Turnos_GRU" meta' in exp
    assert (tmp_path / "ConfereVideo.Report/StaticResources/SharedResources/BaseThemes/Fluent2-CY26SU08.json").exists()
    # gerar de novo na mesma pasta não deixa páginas velhas
    powerbi.gerar_painel(m, tmp_path)
    assert len(list((tmp_path / "ConfereVideo.Report/definition/pages").glob("*/page.json"))) == 3


@pytest.mark.skipif(not shutil.which("dotnet"), reason=".NET não instalado (roda no GitHub)")
def test_modelo_lido_pela_biblioteca_oficial_do_power_bi(tmp_path):
    saida = tmp_path / "modelo.json"
    r = subprocess.run(["dotnet", "run", "--project", str(RAIZ / "tests" / "validar_tmdl"), "--",
                        str(PROJ / "ConfereVideo.SemanticModel" / "definition"), str(saida)],
                       capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stdout + r.stderr
    m = json.loads(saida.read_text(encoding="utf-8"))["model"]
    assert {t["name"] for t in m["tables"]} == {"Erros", "Turnos", "PostoTurno", "Calendario", "Info", "Medidas"}
    assert len(m["relationships"]) == 4
    # consultas Power Query (M) do modelo conferidas pelo analisador oficial (precisa de npm install em tests/validar_m)
    if shutil.which("node") and (RAIZ / "tests" / "validar_m" / "node_modules").exists():
        r = subprocess.run(["node", str(RAIZ / "tests" / "validar_m" / "validar_m.js"), str(saida)],
                           capture_output=True, text=True, timeout=300)
        assert r.returncode == 0, r.stdout + r.stderr
