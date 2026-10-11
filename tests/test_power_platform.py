"""Fluxos do Power Automate gerados pelo programa: estrutura que o 'Importar pacote' exige e expressões
bem formadas (parênteses, aspas, etapas e variáveis que existem). Não substitui importar num ambiente
real, mas pega os erros de digitação que fariam a importação ou a execução falhar."""
import json
import re
import zipfile

import pytest

import power_platform as pp

M = {"site_sharepoint": "https://empresa.sharepoint.com/sites/Qualidade", "chave": "abc123",
     "emails_supervisores": "sup1@empresa.com; sup2@empresa.com", "emails_gestor": "gestor@empresa.com",
     "link_app": "https://apps.powerapps.com/play/e/xyz", "canal_teams": ""}
M_CANAL = dict(M, canal_teams="https://teams.microsoft.com/l/channel/19%3Aabc%40thread.tacv2/Geral?"
                              "groupId=12345678-1234-1234-1234-123456789abc&tenantId=x")


def escopos(acoes):
    """Cada dicionário de ações (o fluxo e o miolo de If/Foreach/Switch)."""
    yield acoes
    for a in acoes.values():
        for chave in ("actions",):
            if isinstance(a.get(chave), dict):
                yield from escopos(a[chave])
        if isinstance(a.get("else"), dict):
            yield from escopos(a["else"].get("actions", {}))
        for caso in (a.get("cases") or {}).values():
            yield from escopos(caso.get("actions", {}))
        if isinstance(a.get("default"), dict):
            yield from escopos(a["default"].get("actions", {}))


def todos_nomes(defin):
    return {n for esc in escopos(defin["actions"]) for n in esc} | set(defin["triggers"])


def textos(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for v in x.values():
            yield from textos(v)
    elif isinstance(x, list):
        for v in x:
            yield from textos(v)


def expressoes(s):
    """Expressões de um texto: a string inteira se começa com '@' (e não '@@'), mais cada @{...}."""
    if s.startswith("@") and not s.startswith("@@") and not s.startswith("@{"):
        yield s[1:]
    i = 0
    while True:
        i = s.find("@{", i)
        if i < 0:
            return
        prof, j, aspas = 0, i + 1, False
        while j < len(s):
            c = s[j]
            if c == "'":
                aspas = not aspas
            elif not aspas and c == "{":
                prof += 1
            elif not aspas and c == "}":
                prof -= 1
                if prof == 0:
                    break
            j += 1
        assert j < len(s), f"@{{ sem fechar em: {s[i:i + 120]}"
        yield s[i + 2:j]
        i = j + 1


def checar_expressao(e):
    sem_texto = re.sub(r"'(?:[^']|'')*'", "''", e)  # tira os textos entre aspas ('' = aspa escapada)
    assert sem_texto.count("'") % 2 == 0, f"aspas desbalanceadas: {e[:160]}"
    assert sem_texto.count("(") == sem_texto.count(")"), f"parênteses desbalanceados: {e[:160]}"
    assert sem_texto.count("[") == sem_texto.count("]"), f"colchetes desbalanceados: {e[:160]}"


@pytest.fixture(scope="module", params=[M, M_CANAL], ids=["chat", "canal"])
def fluxos(request):
    return {arq: fn(request.param) for arq, _, fn in pp.FLUXOS}


def test_cinco_fluxos():
    assert [a for a, _, _ in pp.FLUXOS] == ["1_Criar_listas", "2_Receber_eventos", "3_Cobranca_diaria",
                                            "4_Resumo_semanal", "5_Validar_no_Teams"]


def test_run_after_aponta_para_etapas_do_mesmo_bloco(fluxos):
    for arq, (defin, _) in fluxos.items():
        for esc in escopos(defin["actions"]):
            for nome, a in esc.items():
                for dep in a.get("runAfter", {}):
                    assert dep in esc, f"{arq}: '{nome}' espera '{dep}', que não está no mesmo bloco"


def test_expressoes_bem_formadas_e_referencias_existem(fluxos):
    for arq, (defin, _) in fluxos.items():
        nomes = todos_nomes(defin)
        variaveis = {v["name"] for t in textos(defin) for v in []}  # preenchido abaixo
        for esc in escopos(defin["actions"]):
            for a in esc.values():
                if a.get("type") == "InitializeVariable":
                    variaveis |= {v["name"] for v in a["inputs"]["variables"]}
        for s in textos(defin["actions"]):
            for e in expressoes(s):
                checar_expressao(e)
                for ref in re.findall(r"\b(?:body|outputs|items|actions)\('([^']+)'\)", e):
                    assert ref in nomes, f"{arq}: expressão cita a etapa '{ref}', que não existe"
                for var in re.findall(r"\bvariables\('([^']+)'\)", e):
                    assert var in variaveis, f"{arq}: variável '{var}' não inicializada"


def test_cartoes_do_teams_sao_json_valido(fluxos):
    for arq, (defin, _) in fluxos.items():
        for esc in escopos(defin["actions"]):
            for a in esc.values():
                par = a.get("inputs", {}).get("parameters", {}) if isinstance(a.get("inputs"), dict) else {}
                for chave in ("body/messageBody", "body/body/messageBody"):
                    if chave in par and not par[chave].startswith("@{outputs"):
                        cartao = json.loads(par[chave])
                        assert cartao["type"] == "AdaptiveCard"


def test_validar_no_teams(fluxos):
    defin, cons = fluxos["5_Validar_no_Teams"]
    assert set(cons) == {"sp", "teams", "o365"}
    gat = defin["triggers"]["Quando_um_erro_chegar"]
    assert gat["inputs"]["host"]["operationId"] == "GetOnNewItems" and gat["splitOn"]
    bloco = defin["actions"]["Nao_e_demonstracao"]["actions"]
    perg = bloco["Perguntar_ao_supervisor"]
    assert perg["type"] == "OpenApiConnectionWebhook" and perg["limit"]["timeout"] == "PT12H"
    assert perg["inputs"]["host"]["operationId"] == "PostCardAndWaitForResponse"
    cartao = json.loads(perg["inputs"]["parameters"]["body/body/messageBody"])
    decisoes = [x["data"]["decisao"] for x in cartao["actions"] if x["type"] == "Action.Submit"]
    assert decisoes == ["Confirmado", "Falso alarme"]
    # sem resposta no prazo: avisa o gestor
    assert bloco["Avisar_gestor_sem_resposta"]["runAfter"]["Perguntar_ao_supervisor"] == ["TimedOut", "Failed"]
    assert "gestor@empresa.com" in json.dumps(bloco["Avisar_gestor_sem_resposta"])


def test_validar_no_canal_quando_ha_canal():
    defin, _ = pp.fluxo_validar_teams(M_CANAL)
    par = defin["actions"]["Nao_e_demonstracao"]["actions"]["Perguntar_ao_supervisor"]["inputs"]["parameters"]
    assert par["location"] == "Channel" and par["body/body/recipient/groupId"].startswith("12345678")
    defin, _ = pp.fluxo_validar_teams(M)
    par = defin["actions"]["Nao_e_demonstracao"]["actions"]["Perguntar_ao_supervisor"]["inputs"]["parameters"]
    assert par["location"] == "Chat with Flow bot" and par["body/body/recipient/to"] == "sup1@empresa.com"


def test_escala_criada_e_consultada(fluxos):
    defin, _ = fluxos["1_Criar_listas"]
    assert "Criar_lista_Escala" in defin["actions"] and "ConfereVideo_Escala" in json.dumps(defin, ensure_ascii=False)
    erro = fluxos["2_Receber_eventos"][0]["actions"]["Tipo_de_evento"]["cases"]["Erro"]["actions"]
    esc = erro["Operador_pela_escala"]
    assert esc["runAfter"] == {"Gravar_link_do_recorte": ["Succeeded", "Failed", "Skipped", "TimedOut"]}
    assert esc["actions"]["Escala_do_posto"]["inputs"]["parameters"]["table"] == "ConfereVideo_Escala"


def test_pacotes_zip(tmp_path):
    arqs = pp.gerar_pacotes(M, tmp_path)
    assert len(arqs) == 5 and (tmp_path / "LEIA-ME.txt").exists()
    for arq in arqs:
        with zipfile.ZipFile(arq) as z:
            nomes = z.namelist()
            assert "manifest.json" in nomes and "Microsoft.Flow/flows/manifest.json" in nomes
            defin = [n for n in nomes if n.endswith("/definition.json")]
            assert len(defin) == 1
            fluxo = json.loads(z.read(defin[0]))
            assert fluxo["properties"]["definition"]["actions"]
            manif = json.loads(z.read("manifest.json"))
            conexoes = [r for r in manif["resources"].values() if r["type"] == "Microsoft.PowerApps/apis/connections"]
            assert len(conexoes) == len(fluxo["properties"]["connectionReferences"])
