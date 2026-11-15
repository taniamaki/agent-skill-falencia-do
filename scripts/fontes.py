"""Coletores de cada diário oficial.

Cada coletor recebe (data_inicio, data_fim) como datetime.date e devolve uma lista
de dicts com o mesmo formato ("publicação bruta"):

    id, fonte, esfera, diario, data_publicacao (AAAA-MM-DD), titulo, orgao,
    tribunal_uf, numero_processo, classe, partes (lista), texto (HTML ou texto), link

Para acrescentar um novo diário estadual, escreva uma função com essa assinatura
e registre-a em FONTES no final do arquivo (veja references/fontes.md).
"""
import datetime as dt
import json
import re
import sys
import time

import requests

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9",
}

SESSAO = requests.Session()
SESSAO.headers.update(UA)


def log(msg):
    print(msg, file=sys.stderr, flush=True)


class Falha(Exception):
    pass


def pedir(url, params=None, intervalo=0.0, tentativas=4, espera_base=15, aceitar_json=True):
    """GET com novas tentativas para os erros que estes sites dão quando estão
    sobrecarregados (429, 5xx, "sistema muito ocupado")."""
    ultimo = None
    for n in range(tentativas):
        if intervalo:
            time.sleep(intervalo)
        try:
            r = SESSAO.get(url, params=params, timeout=60,
                           headers={"Accept": "application/json" if aceitar_json else "text/html"})
            if r.status_code == 429 or r.status_code >= 500:
                ultimo = f"HTTP {r.status_code}: {r.text[:120]}"
            else:
                r.raise_for_status()
                restante = r.headers.get("X-RateLimit-Remaining")
                if restante is not None and restante.isdigit() and int(restante) <= 1:
                    time.sleep(60)
                return r
        except requests.RequestException as e:
            ultimo = repr(e)[:200]
        espera = espera_base * (2 ** n)
        log(f"    aguardando {espera}s ({ultimo})")
        time.sleep(espera)
    raise Falha(ultimo)


# ---------------------------------------------------------------- DJEN (CNJ)

TRIBUNAIS_ESTADUAIS = [
    "TJAC", "TJAL", "TJAP", "TJAM", "TJBA", "TJCE", "TJDFT", "TJES", "TJGO", "TJMA", "TJMT", "TJMS", "TJMG", "TJPA",
    "TJPB", "TJPR", "TJPE", "TJPI", "TJRJ", "TJRN", "TJRS", "TJRO", "TJRR", "TJSC", "TJSP", "TJSE", "TJTO",
]
TRIBUNAIS_FEDERAIS = ["TRF1", "TRF2", "TRF3", "TRF4", "TRF5", "TRF6"]
TERMOS_DJEN = ["falência", "massa falida", "recuperação judicial", "recuperação extrajudicial"]
DJEN_URL = "https://comunicaapi.pje.jus.br/api/v1/comunicacao"
DJEN_INTERVALO = 3.2  # a API permite 20 consultas por minuto


def djen(inicio, fim, tribunais=None, falhas=None):
    tribunais = tribunais or TRIBUNAIS_ESTADUAIS
    vistos, out = set(), []
    for trib in tribunais:
        antes = len(out)
        for termo in TERMOS_DJEN:
            pagina = 1
            while True:
                params = {"siglaTribunal": trib, "texto": termo,
                          "dataDisponibilizacaoInicio": inicio.isoformat(), "dataDisponibilizacaoFim": fim.isoformat(),
                          "pagina": pagina, "itensPorPagina": 100}
                try:
                    j = pedir(DJEN_URL, params, intervalo=DJEN_INTERVALO).json()
                except Falha as e:
                    msg = f"DJEN {trib} '{termo}' pág. {pagina}: {e}"
                    log("  FALHA " + msg)
                    if falhas is not None:
                        falhas.append(msg)
                    break
                itens = j.get("items") or []
                for it in itens:
                    if it.get("id") in vistos or not it.get("ativo", True):
                        continue
                    vistos.add(it.get("id"))
                    out.append({
                        "id": f"djen:{it.get('id')}",
                        "fonte": "DJEN",
                        "esfera": "Judicial",
                        "diario": f"DJEN – {it.get('siglaTribunal')} ({it.get('meiocompleto') or 'Diário de Justiça Eletrônico Nacional'})",
                        "data_publicacao": it.get("data_disponibilizacao") or "",
                        "titulo": it.get("tipoComunicacao") or it.get("tipoDocumento") or "",
                        "orgao": it.get("nomeOrgao") or "",
                        "tribunal_uf": it.get("siglaTribunal") or trib,
                        "numero_processo": it.get("numeroprocessocommascara") or "",
                        "classe": it.get("nomeClasse") or "",
                        "partes": [d.get("nome", "") for d in it.get("destinatarios") or []],
                        "texto": it.get("texto") or "",
                        "link": f"https://comunicaapi.pje.jus.br/api/v1/comunicacao/{it.get('hash')}/certidao" if it.get("hash") else (it.get("link") or ""),
                    })
                total = j.get("count") or 0
                if not itens or pagina * 100 >= total:
                    break
                pagina += 1
        log(f"  DJEN {trib}: {len(out) - antes} publicações")
    return out


# ---------------------------------------------------------------- DOU

DOU_BUSCA = "https://www.in.gov.br/consulta/-/buscar/dou"
DOU_ARTIGO = "https://www.in.gov.br/web/dou/-/"
TERMOS_DOU = ['"falência"', '"massa falida"', '"recuperação judicial"', '"recuperação extrajudicial"', '"liquidação extrajudicial"']
DOU_JSON_RE = re.compile(r'id="_br_com_seatecnologia_in_buscadou_BuscaDouPortlet_params"[^>]*>(.*?)</script>', re.S)
DOU_TEXTO_RE = re.compile(r'<div class="texto-dou">(.*?)</div>\s*</div>', re.S)


def _dou_pagina(params):
    r = pedir(DOU_BUSCA, params, intervalo=1.0, espera_base=10, aceitar_json=False)
    m = DOU_JSON_RE.search(r.text)
    return json.loads(m.group(1)).get("jsonArray", []) if m else []


def dou(inicio, fim, falhas=None):
    base = {"s": "todos", "exactDate": "personalizado", "sortType": "0",
            "publishFrom": inicio.strftime("%d-%m-%Y"), "publishTo": fim.strftime("%d-%m-%Y")}
    achados = {}
    for termo in TERMOS_DOU:
        params = {**base, "q": termo}
        pagina = 1
        try:
            while True:
                itens = _dou_pagina(params)
                novos = [i for i in itens if i["classPK"] not in achados]
                for i in itens:
                    achados.setdefault(i["classPK"], i)
                if len(itens) < 20 or not novos or pagina >= 50:
                    break
                ult = itens[-1]
                pagina += 1
                params = {**base, "q": termo, "newPage": str(pagina), "currentPage": str(pagina - 1),
                          "score": str(ult.get("score", 0)), "id": ult["classPK"], "displayDate": ult["displayDateSortable"]}
        except Falha as e:
            msg = f"DOU '{termo}': {e}"
            log("  FALHA " + msg)
            if falhas is not None:
                falhas.append(msg)
    log(f"  DOU: {len(achados)} publicações; baixando texto completo")

    out = []
    for pk, i in achados.items():
        link = DOU_ARTIGO + i["urlTitle"]
        texto = i.get("content", "")
        try:
            r = pedir(link, intervalo=0.5, tentativas=2, espera_base=5, aceitar_json=False)
            m = DOU_TEXTO_RE.search(r.text)
            if m:
                texto = m.group(1)
        except Falha as e:
            if falhas is not None:
                falhas.append(f"DOU texto completo {link}: {e} (usado só o resumo da busca)")
        d, mth, y = (i.get("pubDate") or "//").split("/")
        out.append({
            "id": f"dou:{pk}",
            "fonte": "DOU",
            "esfera": "Federal",
            "diario": f"Diário Oficial da União – {i.get('pubName', '').replace('DO', 'Seção ').replace('_EXTRA_', ' Extra ')}".strip(),
            "data_publicacao": f"{y}-{mth}-{d}" if y else "",
            "titulo": i.get("title", ""),
            "orgao": i.get("hierarchyStr", ""),
            "tribunal_uf": "Federal",
            "numero_processo": "",
            "classe": i.get("artType", ""),
            "partes": [],
            "texto": texto,
            "link": link,
        })
    return out


# ---------------------------------------------------------------- DOE-SP

DOESP_BUSCA = "https://do-api-web-search.doe.sp.gov.br/v2/advanced-search/publications"
DOESP_PUB = "https://do-api-web-search.doe.sp.gov.br/v2/publications/"
TERMOS_DOESP = ["falência", "massa falida", "recuperação judicial", "recuperação extrajudicial", "liquidação extrajudicial"]


def doe_sp(inicio, fim, falhas=None):
    achados = {}
    for termo in TERMOS_DOESP:
        pagina = 1
        while True:
            params = {"periodStartingDate": "personalized", "FromDate": inicio.isoformat(), "ToDate": fim.isoformat(),
                      "Terms[0]": termo, "PageNumber": pagina, "PageSize": 100}
            try:
                j = pedir(DOESP_BUSCA, params, intervalo=0.5, espera_base=10).json()
            except Falha as e:
                msg = f"DOE-SP '{termo}': {e}"
                log("  FALHA " + msg)
                if falhas is not None:
                    falhas.append(msg)
                break
            for it in j.get("items") or []:
                achados.setdefault(it["id"], it)
            if not j.get("hasNextPage"):
                break
            pagina += 1
    log(f"  DOE-SP: {len(achados)} publicações; baixando texto completo")

    out = []
    for pid, it in achados.items():
        texto, orgao = it.get("excerpt", ""), it.get("hierarchy", "")
        try:
            p = pedir(DOESP_PUB + pid, intervalo=0.3, tentativas=2, espera_base=5).json()
            texto = p.get("content") or texto
        except Falha as e:
            if falhas is not None:
                falhas.append(f"DOE-SP texto completo {pid}: {e} (usado só o resumo da busca)")
        out.append({
            "id": f"doesp:{pid}",
            "fonte": "DOE-SP",
            "esfera": "Estadual",
            "diario": "Diário Oficial do Estado de São Paulo",
            "data_publicacao": (it.get("date") or "")[:10],
            "titulo": it.get("title", ""),
            "orgao": orgao,
            "tribunal_uf": "SP",
            "numero_processo": "",
            "classe": "",
            "partes": [],
            "texto": texto,
            "link": "https://doe.sp.gov.br/" + it.get("slug", ""),
        })
    return out


# nome usado em --fontes  ->  função coletora
FONTES = {
    "dou": dou,
    "djen": djen,
    "doesp": doe_sp,
}
