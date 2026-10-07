"""
ConfereVídeo · pacotes do Power Automate
========================================
Gera os fluxos como pacotes .zip para "Importar pacote (Herdado)" no Power Automate,
já preenchidos com o site do SharePoint, as listas e os e-mails das Configurações.

  1_Criar_listas.zip        botão: cria as duas listas no SharePoint (rodar uma vez)
  2_Receber_eventos.zip     recebe os envios do programa: lista + anexos + Teams + e-mail
  3_Cobranca_diaria.zip     todo dia 07:00: erros sem tratativa -> e-mail e Teams
  4_Resumo_semanal.zip      segunda 07:30: indicadores da semana -> e-mail do gestor

Só usa conectores padrão (SharePoint, Teams, Outlook). O gatilho do fluxo 2 vem como
"Quando uma solicitação HTTP for recebida"; sem licença Premium, troque-o por
"Quando uma solicitação de webhook do Teams for recebida" (o resto do fluxo não muda).
"""
from __future__ import annotations

import json
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from integracao import LINK_RECORTE, PADRAO_M365, lista_emails

FUSO = "E. South America Standard Time"  # horário de Brasília
CON = {
    "sp": ("shared_sharepointonline", "SharePoint",
           "https://connectoricons-prod.azureedge.net/releases/v1.0.1550/1.0.1550.2686/sharepointonline/icon.png"),
    "teams": ("shared_teams", "Microsoft Teams",
              "https://connectoricons-prod.azureedge.net/releases/v1.0.1549/1.0.1549.2681/teams/icon.png"),
    "o365": ("shared_office365", "Office 365 Outlook",
             "https://connectoricons-prod.azureedge.net/releases/v1.0.1538/1.0.1538.2621/office365/icon.png"),
}
JSON_NOMETA = {"Accept": "application/json;odata=nometadata", "Content-Type": "application/json;odata=nometadata"}
JSON_VERBOSE = {"Accept": "application/json;odata=verbose", "Content-Type": "application/json;odata=verbose"}

# ---------------------------------------------------------------- colunas das listas
CAMPOS_ERROS = [
    ("TipoCodigo", "Text"), ("Tipo", "Text"), ("DataHora", "DateTime"), ("Unidade", "Text"), ("Local", "Text"),
    ("Posto", "Text"), ("Turno", "Text"), ("Origem", "Text"), ("Fonte", "Text"), ("Sessao", "Text"),
    ("Bipes", "Number"), ("MomentoVideo", "Text"), ("Status", "Text:Pendente"), ("Tratativa", "Text"),
    ("Operador", "Text"), ("Observacao", "Note"), ("TratadoPor", "Text"), ("TratadoEm", "DateTime"),
    ("LinkRecorte", "Note"), ("Miniatura", "Note"),
]
CAMPOS_TURNOS = [
    ("Inicio", "DateTime"), ("Fim", "DateTime"), ("Unidade", "Text"), ("Local", "Text"), ("Posto", "Text"),
    ("Turno", "Text"), ("Origem", "Text"), ("Itens", "Number"), ("Erros", "Number"), ("ItensSemErro", "Number"),
    ("PctSemErro", "Number:1"), ("SemLeitor", "Number"), ("CaixaErrada", "Number"), ("SemBipe", "Number"),
    ("BipeDuplo", "Number"),
]
INDICES = {"erros": ["Status", "DataHora", "Posto"], "turnos": ["Inicio", "Posto"]}


def schema_xml(nome, tipo):
    """XML de criação de coluna do SharePoint (nome interno = nome exibido, sem acento)."""
    base = f"Name='{nome}' StaticName='{nome}' DisplayName='{nome}'"
    if tipo.startswith("Text"):
        padrao = tipo.split(":", 1)[1] if ":" in tipo else ""
        return (f"<Field Type='Text' {base} MaxLength='255'>" + (f"<Default>{padrao}</Default>" if padrao else "")
                + "</Field>")
    if tipo == "Note":
        return f"<Field Type='Note' {base} NumLines='4' RichText='FALSE' />"
    if tipo == "DateTime":
        return f"<Field Type='DateTime' {base} Format='DateTime' />"
    if tipo.startswith("Number"):
        dec = tipo.split(":", 1)[1] if ":" in tipo else "0"
        return f"<Field Type='Number' {base} Decimals='{dec}' />"
    raise ValueError(tipo)


# ---------------------------------------------------------------- blocos de definição
def acao(conector, operacao, parametros, apos=None, descricao=None):
    nome = CON[conector][0]
    a = {"runAfter": apos or {}, "type": "OpenApiConnection",
         "inputs": {"host": {"apiId": f"/providers/Microsoft.PowerApps/apis/{nome}", "connectionName": nome,
                             "operationId": operacao},
                    "parameters": parametros, "authentication": "@parameters('$authentication')"}}
    if descricao:
        a["description"] = descricao
    return a


def sp_http(site, metodo, uri, corpo=None, cab=None, apos=None, descricao=None):
    p = {"dataset": site, "parameters/method": metodo, "parameters/uri": uri,
         "parameters/headers": cab or JSON_NOMETA}
    if corpo is not None:
        p["parameters/body"] = corpo
    return acao("sp", "HttpRequest", p, apos, descricao)


def depois(*nomes, tambem_falha=False):
    st = ["Succeeded", "Failed", "Skipped", "TimedOut"] if tambem_falha else ["Succeeded"]
    return {n: st for n in nomes}


def se(expr, sim, nao=None, apos=None, descricao=None):
    d = {"type": "If", "expression": expr, "actions": sim, "else": {"actions": nao or {}}, "runAfter": apos or {}}
    if descricao:
        d["description"] = descricao
    return d


def compor(valor, apos=None, descricao=None):
    d = {"type": "Compose", "inputs": valor, "runAfter": apos or {}}
    if descricao:
        d["description"] = descricao
    return d


def cada(origem, acoes, apos=None, sequencial=True):
    d = {"type": "Foreach", "foreach": origem, "actions": acoes, "runAfter": apos or {}}
    if sequencial:
        d["runtimeConfiguration"] = {"concurrency": {"repetitions": 1}}
    return d


def cartao_teams(local, mensagem, destino_expr=None, grupo=None, canal=None, apos=None):
    p = {"poster": "Flow bot", "body/messageBody": mensagem}
    if local == "canal":
        p.update({"location": "Channel", "body/recipient/groupId": grupo, "body/recipient/channelId": canal})
    else:
        p.update({"location": "Chat with Flow bot", "body/recipient": destino_expr})
    return acao("teams", "PostCardToConversation", p, apos)


def email(para, assunto, corpo, anexos=None, apos=None):
    p = {"emailMessage/To": para, "emailMessage/Subject": assunto, "emailMessage/Body": corpo,
         "emailMessage/Importance": "Normal"}
    if anexos is not None:
        p["emailMessage/Attachments"] = anexos
    return acao("o365", "SendEmailV2", p, apos)


def definicao(gatilho, acoes):
    return {"$schema": "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#",
            "contentVersion": "1.0.0.0",
            "parameters": {"$connections": {"defaultValue": {}, "type": "Object"},
                           "$authentication": {"defaultValue": {}, "type": "SecureObject"}},
            "triggers": gatilho, "actions": acoes}


# ---------------------------------------------------------------- fluxo 2: receber eventos
D = "outputs('Dados')"


def fluxo_receber_eventos(m):
    chave = (m.get("chave") or "").replace("'", "''")
    gatilho = {"manual": {"type": "Request", "kind": "Http", "inputs": {"schema": {
        "type": "object", "properties": {"type": {"type": "string"}, "attachments": {"type": "array"},
                                         "conferevideo": {"type": "object"}}}},
        "description": "Sem licença Premium: apague este gatilho e use 'Quando uma solicitação de webhook do Teams "
                       "for recebida' (Microsoft Teams), com 'Quem pode disparar o fluxo' = Qualquer pessoa."}}
    lista = f"{D}?['lista']"
    site = f"@{D}?['site']"
    anexar = lambda nome_loop, item_id: {  # noqa: E731
        "Anexar_arquivo" + ("" if nome_loop.endswith("erro") else "_turno"): acao("sp", "CreateAttachment", {
            "dataset": site, "table": f"@{lista}", "itemId": item_id,
            "displayName": f"@items('{nome_loop}')?['nome']",
            "body": f"@base64ToBinary(items('{nome_loop}')?['b64'])"})}
    loop_erro = anexar("Anexar_arquivos_do_erro", "@body('Criar_item_do_erro')?['Id']")
    loop_erro["Guardar_link_do_recorte"] = se(
        {"and": [{"endsWith": ["@items('Anexar_arquivos_do_erro')?['nome']", "_recorte.mp4"]}]},
        {"Link_do_recorte_recebido": {"type": "SetVariable", "runAfter": {},
                                      "inputs": {"name": "LinkRecorte", "value": "@body('Anexar_arquivo')?['AbsoluteUri']"}}},
        apos=depois("Anexar_arquivo"))
    caso_erro = {
        "Criar_item_do_erro": sp_http(site, "POST", f"_api/web/lists/getbytitle('@{{{lista}}}')/items",
                                      f"@{{string({D}?['item'])}}",
                                      descricao="Cria o item na lista de erros com os dados que o programa mandou."),
        "Anexar_arquivos_do_erro": cada(f"@coalesce({D}?['anexos'], json('[]'))", loop_erro,
                                        depois("Criar_item_do_erro")),
        "Gravar_link_do_recorte": se(
            {"and": [{"not": {"equals": ["@variables('LinkRecorte')", ""]}}]},
            {"Atualizar_item_do_erro": sp_http(
                site, "POST", f"_api/web/lists/getbytitle('@{{{lista}}}')/items(@{{body('Criar_item_do_erro')?['Id']}})",
                "{\"LinkRecorte\": \"@{variables('LinkRecorte')}\"}",
                dict(JSON_NOMETA, **{"IF-MATCH": "*", "X-HTTP-Method": "MERGE"}))},
            apos=depois("Anexar_arquivos_do_erro")),
    }
    caso_sessao = {
        "Criar_item_do_turno": sp_http(site, "POST", f"_api/web/lists/getbytitle('@{{{lista}}}')/items",
                                       f"@{{string({D}?['item'])}}",
                                       descricao="Cria o item na lista de turnos (indicadores do turno)."),
        "Anexar_arquivos_do_turno": cada(f"@coalesce({D}?['anexos'], json('[]'))",
                                         anexar("Anexar_arquivos_do_turno", "@body('Criar_item_do_turno')?['Id']"),
                                         depois("Criar_item_do_turno")),
    }
    link_fallback = f"concat({D}?['site'], '/Lists/', {lista})"
    cartao_expr = (f"@replace(string(triggerBody()?['attachments']?[0]?['content']), '{LINK_RECORTE}', "
                   f"if(empty(variables('LinkRecorte')), {link_fallback}, variables('LinkRecorte')))")
    acoes = {
        "Dados": compor("@triggerBody()?['conferevideo']",
                        descricao="Dados enviados pelo ConfereVídeo (evento, item da lista, anexos, Teams e e-mail)."),
        "Conferir_chave": se(
            {"and": [{"equals": [f"@{D}?['chave']", chave]}]}, {},
            {"Recusar_envio": {"type": "Terminate", "runAfter": {},
                               "inputs": {"runStatus": "Cancelled"}}},
            depois("Dados"), "Só aceita envios com a chave de segurança configurada no programa."),
        "Variavel_link_do_recorte": {"type": "InitializeVariable", "runAfter": depois("Conferir_chave"),
                                     "inputs": {"variables": [{"name": "LinkRecorte", "type": "string", "value": ""}]}},
        "Tipo_de_evento": {"type": "Switch", "expression": f"@{D}?['evento']", "runAfter": depois("Variavel_link_do_recorte"),
                           "cases": {"Erro": {"case": "erro", "actions": caso_erro},
                                     "Fim_de_turno": {"case": "sessao", "actions": caso_sessao}},
                           "default": {"actions": {}}},
        "Mandar_email": se(
            {"and": [{"not": {"equals": [f"@coalesce({D}?['email']?['para'], '')", ""]}}]},
            {"Arquivos_do_email": {"type": "Select", "runAfter": {},
                                   "inputs": {"from": f"@if(equals({D}?['evento'], 'sessao'), coalesce({D}?['anexos'], json('[]')), json('[]'))",
                                              "select": {"Name": "@item()?['nome']", "ContentBytes": "@item()?['b64']"}}},
             "Enviar_email": email(f"@{D}?['email']?['para']", f"@{D}?['email']?['assunto']",
                                   f"@{D}?['email']?['html']", "@body('Arquivos_do_email')",
                                   depois("Arquivos_do_email"))},
            apos=depois("Tipo_de_evento", tambem_falha=True)),
        "Avisar_no_Teams": se(
            {"and": [{"equals": [f"@coalesce({D}?['notificar'], true)", True]},
                     {"greater": ["@length(coalesce(triggerBody()?['attachments'], json('[]')))", 0]}]},
            {"Cartao": compor(cartao_expr, descricao="Cartão montado pelo programa, com o link do recorte anexado."),
             "No_canal_ou_no_chat": se(
                 {"and": [{"not": {"equals": [f"@coalesce({D}?['teams']?['grupo'], '')", ""]}}]},
                 {"Postar_no_canal": cartao_teams("canal", "@{outputs('Cartao')}",
                                                  grupo=f"@{D}?['teams']?['grupo']", canal=f"@{D}?['teams']?['canal']")},
                 {"Tem_destinatarios": se(
                     {"and": [{"not": {"equals": [f"@coalesce({D}?['teams']?['destinatarios'], '')", ""]}}]},
                     {"Postar_no_chat": cartao_teams("chat", "@{outputs('Cartao')}",
                                                     destino_expr=f"@{D}?['teams']?['destinatarios']")})},
                 apos=depois("Cartao"))},
            apos=depois("Mandar_email", tambem_falha=True)),
        "Marcar_falha": {"type": "Terminate",
                         "runAfter": {"Avisar_no_Teams": ["Succeeded", "Failed", "Skipped", "TimedOut"],
                                      "Tipo_de_evento": ["Failed", "TimedOut"]},
                         "inputs": {"runStatus": "Failed", "runError": {
                             "code": "ListaSharePoint",
                             "message": "Não consegui gravar na lista do SharePoint. Veja a etapa em vermelho dentro de Tipo_de_evento."}},
                         "description": "Só roda se a gravação na lista falhou: deixa a execução marcada como Falha."},
    }
    return definicao(gatilho, acoes), ["sp", "teams", "o365"]


# ---------------------------------------------------------------- fluxo 1: criar listas
def fluxo_criar_listas(m):
    site = m["site_sharepoint"].rstrip("/")
    le, lt = m.get("lista_erros") or PADRAO_M365["lista_erros"], m.get("lista_sessoes") or PADRAO_M365["lista_sessoes"]
    gatilho = {"manual": {"type": "Request", "kind": "Button",
                          "inputs": {"schema": {"type": "object", "properties": {}, "required": []}}}}
    acoes, ant = {}, None
    for chave, lista, campos, desc in (("Erros", le, CAMPOS_ERROS, "Erros detectados pelo ConfereVídeo"),
                                       ("Turnos", lt, CAMPOS_TURNOS, "Resumo de cada turno do ConfereVídeo")):
        lista_q = lista.replace("'", "''")
        criar = f"Criar_lista_{chave}"
        acoes[criar] = sp_http(site, "POST", "_api/web/lists",
                               json.dumps({"__metadata": {"type": "SP.List"}, "BaseTemplate": 100, "Title": lista,
                                           "Description": desc, "AllowContentTypes": True}, ensure_ascii=False),
                               JSON_VERBOSE, depois(ant, tambem_falha=True) if ant else {},
                               "Se a lista já existir, esta etapa dá erro e o fluxo segue normalmente.")
        acoes[f"Colunas_{chave}"] = compor([schema_xml(n, t) for n, t in campos], depois(criar, tambem_falha=True))
        acoes[f"Criar_colunas_{chave}"] = cada(f"@outputs('Colunas_{chave}')", {
            f"Criar_coluna_{chave}": sp_http(
                site, "POST", f"_api/web/lists/getbytitle('{lista_q}')/fields/createfieldasxml",
                "{\"parameters\": {\"__metadata\": {\"type\": \"SP.XmlSchemaFieldCreationInformation\"}, "
                "\"SchemaXml\": \"@{item()}\", \"Options\": 24}}", JSON_VERBOSE)},
            depois(f"Colunas_{chave}"))
        indices = INDICES["erros" if chave == "Erros" else "turnos"]
        acoes[f"Indexar_{chave}"] = cada("@createArray(" + ", ".join(f"'{c}'" for c in indices) + ")", {
            f"Indexar_coluna_{chave}": sp_http(
                site, "POST", f"_api/web/lists/getbytitle('{lista_q}')/fields/getbyinternalnameortitle('@{{item()}}')",
                "{\"__metadata\": {\"type\": \"SP.Field\"}, \"Indexed\": true}",
                dict(JSON_VERBOSE, **{"IF-MATCH": "*", "X-HTTP-Method": "MERGE"}))},
            depois(f"Criar_colunas_{chave}", tambem_falha=True))
        ant = f"Indexar_{chave}"
    acoes["Pronto"] = compor(f"Listas '{le}' e '{lt}' prontas em {site}", depois(ant, tambem_falha=True))
    return definicao(gatilho, acoes), ["sp"]


# ---------------------------------------------------------------- fluxo 3: cobrança diária
def _estilizar_tabela(expr):
    return (f"replace(replace(replace({expr}, '<table>', '<table style=\"border-collapse:collapse;width:100%;font:14px Segoe UI,Arial,sans-serif\">'), "
            f"'<th>', '<th style=\"text-align:left;padding:6px 10px;border-bottom:2px solid #16202e;color:#5b6678;font-size:12px;text-transform:uppercase\">'), "
            f"'<td>', '<td style=\"padding:6px 10px;border-bottom:1px solid #e3e7ee\">')")


def _casca_email(titulo, miolo, link_app):
    botao = (f'<p style="margin:20px 0 0"><a href="{link_app}" style="background:#0f4c81;color:#fff;padding:10px 18px;'
             f'text-decoration:none;font:bold 14px Segoe UI,Arial,sans-serif">Abrir o app de tratativa</a></p>') if link_app else ""
    return (f'<div style="font:14px Segoe UI,Arial,sans-serif;color:#16202e;max-width:680px">'
            f'<div style="background:#16202e;color:#fff;padding:16px 20px"><div style="font-size:12px;color:#9fb3cc;'
            f'letter-spacing:.1em">CONFEREVÍDEO</div><div style="font-size:20px;font-weight:bold">{titulo}</div></div>'
            f'<div style="padding:16px 20px;border:1px solid #e3e7ee;border-top:0">{miolo}{botao}'
            f'<p style="color:#5b6678;font-size:12px;margin-top:18px">Enviado automaticamente pelo Power Automate. '
            f'Detecção automática por vídeo: confirme cada recorte antes de qualquer tratativa.</p></div></div>')


def fluxo_cobranca(m):
    site = m["site_sharepoint"].rstrip("/")
    lista = m.get("lista_erros") or PADRAO_M365["lista_erros"]
    para = lista_emails(m.get("emails_supervisores")) or lista_emails(m.get("emails_gestor"))
    link = m.get("link_app", "") if str(m.get("link_app", "")).startswith("https://") else ""
    gatilho = {"Todo_dia_7h": {"type": "Recurrence", "recurrence": {
        "frequency": "Day", "interval": 1, "timeZone": FUSO, "schedule": {"hours": ["7"], "minutes": [0]}}}}
    qtd = "length(outputs('Erros_pendentes')?['body/value'])"
    tabela = _estilizar_tabela("body('Tabela_pendentes')")
    miolo = (f"<p>Há <b>@{{{qtd}}}</b> erro(s) do ConfereVídeo aguardando tratativa (confirmar ou marcar falso alarme).</p>"
             f"@{{{tabela}}}")
    cartao = {"type": "AdaptiveCard", "$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "version": "1.4",
              "body": [{"type": "Container", "style": "warning", "bleed": True, "items": [
                  {"type": "TextBlock", "text": "CONFEREVÍDEO · COBRANÇA DIÁRIA", "size": "Small", "weight": "Bolder"},
                  {"type": "TextBlock", "text": f"@{{{qtd}}} erro(s) aguardando tratativa", "size": "Large",
                   "weight": "Bolder", "wrap": True}]},
                  {"type": "TextBlock", "wrap": True,
                   "text": "Abra o app, assista ao recorte e marque se o erro foi confirmado ou se foi falso alarme."}],
              "actions": [{"type": "Action.OpenUrl", "title": "Fazer a tratativa", "url": link}] if link else []}
    sim = {
        "Linhas": {"type": "Select", "runAfter": {}, "inputs": {
            "from": "@outputs('Erros_pendentes')?['body/value']",
            "select": {"Quando": f"@formatDateTime(convertFromUtc(item()?['DataHora'], '{FUSO}'), 'dd/MM HH:mm')",
                       "Posto": "@item()?['Posto']", "Turno": "@item()?['Turno']", "Erro": "@item()?['Tipo']",
                       "Dias sem tratativa": "@div(sub(ticks(utcNow()), ticks(item()?['DataHora'])), 864000000000)"}}},
        "Tabela_pendentes": {"type": "Table", "runAfter": depois("Linhas"),
                             "inputs": {"from": "@body('Linhas')", "format": "HTML"}},
        "Email_cobranca": email(para, f"ConfereVídeo · @{{{qtd}}} erro(s) aguardando tratativa",
                                _casca_email("Erros aguardando tratativa", miolo, link), apos=depois("Tabela_pendentes")),
        "Teams_cobranca": cartao_teams("chat", json.dumps(cartao, ensure_ascii=False), destino_expr=para,
                                       apos=depois("Tabela_pendentes")),
    }
    acoes = {
        "Erros_pendentes": acao("sp", "GetItems", {
            "dataset": site, "table": lista, "$filter": "Status eq 'Pendente' and Origem ne 'Demonstração'",
            "$orderby": "DataHora asc", "$top": 500}),
        "Tem_pendentes": se({"and": [{"greater": [f"@{qtd}", 0]}]}, sim, apos=depois("Erros_pendentes")),
    }
    return definicao(gatilho, acoes), ["sp", "teams", "o365"]


# ---------------------------------------------------------------- fluxo 4: resumo semanal
def fluxo_semanal(m):
    site = m["site_sharepoint"].rstrip("/")
    le, lt = m.get("lista_erros") or PADRAO_M365["lista_erros"], m.get("lista_sessoes") or PADRAO_M365["lista_sessoes"]
    para = lista_emails(m.get("emails_gestor")) or lista_emails(m.get("emails_supervisores"))
    link = m.get("link_app", "") if str(m.get("link_app", "")).startswith("https://") else ""
    gatilho = {"Segunda_7h30": {"type": "Recurrence", "recurrence": {
        "frequency": "Week", "interval": 1, "timeZone": FUSO,
        "schedule": {"weekDays": ["Monday"], "hours": ["7"], "minutes": [30]}}}}
    desde = "@{addDays(utcNow(), -7, 'yyyy-MM-ddTHH:mm:ssZ')}"
    erros = "outputs('Erros_da_semana')?['body/value']"
    filtros = {"Confirmados": "equals(item()?['Status'], 'Confirmado')",
               "Falsos_alarmes": "equals(item()?['Status'], 'Falso alarme')",
               "Pendentes": "equals(item()?['Status'], 'Pendente')",
               "Sem_leitor": "equals(item()?['TipoCodigo'], 'sem_leitor')",
               "Outra_caixa": "equals(item()?['TipoCodigo'], 'caixa_errada')",
               "Sem_bipe": "equals(item()?['TipoCodigo'], 'sem_bipe')",
               "Bipe_duplo": "equals(item()?['TipoCodigo'], 'bipe_duplo')"}
    acoes = {
        "Erros_da_semana": acao("sp", "GetItems", {
            "dataset": site, "table": le, "$filter": f"DataHora ge '{desde}' and Origem ne 'Demonstração'",
            "$top": 5000}),
        "Turnos_da_semana": acao("sp", "GetItems", {
            "dataset": site, "table": lt, "$filter": f"Inicio ge '{desde}' and Origem ne 'Demonstração'",
            "$top": 5000}, depois("Erros_da_semana")),
        "Itens_conferidos": {"type": "InitializeVariable", "runAfter": depois("Turnos_da_semana"),
                             "inputs": {"variables": [{"name": "Itens", "type": "integer", "value": 0}]}},
        "Erros_nos_turnos": {"type": "InitializeVariable", "runAfter": depois("Itens_conferidos"),
                             "inputs": {"variables": [{"name": "ErrosTurnos", "type": "integer", "value": 0}]}},
        "Somar_turnos": cada("@outputs('Turnos_da_semana')?['body/value']", {
            "Somar_itens": {"type": "IncrementVariable", "runAfter": {},
                            "inputs": {"name": "Itens", "value": "@int(coalesce(items('Somar_turnos')?['Itens'], 0))"}},
            "Somar_erros": {"type": "IncrementVariable", "runAfter": depois("Somar_itens"),
                            "inputs": {"name": "ErrosTurnos", "value": "@int(coalesce(items('Somar_turnos')?['Erros'], 0))"}}},
            depois("Erros_nos_turnos")),
    }
    ant = "Somar_turnos"
    for nome, cond in filtros.items():
        acoes[nome] = {"type": "Query", "runAfter": depois(ant), "inputs": {"from": f"@{erros}", "where": f"@{cond}"}}
        ant = nome
    n = lambda a: f"@{{length(body('{a}'))}}"  # noqa: E731
    pct = ("@{if(greater(variables('Itens'), 0), formatNumber(mul(div(float(sub(variables('Itens'), "
           "variables('ErrosTurnos'))), float(variables('Itens'))), 100), '0.0', 'pt-BR'), '—')}")

    def kpi(v, rot, cor="#16202e"):
        return (f'<td style="padding:12px;border:1px solid #e3e7ee;width:25%"><div style="font-size:26px;'
                f'font-weight:bold;color:{cor}">{v}</div><div style="font-size:12px;color:#5b6678">{rot}</div></td>')
    linha = lambda rot, a: f'<tr><td style="padding:6px 10px;border-bottom:1px solid #e3e7ee">{rot}</td><td style="padding:6px 10px;border-bottom:1px solid #e3e7ee;text-align:right;font-weight:bold">{n(a)}</td></tr>'  # noqa: E731
    miolo = (f'<p>Últimos 7 dias (todos os postos).</p><table style="border-collapse:collapse;width:100%"><tr>'
             f'{kpi("@{variables(" + chr(39) + "Itens" + chr(39) + ")}", "itens conferidos")}'
             f'{kpi("@{length(" + erros + ")}", "erros detectados", "#b91c1c")}'
             f'{kpi(pct + "%", "itens sem erro", "#15803d")}{kpi(n("Pendentes"), "aguardando tratativa", "#c2410c")}</tr></table>'
             f'<h3 style="font-size:13px;color:#5b6678;text-transform:uppercase;margin:20px 0 6px">Erros por tipo</h3>'
             f'<table style="border-collapse:collapse;width:100%">{linha("Colocou na caixa sem passar no leitor", "Sem_leitor")}'
             f'{linha("Colocou em outra caixa", "Outra_caixa")}{linha("Passou no leitor, mas não bipou", "Sem_bipe")}'
             f'{linha("Bipe duplo para um item", "Bipe_duplo")}</table>'
             f'<h3 style="font-size:13px;color:#5b6678;text-transform:uppercase;margin:20px 0 6px">Tratativas</h3>'
             f'<table style="border-collapse:collapse;width:100%">{linha("Erros confirmados", "Confirmados")}'
             f'{linha("Falsos alarmes", "Falsos_alarmes")}{linha("Ainda sem tratativa", "Pendentes")}</table>')
    acoes["Email_semanal"] = email(para, "ConfereVídeo · resumo da semana", _casca_email("Resumo da semana", miolo, link),
                                   apos=depois(ant))
    return definicao(gatilho, acoes), ["sp", "o365"]


# ---------------------------------------------------------------- pacote .zip (Importar pacote (Herdado))
def pacote(definicao_fluxo, nome, conectores, saida):
    fid, rid = str(uuid.uuid4()), str(uuid.uuid4())
    recursos = {rid: {"type": "Microsoft.Flow/flows", "suggestedCreationType": "New", "creationType": "Existing, New, Update",
                      "details": {"displayName": nome}, "configurableBy": "User", "hierarchy": "Root", "dependsOn": []}}
    apis_map, cons_map, refs = {}, {}, {}
    for c in conectores:
        api, disp, icone = CON[c]
        a_id, c_id = str(uuid.uuid4()), str(uuid.uuid4())
        recursos[a_id] = {"id": f"/providers/Microsoft.PowerApps/apis/{api}", "name": api,
                          "type": "Microsoft.PowerApps/apis", "suggestedCreationType": "Existing",
                          "details": {"displayName": disp, "iconUri": icone}, "configurableBy": "System",
                          "hierarchy": "Child", "dependsOn": []}
        recursos[c_id] = {"type": "Microsoft.PowerApps/apis/connections", "suggestedCreationType": "Existing",
                          "creationType": "Existing", "details": {"displayName": disp, "iconUri": icone},
                          "configurableBy": "User", "hierarchy": "Child", "dependsOn": [a_id]}
        recursos[rid]["dependsOn"] += [a_id, c_id]
        apis_map[api], cons_map[api] = a_id, c_id
        refs[api] = {"connectionName": f"{api.replace('shared_', 'shared-')}-{uuid.uuid4()}", "source": "Embedded",
                     "id": f"/providers/Microsoft.PowerApps/apis/{api}", "tier": "NotSpecified"}
    manifesto = {"schema": "1.0", "details": {
        "displayName": nome, "description": "ConfereVídeo · conferência da separação por vídeo",
        "createdTime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.0000000Z"),
        "packageTelemetryId": str(uuid.uuid4()), "creator": "ConfereVídeo", "sourceEnvironment": ""},
        "resources": recursos}
    fluxo = {"name": fid, "id": f"/providers/Microsoft.Flow/flows/{fid}", "type": "Microsoft.Flow/flows",
             "properties": {"apiId": "/providers/Microsoft.PowerApps/apis/shared_logicflows", "displayName": nome,
                            "definition": definicao_fluxo, "connectionReferences": refs,
                            "flowFailureAlertSubscribed": False}}
    saida = Path(saida)
    saida.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifesto, ensure_ascii=False, indent=1))
        z.writestr("Microsoft.Flow/flows/manifest.json",
                   json.dumps({"packageSchemaVersion": "1.0", "flowAssets": {"assetPaths": [rid]}}))
        base = f"Microsoft.Flow/flows/{rid}/"
        z.writestr(base + "definition.json", json.dumps(fluxo, ensure_ascii=False, indent=1))
        z.writestr(base + "apisMap.json", json.dumps(apis_map))
        z.writestr(base + "connectionsMap.json", json.dumps(cons_map))
    return saida


FLUXOS = [
    ("1_Criar_listas", "ConfereVídeo · 1 Criar listas", fluxo_criar_listas),
    ("2_Receber_eventos", "ConfereVídeo · 2 Receber eventos", fluxo_receber_eventos),
    ("3_Cobranca_diaria", "ConfereVídeo · 3 Cobrança diária", fluxo_cobranca),
    ("4_Resumo_semanal", "ConfereVídeo · 4 Resumo semanal", fluxo_semanal),
]


def faltando(m):
    falta = []
    if not str(m.get("site_sharepoint", "")).startswith("https://"):
        falta.append("endereço do site do SharePoint")
    if not m.get("chave"):
        falta.append("chave de segurança")
    if not (lista_emails(m.get("emails_supervisores")) or lista_emails(m.get("emails_gestor"))):
        falta.append("pelo menos um e-mail (supervisores ou gestor)")
    return falta


def gerar_pacotes(m, pasta):
    """Gera os 4 pacotes .zip em 'pasta'. Retorna a lista de arquivos."""
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    feitos = []
    for arq, nome, fn in FLUXOS:
        d, cons = fn(m)
        feitos.append(pacote(d, nome, cons, pasta / f"{arq}.zip"))
    (pasta / "LEIA-ME.txt").write_text(LEIA_ME.format(site=m["site_sharepoint"], data=datetime.now()), encoding="utf-8")
    return feitos


LEIA_ME = """ConfereVídeo - fluxos do Power Automate (gerados em {data:%d/%m/%Y %H:%M})
Site do SharePoint: {site}

Em https://make.powerautomate.com com a conta da empresa:
Meus fluxos > Importar > Importar pacote (Herdado) > Carregar > escolha o .zip
Em "Recursos relacionados", clique em cada conexão (SharePoint, Teams, Outlook) e escolha a sua.
Clique em Importar. Faça na ordem:

1_Criar_listas.zip      Depois de importar, abra e clique em Executar (uma vez só).
2_Receber_eventos.zip   Ligue o fluxo e copie a URL do gatilho para o ConfereVídeo.
                        Sem licença Premium: troque o gatilho pelo do Teams (veja o guia, passo 4).
3_Cobranca_diaria.zip   Ligue o fluxo (roda todo dia às 07:00).
4_Resumo_semanal.zip    Ligue o fluxo (roda toda segunda às 07:30).

O passo a passo completo está no GUIA_MICROSOFT_365.html, na pasta Microsoft365 do programa.
"""
