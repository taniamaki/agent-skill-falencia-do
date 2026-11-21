"""API somente leitura sobre a planilha de falências e recuperações judiciais.

Lê falencias/anuncios_falencia.csv (gerada pela skill diarios-falencias) e a
recarrega sozinha quando a coleta grava novos registros.

Uso:
    python api/servidor.py                       # http://127.0.0.1:8000
    python api/servidor.py --porta 8080 --arquivo outra/planilha.csv

Rotas:
    GET /                    índice das rotas
    GET /anuncios            lista com filtros e paginação (JSON)
    GET /anuncios.csv        mesma consulta, em CSV
    GET /anuncios/<id>       um registro (ex.: /anuncios/djen:123456789)
    GET /resumo              totais por data, tipo de ato e tribunal
    GET /tipos               valores de tipo_ato existentes

Filtros de /anuncios (todos opcionais, combináveis):
    data_inicio, data_fim    AAAA-MM-DD (data de publicação)
    tipo_ato                 trecho do tipo, sem distinguir acento/maiúscula
                             (ex.: "decretacao", "recuperacao judicial")
    tribunal                 sigla ou lista: TJSP,TJRJ
    fonte                    djen, dou, doesp
    relevancia               alta, media, baixa
    empresa, processo, cnpj  trecho do texto
    q                        busca em empresa, processo, CNPJ, tipo e trecho
    pagina, por_pagina       padrão 1 e 100 (máximo 1000)
"""
import argparse
import csv
import io
import os
import threading
import unicodedata

from flask import Flask, Response, abort, jsonify, request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARQUIVO_PADRAO = os.path.join(RAIZ, "falencias", "anuncios_falencia.csv")
MAX_POR_PAGINA = 1000

app = Flask(__name__)
app.json.ensure_ascii = False
app.json.sort_keys = False


def _sem_acento(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t or "") if not unicodedata.combining(c)).lower()


class Planilha:
    """Mantém a planilha em memória e a relê quando o arquivo muda no disco."""

    def __init__(self, caminho):
        self.caminho = caminho
        self._mtime = None
        self._linhas = []
        self._colunas = []
        self._trava = threading.Lock()

    def linhas(self):
        with self._trava:
            try:
                mtime = os.path.getmtime(self.caminho)
            except OSError:
                return [], []
            if mtime != self._mtime:
                # A coleta grava no fim; se pegar o arquivo no meio da escrita,
                # a próxima requisição relê.
                with open(self.caminho, newline="", encoding="utf-8-sig") as f:
                    leitor = csv.DictReader(f, delimiter=";")
                    linhas = list(leitor)
                    self._colunas = leitor.fieldnames or []
                for l in linhas:
                    l["_busca"] = _sem_acento(" ".join(
                        l.get(c, "") for c in ("empresa", "numero_processo", "cnpj", "tipo_ato", "trecho")))
                linhas.sort(key=lambda l: (l.get("data_publicacao", ""), l.get("id", "")), reverse=True)
                self._linhas, self._mtime = linhas, mtime
            return self._linhas, self._colunas

    def atualizado_em(self):
        try:
            from datetime import datetime
            return datetime.fromtimestamp(os.path.getmtime(self.caminho)).isoformat(timespec="seconds")
        except OSError:
            return None


planilha = Planilha(ARQUIVO_PADRAO)


def _publico(linha):
    return {k: v for k, v in linha.items() if not k.startswith("_")}


def _filtrar(args):
    linhas, _ = planilha.linhas()
    ini, fim = args.get("data_inicio", ""), args.get("data_fim", "")
    tipo = _sem_acento(args.get("tipo_ato", ""))
    tribunais = {t.strip().upper() for t in args.get("tribunal", "").split(",") if t.strip()}
    fonte = args.get("fonte", "").strip().lower()
    relevancia = args.get("relevancia", "").strip().lower()
    empresa = _sem_acento(args.get("empresa", ""))
    processo = args.get("processo", "").strip()
    cnpj_digitos = "".join(c for c in args.get("cnpj", "") if c.isdigit())
    q = _sem_acento(args.get("q", ""))

    out = []
    for l in linhas:
        d = l.get("data_publicacao", "")
        if ini and d < ini or fim and d > fim:
            continue
        if tipo and tipo not in _sem_acento(l.get("tipo_ato", "")):
            continue
        if tribunais and l.get("tribunal_uf", "").upper() not in tribunais:
            continue
        if fonte and l.get("fonte", "").lower() != fonte:
            continue
        if relevancia and l.get("relevancia", "") != relevancia:
            continue
        if empresa and empresa not in _sem_acento(l.get("empresa", "")):
            continue
        if processo and processo not in l.get("numero_processo", ""):
            continue
        if cnpj_digitos and cnpj_digitos not in "".join(c for c in l.get("cnpj", "") if c.isdigit()):
            continue
        if q and q not in l["_busca"]:
            continue
        out.append(l)
    return out


def _inteiro(nome, padrao, minimo, maximo):
    try:
        v = int(request.args.get(nome, padrao))
    except ValueError:
        abort(400, description=f"'{nome}' deve ser um número inteiro")
    return max(minimo, min(v, maximo))


@app.errorhandler(400)
@app.errorhandler(404)
def _erro(e):
    return jsonify({"erro": e.description}), e.code


@app.get("/")
def indice():
    return jsonify({
        "descricao": "Anúncios de falência, recuperação judicial/extrajudicial e liquidação extrajudicial "
                     "publicados em diários oficiais (DJEN, DOU, DOE-SP).",
        "atualizado_em": planilha.atualizado_em(),
        "rotas": {
            "/anuncios": "lista com filtros: data_inicio, data_fim, tipo_ato, tribunal, fonte, relevancia, "
                         "empresa, processo, cnpj, q, pagina, por_pagina",
            "/anuncios.csv": "mesma consulta em CSV (sem paginação)",
            "/anuncios/<id>": "um registro, ex.: /anuncios/djen:123456789",
            "/resumo": "totais por data, tipo de ato e tribunal (aceita os mesmos filtros)",
            "/tipos": "valores de tipo_ato",
        },
    })


@app.get("/anuncios")
def anuncios():
    linhas = _filtrar(request.args)
    pagina = _inteiro("pagina", 1, 1, 10**6)
    por_pagina = _inteiro("por_pagina", 100, 1, MAX_POR_PAGINA)
    ini = (pagina - 1) * por_pagina
    return jsonify({
        "total": len(linhas),
        "pagina": pagina,
        "por_pagina": por_pagina,
        "paginas": (len(linhas) + por_pagina - 1) // por_pagina,
        "itens": [_publico(l) for l in linhas[ini:ini + por_pagina]],
    })


@app.get("/anuncios.csv")
def anuncios_csv():
    linhas = _filtrar(request.args)
    _, colunas = planilha.linhas()
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=colunas, delimiter=";", extrasaction="ignore")
    w.writeheader()
    w.writerows(linhas)
    return Response("﻿" + buf.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=anuncios_falencia.csv"})


@app.get("/anuncios/<path:id_>")
def anuncio(id_):
    linhas, _ = planilha.linhas()
    for l in linhas:
        if l.get("id") == id_:
            return jsonify(_publico(l))
    abort(404, description=f"registro '{id_}' não encontrado")


def _contar(linhas, campo):
    cont = {}
    for l in linhas:
        cont[l.get(campo, "")] = cont.get(l.get(campo, ""), 0) + 1
    return cont


@app.get("/resumo")
def resumo():
    linhas = _filtrar(request.args)
    datas = sorted(l["data_publicacao"] for l in linhas if l.get("data_publicacao"))
    return jsonify({
        "total": len(linhas),
        "periodo": [datas[0], datas[-1]] if datas else None,
        "atualizado_em": planilha.atualizado_em(),
        "por_data": dict(sorted(_contar(linhas, "data_publicacao").items())),
        "por_tipo_ato": dict(sorted(_contar(linhas, "tipo_ato").items(), key=lambda kv: -kv[1])),
        "por_tribunal": dict(sorted(_contar(linhas, "tribunal_uf").items(), key=lambda kv: -kv[1])),
    })


@app.get("/tipos")
def tipos():
    linhas, _ = planilha.linhas()
    return jsonify(sorted({l.get("tipo_ato", "") for l in linhas if l.get("tipo_ato")}))


def main():
    ap = argparse.ArgumentParser(description="API somente leitura sobre a planilha de falências.")
    ap.add_argument("--host", default="127.0.0.1",
                    help="127.0.0.1 = só este computador (padrão); 0.0.0.0 = aceita outras máquinas da rede")
    ap.add_argument("--porta", type=int, default=8000)
    ap.add_argument("--arquivo", default=ARQUIVO_PADRAO, help="planilha CSV a servir")
    a = ap.parse_args()
    planilha.caminho = os.path.abspath(a.arquivo)
    print(f"Servindo {planilha.caminho} em http://{a.host}:{a.porta}/")
    app.run(host=a.host, port=a.porta, threaded=True)


if __name__ == "__main__":
    main()
