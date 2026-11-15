"""Coleta anúncios de falência, recuperação judicial/extrajudicial e liquidação
extrajudicial nos diários oficiais e grava em CSV.

Uso:
    python coletar.py                         # hoje e ontem, todas as fontes
    python coletar.py --fontes djen,dou       # só algumas fontes
    python coletar.py --data-inicio 2026-10-20 --data-fim 2026-10-24
    python coletar.py --tribunais TJSP,TJRJ   # restringe o DJEN (padrão: os 27 TJs)
    python coletar.py --tribunais todos       # TJs + TRFs

Saída (pasta --saida, padrão ./falencias):
    anuncios_falencia.csv          acumulado, sem duplicatas (chave: coluna id)
    novos_AAAA-MM-DD_HHMM.csv      só o que entrou nesta execução
Um resumo em JSON é impresso no fim (stdout); o progresso vai para stderr.
"""
import argparse
import csv
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extrair  # noqa: E402
import fontes  # noqa: E402

COLUNAS = [
    "id", "fonte", "esfera", "diario", "data_publicacao", "tipo_ato", "relevancia",
    "empresa", "cnpj", "numero_processo", "vara_orgao", "tribunal_uf", "classe_processual",
    "administrador_judicial", "termos_encontrados", "titulo", "link", "trecho", "coletado_em",
]
ARQUIVO = "anuncios_falencia.csv"
NIVEIS = {"alta": 3, "media": 2, "baixa": 1}


def processar(pub, agora):
    texto = extrair.texto_limpo(pub["texto"])
    texto_class = " ".join([pub.get("titulo", ""), texto])
    tipo, relevancia, pos = extrair.classificar(texto_class, pub.get("classe", ""), pub.get("partes"))
    pos_texto = max(0, pos - len(pub.get("titulo", "")) - 1) if pos >= 0 else -1
    processos = [pub["numero_processo"]] if pub.get("numero_processo") else extrair.processos(texto)
    return {
        "id": pub["id"],
        "fonte": pub["fonte"],
        "esfera": pub["esfera"],
        "diario": pub["diario"],
        "data_publicacao": pub["data_publicacao"],
        "tipo_ato": tipo,
        "relevancia": relevancia,
        "empresa": " | ".join(extrair.empresas(texto, pub.get("partes"))),
        "cnpj": " | ".join(extrair.cnpjs(texto)),
        "numero_processo": " | ".join(processos),
        "vara_orgao": pub.get("orgao", ""),
        "tribunal_uf": pub.get("tribunal_uf", ""),
        "classe_processual": pub.get("classe", ""),
        "administrador_judicial": extrair.administrador(texto, pub.get("partes")),
        "termos_encontrados": extrair.termos_encontrados(texto_class),
        "titulo": pub.get("titulo", ""),
        "link": pub.get("link", ""),
        "trecho": extrair.trecho(texto, pos_texto),
        "coletado_em": agora,
    }


def ler_ids(caminho):
    if not os.path.exists(caminho):
        return set()
    with open(caminho, newline="", encoding="utf-8-sig") as f:
        return {linha["id"] for linha in csv.DictReader(f, delimiter=";")}


def gravar(caminho, linhas, acrescentar):
    novo = not (acrescentar and os.path.exists(caminho))
    with open(caminho, "w" if novo else "a", newline="", encoding="utf-8-sig" if novo else "utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        if novo:
            w.writeheader()
        w.writerows(linhas)


def main():
    hoje = dt.date.today()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-inicio", type=dt.date.fromisoformat, default=hoje - dt.timedelta(days=1))
    ap.add_argument("--data-fim", type=dt.date.fromisoformat, default=hoje)
    ap.add_argument("--fontes", default="dou,djen,doesp", help="lista separada por vírgulas: " + ",".join(fontes.FONTES))
    ap.add_argument("--tribunais", default="", help="siglas do DJEN separadas por vírgula, ou 'todos' (padrão: 27 TJs)")
    ap.add_argument("--saida", default="falencias", help="pasta de saída")
    ap.add_argument("--brutos", help="salva as publicações baixadas (antes do filtro) neste arquivo .json")
    ap.add_argument("--de-brutos", help="reprocessa um .json salvo com --brutos, sem acessar a internet")
    ap.add_argument("--nivel-minimo", choices=list(NIVEIS), default="alta",
                    help="alta: só anúncios do caso de insolvência (padrão); media: inclui publicações de outros "
                         "processos que citam empresa em falência/RJ; baixa: inclui tudo que a busca trouxe")
    a = ap.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    nomes = [n.strip().lower() for n in a.fontes.split(",") if n.strip()]
    desconhecidas = [n for n in nomes if n not in fontes.FONTES]
    if desconhecidas:
        ap.error(f"fontes desconhecidas: {desconhecidas}; opções: {list(fontes.FONTES)}")
    if a.tribunais.lower() == "todos":
        tribunais = fontes.TRIBUNAIS_ESTADUAIS + fontes.TRIBUNAIS_FEDERAIS
    else:
        tribunais = [t.strip().upper() for t in a.tribunais.split(",") if t.strip()] or None

    os.makedirs(a.saida, exist_ok=True)
    caminho = os.path.join(a.saida, ARQUIVO)
    ja_gravados = ler_ids(caminho)
    agora = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    falhas, resumo_fontes, novos = [], {}, []
    ini, fim = a.data_inicio.isoformat(), a.data_fim.isoformat()

    brutos = {}
    if a.de_brutos:
        with open(a.de_brutos, encoding="utf-8") as f:
            brutos = json.load(f)
        nomes = list(brutos)
    for nome in nomes:
        if a.de_brutos:
            pubs = brutos[nome]
        else:
            fontes.log(f"Coletando {nome.upper()} de {ini} a {fim}...")
            kwargs = {"falhas": falhas}
            if nome == "djen":
                kwargs["tribunais"] = tribunais
            try:
                pubs = fontes.FONTES[nome](a.data_inicio, a.data_fim, **kwargs)
            except Exception as e:  # uma fonte fora do ar não deve derrubar as outras
                falhas.append(f"{nome}: erro inesperado {e!r}")
                fontes.log(f"  ERRO {nome}: {e!r}")
                pubs = []
            brutos[nome] = pubs
        cont = {"publicacoes_lidas": len(pubs), "alta": 0, "media": 0, "baixa": 0, "novas_gravadas": 0}
        for pub in pubs:
            if pub["data_publicacao"] and not (ini <= pub["data_publicacao"] <= fim):
                continue
            linha = processar(pub, agora)
            cont[linha["relevancia"]] += 1
            if NIVEIS[linha["relevancia"]] < NIVEIS[a.nivel_minimo]:
                continue
            if linha["id"] in ja_gravados:
                continue
            ja_gravados.add(linha["id"])
            novos.append(linha)
            cont["novas_gravadas"] += 1
        resumo_fontes[nome] = cont

    if a.brutos and not a.de_brutos:
        with open(a.brutos, "w", encoding="utf-8") as f:
            json.dump(brutos, f, ensure_ascii=False)

    novos.sort(key=lambda l: (l["data_publicacao"], l["fonte"], l["tribunal_uf"]))
    gravar(caminho, novos, acrescentar=True)
    arquivo_execucao = os.path.join(a.saida, f"novos_{dt.datetime.now():%Y-%m-%d_%H%M}.csv")
    gravar(arquivo_execucao, novos, acrescentar=False)

    por_tipo = {}
    for l in novos:
        por_tipo[l["tipo_ato"]] = por_tipo.get(l["tipo_ato"], 0) + 1
    print(json.dumps({
        "periodo": [ini, fim],
        "arquivo_acumulado": os.path.abspath(caminho),
        "arquivo_desta_execucao": os.path.abspath(arquivo_execucao),
        "novos_registros": len(novos),
        "por_fonte": resumo_fontes,
        "por_tipo_ato": dict(sorted(por_tipo.items(), key=lambda kv: -kv[1])),
        "falhas": falhas,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
