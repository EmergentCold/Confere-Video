"""Painel do Power BI do ConfereVídeo (projeto PBIP: modelo em TMDL + relatório em PBIR).

Lê as listas do SharePoint que o fluxo 2 preenche (ConfereVideo_Erros e ConfereVideo_Turnos). Sem o
endereço do site (parâmetro SiteSharePoint = "exemplo"), usa dados de exemplo embutidos, para ver o
painel antes de ligar o Microsoft 365.

    python powerbi.py                      -> refaz o modelo em Microsoft365/PowerBI (dados de exemplo)
    python powerbi.py PASTA --site URL     -> painel pronto para o seu site, em PASTA

No programa: tela Microsoft 365 > "Gerar painel do Power BI…" (usa o site e as listas configurados).
"""
import base64
import gzip
import hashlib
import json
import math
import random
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PASTA = Path(__file__).resolve().parent
MODELO = PASTA / "Microsoft365" / "PowerBI"
NOME = "ConfereVideo"
FUSO_PADRAO = -3
TRATATIVAS = ["Orientação verbal", "Retreinamento no posto", "Advertência", "Só registro"]
TIPOS = {"sem_leitor": "Sem passar no leitor", "caixa_errada": "Outra caixa",
         "sem_bipe": "Sem bipe", "bipe_duplo": "Bipe duplo"}
CERTEZA_MINIMA = 40

# versões dos esquemas do formato PBIR usadas nos arquivos (cópia em tests/esquemas_powerbi)
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/"
V = {"report": "3.3.0", "page": "2.1.0", "pagesMetadata": "1.1.0", "versionMetadata": "1.0.0",
     "visualContainer": "2.12.0"}
VERSAO_IMPORT = {"visual": "2.12.0", "report": "3.3.0", "page": "2.1.0"}
TEMA_BASE = "Fluent2-CY26SU08"


# =====================================================================================
# Dados de exemplo (determinísticos): 4 semanas, 3 postos, 2 turnos
# =====================================================================================
def dados_exemplo(semente=7):
    rnd = random.Random(semente)
    fuso = timezone(timedelta(hours=FUSO_PADRAO))
    agora = datetime(2026, 10, 9, 23, 0, tzinfo=fuso)
    postos = {"Posto 01": 0.0045, "Posto 02": 0.0055, "Posto 03": 0.0090}
    turnos = {"Turno A": ((6, 0), (14, 20)), "Turno B": ((14, 20), (22, 35))}
    operadores = {("Posto 01", "Turno A"): "Ana Souza", ("Posto 01", "Turno B"): "Bruno Lima",
                  ("Posto 02", "Turno A"): "Carla Dias", ("Posto 02", "Turno B"): "Diego Rocha",
                  ("Posto 03", "Turno A"): "Elisa Prado", ("Posto 03", "Turno B"): "Fábio Nunes"}
    supervisores = {"Turno A": "Marcos Teixeira", "Turno B": "Paula Ribeiro"}
    pesos_tipo = {"Posto 03": [0.30, 0.32, 0.20, 0.18]}

    def poisson(lam):
        L, k, p = math.exp(-lam), 0, 1.0
        while True:
            p *= rnd.random()
            if p <= L:
                return k
            k += 1

    def utc(d):
        return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    erros, resumo = [], []
    dia0 = datetime(2026, 9, 14, tzinfo=fuso)
    for n_dia in range(26):
        dia = dia0 + timedelta(days=n_dia)
        if dia.weekday() == 6:  # domingo sem operação
            continue
        semana = n_dia // 7
        for posto, taxa in postos.items():
            for turno, ((h0, m0), (h1, m1)) in turnos.items():
                ini = dia.replace(hour=h0, minute=m0)
                fim = dia.replace(hour=h1, minute=m1)
                itens = max(600, int(rnd.gauss(1150, 110)))
                lam = itens * taxa * (1.2 if turno == "Turno B" else 1.0) * (1.25, 1.1, 0.95, 0.85)[semana]
                n_err = poisson(lam)
                cont = {t: 0 for t in TIPOS}
                op = operadores[(posto, turno)]
                if rnd.random() < 0.08:  # cobertura de folga
                    op = rnd.choice([o for o in operadores.values() if o != op])
                for k in range(n_err):
                    tipo = rnd.choices(list(TIPOS), pesos_tipo.get(posto, [0.36, 0.18, 0.26, 0.20]))[0]
                    cont[tipo] += 1
                    quando = ini + (fim - ini) * rnd.random()
                    certeza = int(min(100, max(15, rnd.gauss(78, 15))))
                    if certeza < CERTEZA_MINIMA:  # fica só no relatório do posto: não vira item da lista
                        continue
                    status, tratativa, tratado_por, tratado_em = "Pendente", "", "", ""
                    if quando < agora - timedelta(days=2) or rnd.random() < 0.4:
                        falso = rnd.random() < (0.30 if certeza < 60 else 0.06)
                        status = "Falso alarme" if falso else "Confirmado"
                        tratativa = "" if falso else rnd.choices(TRATATIVAS, [0.6, 0.2, 0.05, 0.15])[0]
                        tratado_por = supervisores[turno]
                        t_trat = min(agora, quando + timedelta(hours=rnd.uniform(0.3, 16)))
                        tratado_em = utc(t_trat)
                    seq = len(erros) + 1
                    erros.append({
                        "Title": f"{posto.replace(' ', '').upper()}-{quando:%Y%m%d-%H%M%S}-{seq:04d}",
                        "TipoCodigo": tipo, "Tipo": TIPOS[tipo], "DataHora": utc(quando),
                        "Unidade": "Guarulhos II", "Local": "Separação de cigarros", "Posto": posto,
                        "Turno": turno, "Origem": "Câmera ao vivo",
                        "Bipes": {"sem_bipe": 0, "bipe_duplo": 2, "caixa_errada": 1}.get(tipo),
                        "Confianca": certeza, "Status": status, "Tratativa": tratativa,
                        "Operador": op, "OperadorOrigem": "Crachá" if rnd.random() < 0.78 else "Escala",
                        "TratadoPor": tratado_por, "TratadoEm": tratado_em, "LinkRecorte": ""})
                total = sum(cont.values())
                resumo.append({
                    "Title": f"{posto.replace(' ', '').upper()}-{dia:%Y%m%d}-{turno[-1]}",
                    "Inicio": utc(ini), "Fim": utc(fim), "Unidade": "Guarulhos II",
                    "Local": "Separação de cigarros", "Posto": posto, "Turno": turno, "Origem": "Câmera ao vivo",
                    "Itens": itens, "Erros": total, "ItensSemErro": itens - total,
                    "SemLeitor": cont["sem_leitor"], "CaixaErrada": cont["caixa_errada"],
                    "SemBipe": cont["sem_bipe"], "BipeDuplo": cont["bipe_duplo"]})
    return erros, resumo


def _embutir(erros, resumo):
    """Dados de exemplo compactos (JSON em colunas, gzip, base64) para ir dentro do modelo."""
    def tab(linhas):
        cols = list(linhas[0])
        return {"cols": cols, "rows": [[l[c] for c in cols] for l in linhas]}
    bruto = json.dumps({"erros": tab(erros), "turnos": tab(resumo)}, ensure_ascii=False, separators=(",", ":"))
    return base64.b64encode(gzip.compress(bruto.encode("utf-8"), 9, mtime=0)).decode()


def indicadores(erros, resumo):
    """Os números que o painel deve mostrar com estes dados (conferem as medidas DAX)."""
    itens = sum(r["Itens"] for r in resumo)
    sem_erro = sum(r["ItensSemErro"] for r in resumo)
    detectados = sum(r["Erros"] for r in resumo)
    st = {s: sum(1 for e in erros if e["Status"] == s) for s in ("Pendente", "Confirmado", "Falso alarme")}
    horas = [(datetime.fromisoformat(e["TratadoEm"].replace("Z", "+00:00")) -
              datetime.fromisoformat(e["DataHora"].replace("Z", "+00:00"))).total_seconds() // 60 / 60
             for e in erros if e["TratadoEm"]]
    return {
        "Itens conferidos": itens, "% itens sem erro": round(sem_erro / itens * 100, 1),
        "Erros detectados": detectados, "Erros a cada mil itens": round(detectados / itens * 1000, 2),
        "Erros alertados": len(erros), "Erros pendentes": st["Pendente"], "Erros confirmados": st["Confirmado"],
        "Falsos alarmes": st["Falso alarme"],
        "% falso alarme": round(st["Falso alarme"] / (st["Confirmado"] + st["Falso alarme"]) * 100, 1),
        "Horas até a tratativa": round(sum(horas) / len(horas), 1),
        "Certeza média da IA": round(sum(e["Confianca"] for e in erros) / len(erros), 1),
    }


# =====================================================================================
# Modelo semântico (TMDL)
# =====================================================================================
def _tmdl_nome(n):
    return n if n.replace("_", "").isalnum() and n.isascii() else "'" + n.replace("'", "''") + "'"


def _m_texto(s):
    return '"' + s.replace('"', '""') + '"'


def _bloco(expr, recuo):
    return "\n".join(recuo + linha if linha.strip() else "" for linha in expr.strip("\n").split("\n"))


def _coluna(nome, tipo, fmt=None, oculta=False, data=False, ordenar=None, categoria=None, chave=False):
    t = [f"\tcolumn {_tmdl_nome(nome)}", f"\t\tdataType: {tipo}"]
    if fmt:
        t.append(f"\t\tformatString: {fmt}")
    if oculta:
        t.append("\t\tisHidden")
    if chave:
        t.append("\t\tisKey")
    if categoria:
        t.append(f"\t\tdataCategory: {categoria}")
    t.append("\t\tsummarizeBy: none")
    t.append(f"\t\tsourceColumn: {nome}")
    if ordenar:
        t.append(f"\t\tsortByColumn: {_tmdl_nome(ordenar)}")
    if data:
        t += ["", "\t\tannotation UnderlyingDateTimeDataType = Date"]
    return "\n".join(t) + "\n"


def _tabela(nome, colunas, m, medidas=(), extra=""):
    t = [f"table {_tmdl_nome(nome)}", extra.rstrip()] if extra else [f"table {_tmdl_nome(nome)}"]
    t.append("")
    for nm, expr, fmt in medidas:
        t.append(f"\tmeasure {_tmdl_nome(nm)} = {expr}")
        if fmt:
            t.append(f"\t\tformatString: {fmt}")
        t.append("")
    for c in colunas:
        t.append(c)
    t += [f"\tpartition {_tmdl_nome(nome)} = m", "\t\tmode: import", "\t\tsource =", _bloco(m, "\t\t\t\t"), "",
          "\tannotation PBI_ResultType = Table", ""]
    return "\n".join(t)


M_COMUM = """
UsarExemplo = Text.Trim(SiteSharePoint) = "" or Text.Lower(Text.Trim(SiteSharePoint)) = "exemplo",
ParaLocal = (v as any) as nullable datetime =>
    if v = null or v = "" then null
    else DateTimeZone.RemoveZone(DateTimeZone.SwitchZone(
        if Value.Is(v, type datetimezone) then v
        else if Value.Is(v, type datetime) then DateTime.AddZone(v, 0)
        else DateTimeZone.From(v), FusoHorario)),
Num = (v as any) as nullable number => if v = null or v = "" then null else Number.From(v),
Txt = (v as any) as text => if v = null then "" else Text.Trim(Text.From(v)),
OuPadrao = (v as text, padrao as text) as text => if v = "" then padrao else v,
"""


def m_erros():
    texto = ["Title", "TipoCodigo", "Tipo", "Unidade", "Local", "Posto", "Turno", "Origem", "Status",
             "Tratativa", "Operador", "OperadorOrigem", "TratadoPor", "LinkRecorte"]
    cols = texto + ["DataHora", "TratadoEm", "Bipes", "Confianca"]
    return f"""
let
{_bloco(M_COMUM, "    ")}
    Bruto = if UsarExemplo then DadosExemplo[Erros]
            else SharePoint.Tables(SiteSharePoint, [ApiVersion = 15]){{[Title = ListaErros]}}[Items],
    Selecionado = Table.SelectColumns(Bruto, {{{", ".join(_m_texto(c) for c in cols)}}}, MissingField.UseNull),
    Convertido = Table.TransformColumns(Selecionado,
        List.Transform({{{", ".join(_m_texto(c) for c in texto)}}}, each {{_, Txt, type text}}) & {{
        {{"DataHora", ParaLocal, type nullable datetime}}, {{"TratadoEm", ParaLocal, type nullable datetime}},
        {{"Bipes", Num, type nullable number}}, {{"Confianca", Num, type nullable number}}}}),
    SemDemonstracao = if IncluirDemonstracao then Convertido
                      else Table.SelectRows(Convertido, each [Origem] <> "Demonstração"),
    Rotulos = Table.TransformColumns(SemDemonstracao, {{
        {{"Posto", each OuPadrao(_, "(sem posto)"), type text}}, {{"Turno", each OuPadrao(_, "(sem turno)"), type text}},
        {{"Operador", each OuPadrao(_, "(não identificado)"), type text}},
        {{"OperadorOrigem", each OuPadrao(_, "(não identificado)"), type text}}}}),
    Renomeado = Table.RenameColumns(Rotulos, {{{{"Title", "Codigo"}}}}),
    ComData = Table.AddColumn(Renomeado, "Data", each if [DataHora] = null then null else DateTime.Date([DataHora]), type nullable date),
    ComHora = Table.AddColumn(ComData, "Hora", each if [DataHora] = null then null else Time.Hour([DataHora]), Int64.Type),
    ComChave = Table.AddColumn(ComHora, "PostoTurno", each [Posto] & " | " & [Turno], type text),
    ComFaixa = Table.AddColumn(ComChave, "Faixa de certeza", each
        if [Confianca] = null then "(sem dado)" else if [Confianca] < 60 then "40 a 59%"
        else if [Confianca] < 80 then "60 a 79%" else "80 a 100%", type text),
    Tipado = Table.TransformColumnTypes(ComFaixa, {{{{"Bipes", Int64.Type}}, {{"Confianca", Int64.Type}}}})
in
    Tipado
"""


def m_turnos():
    texto = ["Title", "Unidade", "Local", "Posto", "Turno", "Origem"]
    nums = ["Itens", "Erros", "ItensSemErro", "SemLeitor", "CaixaErrada", "SemBipe", "BipeDuplo"]
    cols = texto + ["Inicio", "Fim"] + nums
    return f"""
let
{_bloco(M_COMUM, "    ")}
    Bruto = if UsarExemplo then DadosExemplo[Turnos]
            else SharePoint.Tables(SiteSharePoint, [ApiVersion = 15]){{[Title = ListaTurnos]}}[Items],
    Selecionado = Table.SelectColumns(Bruto, {{{", ".join(_m_texto(c) for c in cols)}}}, MissingField.UseNull),
    Convertido = Table.TransformColumns(Selecionado,
        List.Transform({{{", ".join(_m_texto(c) for c in texto)}}}, each {{_, Txt, type text}}) &
        List.Transform({{{", ".join(_m_texto(c) for c in nums)}}}, each {{_, (v) => if Num(v) = null then 0 else Num(v), type number}}) & {{
        {{"Inicio", ParaLocal, type nullable datetime}}, {{"Fim", ParaLocal, type nullable datetime}}}}),
    SemDemonstracao = if IncluirDemonstracao then Convertido
                      else Table.SelectRows(Convertido, each [Origem] <> "Demonstração"),
    Rotulos = Table.TransformColumns(SemDemonstracao, {{
        {{"Posto", each OuPadrao(_, "(sem posto)"), type text}}, {{"Turno", each OuPadrao(_, "(sem turno)"), type text}}}}),
    Renomeado = Table.RenameColumns(Rotulos, {{{{"Title", "Codigo"}}}}),
    ComData = Table.AddColumn(Renomeado, "Data", each if [Inicio] = null then null else DateTime.Date([Inicio]), type nullable date),
    ComChave = Table.AddColumn(ComData, "PostoTurno", each [Posto] & " | " & [Turno], type text),
    Tipado = Table.TransformColumnTypes(ComChave, List.Transform({{{", ".join(_m_texto(c) for c in nums)}}}, each {{_, Int64.Type}}))
in
    Tipado
"""


M_POSTO_TURNO = """
let
    Pares = Table.Combine({Table.SelectColumns(Erros, {"Posto", "Turno"}), Table.SelectColumns(Turnos, {"Posto", "Turno"})}),
    Distintos = Table.Distinct(Pares),
    ComChave = Table.AddColumn(Distintos, "PostoTurno", each [Posto] & " | " & [Turno], type text)
in
    ComChave
"""

M_CALENDARIO = """
let
    Datas = List.RemoveNulls(List.Combine({Erros[Data], Turnos[Data]})),
    Hoje = Date.From(DateTimeZone.SwitchZone(DateTimeZone.UtcNow(), FusoHorario)),
    Inicio = if List.IsEmpty(Datas) then Date.AddDays(Hoje, -30) else Date.StartOfMonth(List.Min(Datas)),
    Fim = if List.IsEmpty(Datas) then Hoje else List.Max({List.Max(Datas), Hoje}),
    Lista = List.Dates(Inicio, Duration.Days(Fim - Inicio) + 1, #duration(1, 0, 0, 0)),
    Base = Table.FromList(Lista, Splitter.SplitByNothing(), type table [Data = date]),
    Ano = Table.AddColumn(Base, "Ano", each Date.Year([Data]), Int64.Type),
    AnoMes = Table.AddColumn(Ano, "AnoMesNumero", each Date.Year([Data]) * 100 + Date.Month([Data]), Int64.Type),
    Mes = Table.AddColumn(AnoMes, "Mes", each Date.ToText([Data], [Format = "MMM/yyyy", Culture = "pt-BR"]), type text),
    DiaNum = Table.AddColumn(Mes, "DiaSemanaNumero", each Date.DayOfWeek([Data], Day.Monday) + 1, Int64.Type),
    Dia = Table.AddColumn(DiaNum, "DiaSemana", each Date.ToText([Data], [Format = "ddd", Culture = "pt-BR"]), type text),
    Semana = Table.AddColumn(Dia, "Semana", each Date.StartOfWeek([Data], Day.Monday), type date)
in
    Semana
"""

M_INFO = """
let
    UsarExemplo = Text.Trim(SiteSharePoint) = "" or Text.Lower(Text.Trim(SiteSharePoint)) = "exemplo",
    Agora = DateTimeZone.RemoveZone(DateTimeZone.SwitchZone(DateTimeZone.UtcNow(), FusoHorario)),
    Fonte = if UsarExemplo then "Dados de exemplo. Para ver os seus: Transformar dados > Editar parâmetros > SiteSharePoint"
            else "SharePoint: " & SiteSharePoint,
    Tabela = #table(type table [Fonte = text, Atualizado = datetime], {{Fonte, Agora}})
in
    Tabela
"""

M_MEDIDAS = """
let
    Tabela = #table(type table [Medidas = text], {})
in
    Tabela
"""

MEDIDAS = [  # nome, DAX, formato
    ("Itens conferidos", "SUM(Turnos[Itens])", "#,0"),
    ("Itens sem erro", "SUM(Turnos[ItensSemErro])", "#,0"),
    ("% itens sem erro", "DIVIDE([Itens sem erro], [Itens conferidos])", "0.0%"),
    ("Erros detectados", "SUM(Turnos[Erros])", "#,0"),
    ("Erros a cada mil itens", "DIVIDE([Erros detectados], [Itens conferidos]) * 1000", "#,0.0"),
    ("Erros alertados", "COUNTROWS(Erros)", "#,0"),
    ("Erros pendentes", 'COALESCE(CALCULATE(COUNTROWS(Erros), Erros[Status] = "Pendente"), 0)', "#,0"),
    ("Erros confirmados", 'CALCULATE(COUNTROWS(Erros), Erros[Status] = "Confirmado")', "#,0"),
    ("Falsos alarmes", 'CALCULATE(COUNTROWS(Erros), Erros[Status] = "Falso alarme")', "#,0"),
    ("% falso alarme", "DIVIDE([Falsos alarmes], [Erros confirmados] + [Falsos alarmes])", "0.0%"),
    ("Horas até a tratativa",
     "AVERAGEX(FILTER(Erros, NOT ISBLANK(Erros[TratadoEm]) && NOT ISBLANK(Erros[DataHora])), "
     "DATEDIFF(Erros[DataHora], Erros[TratadoEm], MINUTE) / 60)", "#,0.0"),
    ("Certeza média da IA", "DIVIDE(AVERAGE(Erros[Confianca]), 100)", "0%"),
    ("Fonte dos dados", "SELECTEDVALUE(Info[Fonte])", None),
    ("Atualizado em", '"Atualizado em " & FORMAT(MAX(Info[Atualizado]), "dd/mm/yyyy hh:nn")', None),
]

RELACOES = [("Erros", "Data", "Calendario", "Data"), ("Turnos", "Data", "Calendario", "Data"),
            ("Erros", "PostoTurno", "PostoTurno", "PostoTurno"), ("Turnos", "PostoTurno", "PostoTurno", "PostoTurno")]


def arquivos_modelo(site="exemplo", lista_erros="ConfereVideo_Erros", lista_turnos="ConfereVideo_Turnos",
                    fuso=FUSO_PADRAO, incluir_demo=False):
    """{caminho relativo: texto} da pasta ConfereVideo.SemanticModel."""
    erros, resumo = dados_exemplo()
    d = "definition/"
    arq = {}
    arq["definition.pbism"] = json.dumps({
        "$schema": SCHEMA + "item/semanticModel/definitionProperties/1.0.0/schema.json",
        "version": "4.0", "settings": {}}, indent=2)
    arq[".pbi/editorSettings.json"] = json.dumps({
        "$schema": SCHEMA + "item/semanticModel/editorSettings/1.0.0/schema.json",
        "autodetectRelationships": False, "parallelQueryLoading": True, "typeDetectionEnabled": True,
        "relationshipImportEnabled": False, "runBackgroundAnalysis": True}, indent=2)
    arq[d + "database.tmdl"] = "database\n\tcompatibilityLevel: 1600\n"
    tabelas = ["Erros", "Turnos", "PostoTurno", "Calendario", "Info", "Medidas"]
    ordem = ["SiteSharePoint", "ListaErros", "ListaTurnos", "FusoHorario", "IncluirDemonstracao", "DadosExemplo"] + tabelas
    arq[d + "model.tmdl"] = "\n".join([
        "model Model", "\tculture: pt-BR", "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
        "\tdiscourageImplicitMeasures", "\tsourceQueryCulture: pt-BR", "\tdataAccessOptions",
        "\t\tlegacyRedirects", "\t\treturnErrorValuesAsNull", "",
        f"annotation PBI_QueryOrder = {json.dumps(ordem, ensure_ascii=False)}", "",
        "annotation __PBI_TimeIntelligenceEnabled = 0", "",
        *[f"ref table {t}" for t in tabelas], ""])

    def parametro(nome, valor_m, tipo, desc):
        return (f"/// {desc}\nexpression {nome} = {valor_m} meta [IsParameterQuery = true, Type = \"{tipo}\", "
                f"IsParameterQueryRequired = true]\n\n\tannotation PBI_ResultType = {tipo}\n")
    exemplo = _embutir(erros, resumo)
    arq[d + "expressions.tmdl"] = "\n".join([
        parametro("SiteSharePoint", _m_texto(site), "Text",
                  "Endereço do site do SharePoint (ex.: https://empresa.sharepoint.com/sites/Operacao). "
                  "Com \"exemplo\", o painel usa os dados de exemplo."),
        parametro("ListaErros", _m_texto(lista_erros), "Text", "Nome da lista de erros do ConfereVídeo."),
        parametro("ListaTurnos", _m_texto(lista_turnos), "Text", "Nome da lista de turnos do ConfereVídeo."),
        parametro("FusoHorario", str(int(fuso)), "Number", "Fuso horário das datas, em horas (Brasília: -3)."),
        parametro("IncluirDemonstracao", "true" if incluir_demo else "false", "Logical",
                  "Mostrar também os itens que vieram da demonstração do programa."),
        "/// Dados de exemplo (4 semanas, 3 postos, 2 turnos), usados quando SiteSharePoint = \"exemplo\".",
        "expression DadosExemplo =",
        _bloco(f"""
let
    Bruto = Json.Document(Binary.Decompress(Binary.FromText("{exemplo}", BinaryEncoding.Base64), Compression.GZip)),
    Tabela = (t as record) as table => Table.FromRows(t[rows], t[cols]),
    Dados = [Erros = Tabela(Bruto[erros]), Turnos = Tabela(Bruto[turnos])]
in
    Dados
""", "\t\t"),
        "", "\tannotation PBI_ResultType = Record", ""])

    arq[d + "tables/Erros.tmdl"] = _tabela("Erros", [
        _coluna("Codigo", "string"), _coluna("TipoCodigo", "string", oculta=True), _coluna("Tipo", "string"),
        _coluna("DataHora", "dateTime", fmt="dd/mm/yyyy hh:nn"), _coluna("Data", "dateTime", fmt="dd/mm/yyyy", data=True),
        _coluna("Hora", "int64", fmt="0"), _coluna("Unidade", "string"), _coluna("Local", "string"),
        _coluna("Posto", "string"), _coluna("Turno", "string"), _coluna("PostoTurno", "string", oculta=True),
        _coluna("Origem", "string"), _coluna("Status", "string"), _coluna("Tratativa", "string"),
        _coluna("Operador", "string"), _coluna("OperadorOrigem", "string"), _coluna("TratadoPor", "string"),
        _coluna("TratadoEm", "dateTime", fmt="dd/mm/yyyy hh:nn"), _coluna("Bipes", "int64", fmt="0"),
        _coluna("Confianca", "int64", fmt="0"), _coluna("Faixa de certeza", "string"),
        _coluna("LinkRecorte", "string", categoria="WebUrl")], m_erros())
    arq[d + "tables/Turnos.tmdl"] = _tabela("Turnos", [
        _coluna("Codigo", "string"), _coluna("Inicio", "dateTime", fmt="dd/mm/yyyy hh:nn"),
        _coluna("Fim", "dateTime", fmt="dd/mm/yyyy hh:nn"), _coluna("Data", "dateTime", fmt="dd/mm/yyyy", data=True),
        _coluna("Unidade", "string"), _coluna("Local", "string"), _coluna("Posto", "string"),
        _coluna("Turno", "string"), _coluna("PostoTurno", "string", oculta=True), _coluna("Origem", "string"),
        *[_coluna(c, "int64", fmt="#,0") for c in
          ("Itens", "Erros", "ItensSemErro", "SemLeitor", "CaixaErrada", "SemBipe", "BipeDuplo")]], m_turnos())
    arq[d + "tables/PostoTurno.tmdl"] = _tabela("PostoTurno", [
        _coluna("Posto", "string"), _coluna("Turno", "string"), _coluna("PostoTurno", "string", oculta=True, chave=True)],
        M_POSTO_TURNO)
    arq[d + "tables/Calendario.tmdl"] = _tabela("Calendario", [
        _coluna("Data", "dateTime", fmt="dd/mm/yyyy", data=True, chave=True), _coluna("Ano", "int64", fmt="0"),
        _coluna("AnoMesNumero", "int64", fmt="0", oculta=True), _coluna("Mes", "string", ordenar="AnoMesNumero"),
        _coluna("DiaSemanaNumero", "int64", fmt="0", oculta=True),
        _coluna("DiaSemana", "string", ordenar="DiaSemanaNumero"),
        _coluna("Semana", "dateTime", fmt="dd/mm/yyyy", data=True)], M_CALENDARIO, extra="\tdataCategory: Time")
    arq[d + "tables/Info.tmdl"] = _tabela("Info", [
        _coluna("Fonte", "string"), _coluna("Atualizado", "dateTime", fmt="dd/mm/yyyy hh:nn")], M_INFO)
    arq[d + "tables/Medidas.tmdl"] = _tabela("Medidas", [_coluna("Medidas", "string", oculta=True)], M_MEDIDAS,
                                             medidas=MEDIDAS)
    arq[d + "relationships.tmdl"] = "\n".join(
        f"relationship {de}_{cde}\n\tfromColumn: {de}.{cde}\n\ttoColumn: {para}.{cpara}\n"
        for de, cde, para, cpara in RELACOES)
    return arq


# =====================================================================================
# Relatório (PBIR)
# =====================================================================================
def _id(*partes):
    return hashlib.sha1("|".join(partes).encode()).hexdigest()[:20]


def _lit(v):
    if isinstance(v, bool):
        return {"expr": {"Literal": {"Value": "true" if v else "false"}}}
    if isinstance(v, (int, float)):
        return {"expr": {"Literal": {"Value": f"{v}D"}}}
    return {"expr": {"Literal": {"Value": "'" + str(v).replace("'", "''") + "'"}}}


def _campo(ref):
    """'Tabela[Coluna]' ou 'Medidas.Nome' -> (field, queryRef, nome)."""
    if "[" in ref:
        t, c = ref[:-1].split("[", 1)
        return {"Column": {"Expression": {"SourceRef": {"Entity": t}}, "Property": c}}, f"{t}.{c}", c
    t, c = ref.split(".", 1)
    return {"Measure": {"Expression": {"SourceRef": {"Entity": t}}, "Property": c}}, f"{t}.{c}", c


def _proj(ref, ativo=None, nome=None):
    f, q, n = _campo(ref)
    p = {"field": f, "queryRef": q, "nativeQueryRef": n}
    if ativo is not None:
        p["active"] = ativo
    if nome:
        p["displayName"] = nome
    return p


def visual(pagina, chave, tipo, x, y, w, h, papeis=None, titulo=None, ordem=None, objetos=None, z=0, sync=None):
    nome = _id(pagina, chave)
    v = {"visualType": tipo}
    if papeis:
        estado = {}
        for papel, refs in papeis.items():
            ativo = papel in ("Category", "Rows", "Columns") or (tipo == "slicer" and papel == "Values")
            estado[papel] = {"projections": [_proj(r, ativo=True if ativo and "[" in r else None) for r in refs]}
        v["query"] = {"queryState": estado}
        if ordem:
            ref, sentido = ordem
            v["query"]["sortDefinition"] = {"sort": [{"field": _campo(ref)[0], "direction": sentido}],
                                            "isDefaultSort": True}
    if objetos:
        v["objects"] = objetos
    vco = {}
    if titulo:
        vco["title"] = [{"properties": {"show": _lit(True), "text": _lit(titulo)}}]
    if vco:
        v["visualContainerObjects"] = vco
    if sync:
        v["syncGroup"] = {"groupName": sync, "fieldChanges": True, "filterChanges": True}
    return nome, {"$schema": SCHEMA + f"item/report/definition/visualContainer/{V['visualContainer']}/schema.json",
                  "name": nome, "position": {"x": x, "y": y, "z": z, "height": h, "width": w, "tabOrder": z},
                  "visual": v}


def texto(pagina, chave, x, y, w, h, linhas, z=0):
    paras = [{"textRuns": [{"value": t, "textStyle": {"fontFamily": "Segoe UI Semibold" if i == 0 else "Segoe UI",
                                                       "fontSize": tam, "color": cor}}]}
             for i, (t, tam, cor) in enumerate(linhas)]
    return visual(pagina, chave, "textbox", x, y, w, h, z=z,
                  objetos={"general": [{"properties": {"paragraphs": paras}}]})


def segmentacoes(pagina, z0):
    def seg(chave, ref, x, w, modo, sync):
        return visual(pagina, chave, "slicer", x, 8, w, 64, {"Values": [ref]}, z=z0 + x,
                      objetos={"data": [{"properties": {"mode": _lit(modo)}}]}, sync=sync)
    return [seg("seg_data", "Calendario[Data]", 660, 300, "Between", "Data"),
            seg("seg_posto", "PostoTurno[Posto]", 968, 148, "Dropdown", "Posto"),
            seg("seg_turno", "PostoTurno[Turno]", 1124, 140, "Dropdown", "Turno")]


def cartoes(pagina, medidas, y=88, h=92):
    n = len(medidas)
    w = (1248 - 8 * (n - 1)) / n
    return [visual(pagina, "kpi_" + m, "cardVisual", 16 + i * (w + 8), y, w, h, {"Data": ["Medidas." + m]},
                   z=100 + i) for i, m in enumerate(medidas)]


PAGINAS = [
    ("visao_geral", "Visão geral", lambda p: [
        texto(p, "titulo", 16, 6, 620, 46, [("ConfereVídeo · conferência da separação", "18pt", "#16202E"),
                                             ("Itens conferidos pela IA, erros e tratativas", "10pt", "#5B6678")]),
        visual(p, "fonte", "cardVisual", 16, 52, 620, 30, {"Data": ["Medidas.Fonte dos dados"]}, z=5),
        *segmentacoes(p, 10),
        *cartoes(p, ["Itens conferidos", "% itens sem erro", "Erros a cada mil itens", "Erros pendentes",
                     "% falso alarme", "Horas até a tratativa"]),
        visual(p, "linha_dia", "lineChart", 16, 188, 620, 256, {"Category": ["Calendario[Data]"],
               "Y": ["Medidas.Erros detectados"]}, titulo="Erros detectados por dia", z=200),
        visual(p, "barra_tipo", "clusteredBarChart", 644, 188, 620, 256, {"Category": ["Erros[Tipo]"],
               "Y": ["Medidas.Erros alertados"]}, titulo="Erros por tipo", ordem=("Medidas.Erros alertados", "Descending"),
               z=210),
        visual(p, "coluna_hora", "clusteredColumnChart", 16, 452, 620, 256, {"Category": ["Erros[Hora]"],
               "Y": ["Medidas.Erros alertados"]}, titulo="Erros por hora do dia", ordem=("Erros[Hora]", "Ascending"),
               z=220),
        visual(p, "coluna_posto", "clusteredColumnChart", 644, 452, 620, 256, {"Category": ["PostoTurno[Posto]"],
               "Y": ["Medidas.Erros a cada mil itens"]}, titulo="Erros a cada mil itens, por posto",
               ordem=("PostoTurno[Posto]", "Ascending"), z=230),
    ]),
    ("pessoas", "Pessoas e tratativas", lambda p: [
        texto(p, "titulo", 16, 6, 620, 46, [("Pessoas e tratativas", "18pt", "#16202E"),
                                             ("Quem errou, onde e o que já foi tratado", "10pt", "#5B6678")]),
        *segmentacoes(p, 10),
        *cartoes(p, ["Erros alertados", "Erros confirmados", "Erros pendentes", "Horas até a tratativa"]),
        visual(p, "barra_operador", "clusteredBarChart", 16, 188, 420, 520, {"Category": ["Erros[Operador]"],
               "Y": ["Medidas.Erros confirmados"]}, titulo="Erros confirmados por operador",
               ordem=("Medidas.Erros confirmados", "Descending"), z=200),
        visual(p, "matriz", "pivotTable", 444, 188, 820, 200, {"Rows": ["PostoTurno[Posto]", "PostoTurno[Turno]"],
               "Columns": ["Erros[Tipo]"], "Values": ["Medidas.Erros alertados"]},
               titulo="Erros por posto, turno e tipo", z=210),
        visual(p, "tabela", "tableEx", 444, 396, 820, 312, {"Values": [
            "Erros[DataHora]", "Erros[Posto]", "Erros[Turno]", "Erros[Tipo]", "Erros[Operador]", "Erros[Status]",
            "Erros[Tratativa]", "Erros[Confianca]", "Erros[LinkRecorte]"]},
               titulo="Erros (mais recentes primeiro)", ordem=("Erros[DataHora]", "Descending"), z=220),
    ]),
    ("qualidade_ia", "Qualidade da IA", lambda p: [
        texto(p, "titulo", 16, 6, 620, 46, [("Qualidade da IA", "18pt", "#16202E"),
                                             ("Cada alerta é conferido por uma pessoa: confirmado ou falso alarme",
                                              "10pt", "#5B6678")]),
        *segmentacoes(p, 10),
        *cartoes(p, ["Certeza média da IA", "% falso alarme", "Falsos alarmes", "Erros alertados"]),
        visual(p, "fa_faixa", "clusteredColumnChart", 16, 188, 620, 256, {"Category": ["Erros[Faixa de certeza]"],
               "Y": ["Medidas.% falso alarme"]}, titulo="% de falso alarme por faixa de certeza da IA",
               ordem=("Erros[Faixa de certeza]", "Ascending"), z=200),
        visual(p, "fa_tipo", "clusteredBarChart", 644, 188, 620, 256, {"Category": ["Erros[Tipo]"],
               "Y": ["Medidas.% falso alarme"]}, titulo="% de falso alarme por tipo de erro",
               ordem=("Medidas.% falso alarme", "Descending"), z=210),
        visual(p, "situacao", "donutChart", 16, 452, 620, 256, {"Category": ["Erros[Status]"],
               "Y": ["Medidas.Erros alertados"]}, titulo="Situação dos erros", z=220),
        visual(p, "origem_op", "clusteredBarChart", 644, 452, 620, 256, {"Category": ["Erros[OperadorOrigem]"],
               "Y": ["Medidas.Erros alertados"]}, titulo="Operador identificado por (sem reconhecimento facial)",
               ordem=("Medidas.Erros alertados", "Descending"), z=230),
    ]),
]

TEMA = {
    "name": "ConfereVideo",
    # paleta categórica validada para daltonismo (ordem fixa) e cores de status reservadas
    "dataColors": ["#2A78D6", "#EB6834", "#1BAF7A", "#EDA100", "#E87BA4", "#008300", "#6250D6", "#E34948"],
    "foreground": "#16202E", "background": "#FFFFFF", "tableAccent": "#2A78D6",
    "good": "#0CA30C", "neutral": "#FAB219", "bad": "#D03B3B",
}


def arquivos_relatorio():
    """{caminho relativo: texto} da pasta ConfereVideo.Report (menos o tema base, que é copiado)."""
    d = "definition/"
    arq = {
        "definition.pbir": json.dumps({
            "$schema": SCHEMA + "item/report/definitionProperties/2.0.0/schema.json", "version": "4.0",
            "datasetReference": {"byPath": {"path": f"../{NOME}.SemanticModel"}}}, indent=2),
        d + "version.json": json.dumps({
            "$schema": SCHEMA + f"item/report/definition/versionMetadata/{V['versionMetadata']}/schema.json",
            "version": "2.0.0"}, indent=2),
        d + "report.json": json.dumps({
            "$schema": SCHEMA + f"item/report/definition/report/{V['report']}/schema.json",
            "themeCollection": {
                "baseTheme": {"name": TEMA_BASE, "reportVersionAtImport": VERSAO_IMPORT, "type": "SharedResources"},
                "customTheme": {"name": "ConfereVideo.json", "reportVersionAtImport": VERSAO_IMPORT,
                                "type": "RegisteredResources"}},
            "resourcePackages": [
                {"name": "SharedResources", "type": "SharedResources",
                 "items": [{"name": TEMA_BASE, "path": f"BaseThemes/{TEMA_BASE}.json", "type": "BaseTheme"}]},
                {"name": "RegisteredResources", "type": "RegisteredResources",
                 "items": [{"name": "ConfereVideo.json", "path": "ConfereVideo.json", "type": "CustomTheme"}]}],
            "settings": {"useStylableVisualContainerHeader": True, "defaultFilterActionIsDataFilter": True,
                         "useEnhancedTooltips": True}}, indent=2, ensure_ascii=False),
        "StaticResources/RegisteredResources/ConfereVideo.json": json.dumps(TEMA, indent=2),
    }
    ordem = []
    for chave, titulo, montar in PAGINAS:
        pid = _id("pagina", chave)
        ordem.append(pid)
        base = f"{d}pages/{pid}/"
        arq[base + "page.json"] = json.dumps({
            "$schema": SCHEMA + f"item/report/definition/page/{V['page']}/schema.json",
            "name": pid, "displayName": titulo, "displayOption": "FitToPage", "height": 720, "width": 1280},
            indent=2, ensure_ascii=False)
        for nome, vis in montar(chave):
            arq[f"{base}visuals/{nome}/visual.json"] = json.dumps(vis, indent=2, ensure_ascii=False)
    arq[d + "pages/pages.json"] = json.dumps({
        "$schema": SCHEMA + f"item/report/definition/pagesMetadata/{V['pagesMetadata']}/schema.json",
        "pageOrder": ordem, "activePageName": ordem[0]}, indent=2)
    return arq


def arquivos_projeto(**kw):
    arq = {f"{NOME}.pbip": json.dumps({
        "$schema": SCHEMA + "pbip/pbipProperties/1.0.0/schema.json", "version": "1.0",
        "artifacts": [{"report": {"path": f"{NOME}.Report"}}], "settings": {"enableAutoRecovery": True}}, indent=2),
        ".gitignore": "**/.pbi/localSettings.json\n**/.pbi/cache.abf\n"}
    arq.update({f"{NOME}.SemanticModel/{k}": v for k, v in arquivos_modelo(**kw).items()})
    arq.update({f"{NOME}.Report/{k}": v for k, v in arquivos_relatorio().items()})
    return arq


def gravar(destino, **kw):
    """Grava o projeto em destino (apaga páginas e tabelas antigas geradas antes; mantém o tema base)."""
    destino = Path(destino)
    tema_base = MODELO / f"{NOME}.Report/StaticResources/SharedResources/BaseThemes/{TEMA_BASE}.json"
    for velho in (destino / f"{NOME}.Report/definition", destino / f"{NOME}.SemanticModel/definition"):
        if velho.exists():
            shutil.rmtree(velho)
    for rel, txt in arquivos_projeto(**kw).items():
        p = destino / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(txt if txt.endswith("\n") else txt + "\n", encoding="utf-8", newline="\n")
    alvo = destino / tema_base.relative_to(MODELO)
    if tema_base.exists() and tema_base.resolve() != alvo.resolve():
        alvo.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(tema_base, alvo)
    return destino / f"{NOME}.pbip"


def gerar_painel(m, pasta):
    """Painel pronto para o site configurado na tela Microsoft 365 (m = cfg['m365'])."""
    site = (m.get("site_sharepoint") or "").strip().rstrip("/") or "exemplo"
    return gravar(Path(pasta), site=site, lista_erros=m.get("lista_erros") or "ConfereVideo_Erros",
                  lista_turnos=m.get("lista_sessoes") or "ConfereVideo_Turnos",
                  incluir_demo=bool(m.get("enviar_demonstracao")))


if __name__ == "__main__":
    args = sys.argv[1:]
    site = "exemplo"
    if "--site" in args:
        i = args.index("--site")
        site = args[i + 1]
        del args[i:i + 2]
    pbip = gravar(Path(args[0]) if args else MODELO, site=site)
    print(pbip)
    print(json.dumps(indicadores(*dados_exemplo()), ensure_ascii=False, indent=1))
