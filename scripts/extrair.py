"""Classificação e extração de campos de publicações sobre falência e recuperação.

Recebe o texto de uma publicação (HTML ou texto puro) e decide:
  - se é um anúncio do caso de insolvência ou só uma menção de passagem
    (ex.: "certidão negativa de falência" num edital de licitação, ou uma
    execução comum em que uma das partes está em recuperação judicial);
  - qual o tipo de ato (decretação de falência, deferimento de RJ, edital...);
  - empresa, CNPJ, número do processo e administrador judicial.

A classificação usa o texto sem acentos e em minúsculas, para tolerar as
variações de grafia dos diários; a extração de nomes usa o texto original,
porque depende das maiúsculas.
"""
import functools
import html
import re
import unicodedata


def texto_limpo(bruto: str) -> str:
    """HTML -> texto corrido, preservando acentos."""
    if not bruto:
        return ""
    t = re.sub(r"(?is)<(style|script)[^>]*>.*?</\1>", " ", bruto)
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</tr>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    t = t.replace("‑", "-").replace(" ", " ")
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    t = re.sub(r"\s*\n\s*", "\n", t)
    return t.strip()


class _TabelaNormal(dict):
    """Tabela para str.translate, preenchida sob demanda (um caractere por vez)."""

    def __missing__(self, cod):
        ch = chr(cod)
        base = unicodedata.normalize("NFD", ch)[0].lower()
        self[cod] = base if len(base) == 1 else ch
        return self[cod]


_TABELA_NORMAL = _TabelaNormal()


def normalizar(t: str) -> str:
    """Minúsculas e sem acentos, com o mesmo comprimento do texto original, para
    que as posições encontradas aqui sirvam para recortar o texto original."""
    return t.translate(_TABELA_NORMAL)


# ---------------------------------------------------------------- classificação

# Menções que não são anúncios: exigências de licitação, nomes de varas, citações
# de lei, rótulos de assunto do e-SAJ. São apagadas antes da classificação.
RUIDO = [
    r"certid(ao|oes) [^.;\n]{0,120}(falencia|recuperacao|concordata)[^.;\n]{0,120}",
    r"(nao|nem) (esteja|estar|estiver|estejam|se encontre|se encontrar|encontrar-se|for|seja|possua)[^.;\n]{0,120}(falencia|recuperacao|concordata|falid)[^.;\n]{0,250}",
    r"(empresas?|licitantes?|fornecedor\w*|interessad\w*|pessoas? juridicas?|participantes?) (que se encontrem |que estejam )?(em|sob) (processo de )?(falencia|recuperacao|concordata|liquidacao)[^.;\n]{0,250}",
    r"(sob|em) (processo de )?(falencia|concordata), (recuperacao|concordata|dissolucao|liquidacao|insolvencia)[^.;\n]{0,250}",
    r"viabilidade economica[^.;\n]{0,160}plano de recuperacao[^.;\n]{0,80}",
    r"falencia,? (ou |de )?(recuperacao judicial|concordata|insolvencia)( ou (extrajudicial|recuperacao extrajudicial))?[^.;\n]{0,40}(do licitante|da licitante|do fornecedor|da empresa|da contratada)",
    r"(decretacao|declaracao) de falencia,? (concordata|recuperacao|insolvencia|dissolucao)[^.;\n]{0,120}",
    r"varas? (empresaria\w* e )?(regionais? )?(de |da |das )?(falencias?|empresarial)[^.;\n]{0,10}(e |, )?(de )?(recuperac\w+ judicia\w+)?( e conflitos[^.;\n]{0,40})?",
    r"(juizo|juiz\w*|tribunal) (da |de |das )?(falencias?|recuperacoes?)( e recuperacoes judiciais)?",
    r"lei (n[o.º°]* ?)?(11\.?101|14\.?112|7\.?661)[^.;\n]{0,40}",
    r"recuperacao judicial e falencia",          # assunto processual do e-SAJ
    r"(falencia decretada|decretada a falencia)\s*-",  # rótulo de situação do e-SAJ
    r"fls?\.? ?\d+\s*:\s*decretada a falencia",
]
RUIDO_RE = [re.compile(p) for p in RUIDO]

# Tipos de ato, do mais específico para o mais genérico; o primeiro que casar vence.
# nível "ato"     -> decisão ou fato central do caso (sempre relevante);
#       "edital"  -> comunicações típicas do processo de insolvência;
#       "generico"-> só menciona o tema.
#
# Convolação e decretação só contam quando o próprio texto decide ("convolo",
# "decreto a falência", "fixo o termo legal"). Frases como "a quebra foi decretada
# em 2017" ou "sob pena de convolação em falência" citam decisões antigas ou
# hipotéticas e caem em "Outros atos – falência".
TIPOS = [
    ("Convolação em falência", "ato", r"\bconvolo(?![a-z])|\bconvoloem|convolando (a |em )?(presente )?(recuperacao|concordata)|convola-se|fica convolada|(julgo|declaro)[^.;\n]{0,80}convol"),
    ("Decretação de falência", "ato", r"\bdecreto,? (hoje,? )?(a |sua |a sua )?(quebra|falencia)|declaro (aberta |a )+falencia|decreta-se a (quebra|falencia)|fica decretada a (quebra|falencia)|(julgo|declaro) procedente[^.;\n]{0,200}decret\w* (a |sua )?(quebra|falencia)|\bfixo,? (como |o )*termo legal"),
    ("Encerramento de falência", "ato", r"encerra\w* (da |a |o processo de )?falencia|falencia[^.;\n]{0,30}encerrada"),
    ("Pedido de falência", "ato", r"pedido de (auto)?falencia|requer\w* (a |sua )?(auto)?falencia|auto-?falencia"),
    ("Deferimento de recuperação judicial", "ato", r"defer\w* (o )?processamento d[ae] (pedido de )?recuperacao judicial|processamento da recuperacao judicial[^.;\n]{0,30}deferido"),
    ("Concessão / homologação de plano de recuperação", "edital",r"conce(do|ssao da|dida a) (a )?recuperacao judicial|homolog\w*[^.;\n]{0,40}plano de recuperacao|homolog\w*[^.;\n]{0,40}recuperacao extrajudicial"),
    ("Encerramento de recuperação judicial", "ato", r"encerra\w* (da |a )?recuperacao judicial"),
    ("Liquidação extrajudicial", "ato", r"decret\w*[^.;\n]{0,60}liquidacao extrajudicial|liquidacao extrajudicial[^.;\n]{0,60}decretad"),
    ("Assembleia geral de credores", "edital", r"assembleia(-| )geral de credores|assembleia de credores"),
    ("Edital / habilitação de créditos", "edital", r"(edital|aviso)[^\n]{0,300}credores|(relacao|quadro geral|lista) de credores|habilitac\w+[^.;\n]{0,20}credit|impugnac\w+[^.;\n]{0,20}credit|divergenc\w+[^.;\n]{0,20}credit"),
    ("Plano de recuperação", "edital", r"plano de recuperacao"),
    ("Pedido de recuperação judicial", "edital", r"(pedido|requerimento) de recuperacao judicial|requer\w*[^.;\n]{0,40}recuperacao judicial|ajuiz\w*[^.;\n]{0,40}recuperacao judicial"),
    ("Recuperação extrajudicial", "edital", r"(pedido|plano|homologacao)[^.;\n]{0,30}recuperacao extrajudicial"),
    ("Alienação / leilão de bens da massa", "edital", r"leil(ao|oes)|alienacao[^.;\n]{0,40}(bens|ativos?|upi)|hasta publica"),
    ("Outros atos – falência", "generico", r"massa falida|falencia|\bfalid[ao]s?\b"),
    ("Outros atos – recuperação judicial", "generico", r"recuperacao judicial|recuperand[ao]s?\b"),
    ("Outros atos – recuperação extrajudicial", "generico", r"recuperacao extrajudicial"),
    ("Outros atos – liquidação extrajudicial", "generico", r"liquidacao extrajudicial"),
]
TIPOS_RE = [(nome, nivel, re.compile(p)) for nome, nivel, p in TIPOS]

# Classes processuais (DJEN) que indicam que o próprio processo é de insolvência.
CLASSES_RELACIONADAS = re.compile(
    r"falencia|recuperacao judicial|recuperacao extrajudicial|autofalencia|habilitacao de credito|impugnacao de credito|classificacao de credito|insolvencia"
)
# Classes que não dizem nada sobre o assunto: a cautelar antecedente é a porta de
# entrada comum de uma RJ, então valem como "sem classe" e o texto decide.
CLASSES_NEUTRAS = re.compile(r"tutela (cautelar|antecipada) antecedente")
# Sinais de que alguma das partes está em falência/recuperação/liquidação.
MARCA_INSOLVENCIA = re.compile(r"massa falida|recuperand[ao]|em recuperacao (judicial|extrajudicial)|em liquidacao extrajudicial|\bfalid[ao]\b")
CONTEXTO_INSOLVENCIA = re.compile(r"massa falida|falencia|falid[ao]|recuperacao judicial|recuperand[ao]|recuperacao extrajudicial|liquidacao extrajudicial")

TERMOS_REL = re.compile(
    r"massa falida|autofalencia|falencia|falid[ao]s?\b|recuperacao judicial|recuperacao extrajudicial|recuperand[ao]s?\b|liquidacao extrajudicial|administrador\w* judicial|assembleia(-| )geral de credores|plano de recuperacao"
)


def remover_ruido(norm: str) -> str:
    for rx in RUIDO_RE:
        norm = rx.sub(lambda m: " " * len(m.group(0)), norm)
    return norm


def texto_classificavel(texto: str) -> str:
    return remover_ruido(normalizar(texto))


@functools.lru_cache(maxsize=512)
def _buscas(norm: str):
    """As buscas que só dependem do texto (a parte cara), guardadas porque o DJEN
    repete o mesmo texto para cada destinatário com classe e partes diferentes."""
    achados = []
    for nome, nivel, rx in TIPOS_RE:
        m = rx.search(norm)
        if m:
            achados.append((nome, nivel, m.start()))
    return achados, bool(MARCA_INSOLVENCIA.search(norm)), bool(CONTEXTO_INSOLVENCIA.search(norm))


def classificar(texto: str, classe: str = "", partes=None, norm: str = None):
    """Retorna (tipo_ato, relevancia, posicao_do_trecho).

    relevancia:
      "alta"  -> a publicação é do caso de insolvência: processo de classe
                 falência/RJ/habilitação etc., ou um ato/edital típico do caso;
      "media" -> só cita uma empresa em falência/recuperação dentro de outro
                 assunto (ex.: execução contra uma empresa em RJ);
      "baixa" -> menção de passagem; nada sobra depois de remover o ruído.

    Quando a publicação tem classe processual (DJEN), a classe decide: se não é de
    insolvência (execução, juizado, agravo...), a publicação é de outro processo
    que só cita a falência/RJ — no máximo "media", mesmo que mencione uma
    decretação ("aguarde-se o encerramento da falência", "o juízo X decretou...").

    `norm` aceita o texto já passado por normalizar() e remover_ruido(), para não
    refazer o trabalho em publicações grandes.
    """
    if norm is None:
        norm = texto_classificavel(texto)
    classe_n = normalizar(classe or "")
    partes_n = normalizar(" ".join(partes or []))
    classe_rel = bool(CLASSES_RELACIONADAS.search(classe_n))
    tem_classe = bool(classe_n.strip()) and not CLASSES_NEUTRAS.search(classe_n)
    achados, marca_texto, contexto = _buscas(norm)
    marca = marca_texto or bool(MARCA_INSOLVENCIA.search(partes_n))

    for nome, nivel, pos in achados:
        if nome.startswith("Alienação") and not (classe_rel or contexto):
            continue
        if classe_rel or (nivel != "generico" and not tem_classe):
            return nome, "alta", pos
        if nivel != "generico" or marca:
            return nome, "media", pos
        return nome, "baixa", pos

    if classe_rel:
        tipo = "Outros atos – falência" if "falencia" in classe_n else "Outros atos – recuperação judicial"
        return tipo, "alta", 0
    if marca:
        tipo = "Outros atos – falência" if "falid" in partes_n else "Outros atos – recuperação judicial"
        return tipo, "media", 0
    return "", "baixa", -1


def termos_encontrados(texto: str, norm: str = None) -> str:
    if norm is None:
        norm = texto_classificavel(texto)
    return ", ".join(sorted({m.group(0) for m in TERMOS_REL.finditer(norm)}))


# ---------------------------------------------------------------- extração

SUFIXO = r"(?:LTDA|Ltda|LIMITADA|Limitada|S/A|S\.\s?A\.?|S\.A|EIRELI|Eireli|EPP|S/S)"
PAL = r"[A-ZÀ-Ý0-9][\wÀ-ÿ&'´`.\-/]*"
CONECTOR = r"(?:de|da|do|dos|das|e|&|DE|DA|DO|DOS|DAS|E)"
NOME = rf"(?:{PAL}(?:\s+|,\s*)(?:{CONECTOR}\s+)?){{0,11}}{PAL}"

CHAVE = r"(?i:fal[eê]ncia|massa falida|recupera[cç][aã]o judicial|recupera[cç][aã]o extrajudicial|liquida[cç][aã]o extrajudicial|autofal[eê]ncia|recuperand[ao]s?)"
APOS_CHAVE_RE = re.compile(rf"{CHAVE}\s+(?i:d[aoe]s?\s+)?(?i:(?:empresa|sociedade|devedora|requerente)\s+)?({NOME})")
# Nome da classe processual do CNJ, que senão seria lido como "falência de <empresa>".
CLASSE_FALENCIA_RE = re.compile(r"(?i)fal[eê]ncia de empres[aá]rios,? sociedades empres[aá]r\w*,? microempresas e empresas de pequeno porte")
ANTES_MARCA_RE = re.compile(
    rf"({NOME})\s*(?:[-–(,]?\s*\(?(?i:em recupera[cç][aã]o judicial|em recupera[cç][aã]o extrajudicial|em liquida[cç][aã]o extrajudicial|massa falida)|[-–(]\s*(?i:falid[ao])\b)"
)
EMPRESA_SUFIXO_RE = re.compile(rf"(?:{PAL}(?:\s+|,\s*)(?:{CONECTOR}\s+)?){{1,11}}?{SUFIXO}")

# Onde um nome de empresa termina (o texto que vem depois já é outra coisa).
FIM_NOME_RE = re.compile(
    r"(?i)[,\s]+(?:cnpj|cpf|inscrit\w*|com sede|sediad\w*|situad\w*|estabelecid\w*|rua|r(?=\.\s)|avenida|av(?=\.)|nire|processo|autos|n[º°o]\.?\s|adv\b|advogad\w*|oab|representad\w*|por meio|nos termos|neste|nesta|vem|requer\w*|ajuiz\w*|em face|contra|ficam?|foi|que|onde|cujo|para|pelo|pela|e outr\w*|\(fls?)\b.*$"
)
PALAVRAS_PROIBIDAS = re.compile(
    r"(?i)\b(?:fal[eê]ncias?|microempresas?|pequeno porte|recupera[cç][aã]o|judicial|extrajudicial|vara|ju[ií]z\w*|processo|edital|autos|credores|decretad\w*|decreto|senten[cç]a|massa|falid[ao]|tribunal|comarca|foro|advogad\w*|cart[oó]rio|intima[cç][aã]o|assembleia|encerrad\w*|ficha|assunto|valor|causa|estado|cep|bairro|endere[cç]o)\b"
    r"|\d{5,}|/(?:AC|AL|AP|AM|BA|CE|DF|ES|GO|MA|MT|MS|MG|PA|PB|PR|PE|PI|RJ|RN|RS|RO|RR|SC|SP|SE|TO)\b|,\s*EM$"  # números de processo, "CIDADE/UF", "CURITIBA, ..., EM"
)
ADMIN_NOME_RE = re.compile(r"(?i)administra\w*\s+(?:judicia\w*|de fal[eê]ncias)|\bAJ\b")
LIXO_INICIAL = re.compile(r"^(?:[\d.\-/º°]+\s*[-–]?\s*|(?:a|o|as|os|da|do|de|das|dos|e|A|O|DA|DO|DE|E)\s+)+")


def _limpar_nome(n: str) -> str:
    n = re.sub(r"\s+", " ", n).strip(" ,.-–:;")
    n = FIM_NOME_RE.sub("", n)
    m = re.search(SUFIXO, n)
    if m:
        n = n[:m.end()]
    n = LIXO_INICIAL.sub("", n)
    return n.strip(" ,.-–:;()")


def _nome_valido(n: str) -> bool:
    palavras = n.split()
    return (len(n) >= 4 and len(palavras) >= 2 and len(palavras) <= 14
            and not PALAVRAS_PROIBIDAS.search(n) and not re.fullmatch(r"[\d\W]+", n))


def empresas(texto: str, partes=None, maximo: int = 5):
    """Empresas em falência / recuperação citadas na publicação.

    Ordem de confiança: partes do processo marcadas como massa falida / em
    recuperação (DJEN); nome logo depois de "falência de", "massa falida de"...;
    nome logo antes de "- em recuperação judicial"; e, só se nada disso achar,
    a primeira razão social (LTDA, S/A...) do texto. Administradoras judiciais
    ficam de fora (vão para a coluna administrador_judicial)."""
    vistos, out = [], []
    texto = CLASSE_FALENCIA_RE.sub(" ", texto)

    def add(n):
        n = _limpar_nome(n)
        chave = normalizar(re.sub(r"[^\w]", "", n))
        if not chave or ADMIN_NOME_RE.search(n) or not _nome_valido(n):
            return
        # "COMERCIO E EXPORTACAO LTDA" é pedaço de "POLIMPORT - COMERCIO E EXPORTACAO LTDA"
        if any(chave in v or v in chave for v in vistos):
            return
        vistos.append(chave)
        out.append(n)

    for p in partes or []:
        if re.search(r"(?i)massa falida|recupera[cç][aã]o|liquida[cç][aã]o extrajudicial|falid[ao]", p):
            limpo = re.sub(r"(?i)\s*[-–(]*\s*(massa falida( d[aoe])?|em recupera[cç][aã]o (judicial|extrajudicial)|em liquida[cç][aã]o extrajudicial)\s*[)]?\s*", " ", p)
            add(limpo)
    for rx in (APOS_CHAVE_RE, ANTES_MARCA_RE):
        for m in rx.finditer(texto):
            add(m.group(1))
            if len(out) >= maximo:
                return out
    if not out:
        for m in EMPRESA_SUFIXO_RE.finditer(texto):
            add(m.group(0))
            if len(out) >= 2:
                break
    return out[:maximo]


def _cnpj_valido(d: str) -> bool:
    if len(d) != 14 or len(set(d)) == 1:
        return False
    for tam in (12, 13):
        pesos = list(range(tam - 7, 1, -1)) + list(range(9, 1, -1))
        soma = sum(int(x) * p for x, p in zip(d[:tam], pesos))
        dig = 11 - soma % 11
        if (0 if dig >= 10 else dig) != int(d[tam]):
            return False
    return True


CNPJ_RE = re.compile(r"(?<![\d.])(\d{2})\.?(\d{3})\.?(\d{3})\s?/\s?(\d{4})\s?-?\s?(\d{2})(?!\d)|(?<![\d.])(\d{14})(?!\d)")


def cnpjs(texto: str):
    out = []
    for m in CNPJ_RE.finditer(texto):
        d = re.sub(r"\D", "", m.group(0))
        if _cnpj_valido(d):
            c = f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
            if c not in out:
                out.append(c)
    return out[:5]


PROCESSO_RE = re.compile(r"(?<!\d)(\d{7})-?(\d{2})\.?(\d{4})\.?(\d)\.?(\d{2})\.?(\d{4})(?!\d)")


def processos(texto: str):
    out = []
    for m in PROCESSO_RE.finditer(texto):
        p = "{}-{}.{}.{}.{}.{}".format(*m.groups())
        if p not in out:
            out.append(p)
    return out[:3]


ADMIN_RE = re.compile(
    rf"(?:(?i:administrador(?:a)?\s+judicial)|(?i:cujo\s+administrador(?:\s+judicial)?\s+(?:é|e)))"
    rf"(?:\s+(?i:nomead[oa]))?(?:\s*[:,\-–]\s*|\s+(?i:o|a|é|sr\.?|sra\.?|dr\.?|dra\.?)\s+|\s+)*({NOME})"
)


def administrador(texto: str, partes=None) -> str:
    """Administrador judicial: primeiro procura o nome escrito logo depois de
    "administrador judicial"; se não achar, uma parte/empresa do texto cuja
    razão social indique administração judicial."""
    for m in ADMIN_RE.finditer(texto):
        n = _limpar_nome(m.group(1))
        if _nome_valido(n) and not re.match(r"(?i)(ltda|s/a|s\.a|advogad|eireli)\b", n):
            return n
    for n in list(partes or []) + [m.group(0) for m in EMPRESA_SUFIXO_RE.finditer(texto)]:
        if re.search(r"(?i)administra\w*\s+(?:judicia\w*|de fal[eê]ncias)", n):
            n = _limpar_nome(n)
            if 2 <= len(n.split()) <= 9 and not re.search(r"(?i)massa|manifesta|falid|\.\s", n):
                return n
    return ""


def trecho(texto: str, pos: int, tamanho: int = 700) -> str:
    pos = max(pos, 0)
    ini = max(0, pos - 150)
    if ini > 0:
        espaco = texto.find(" ", ini)
        ini = espaco + 1 if 0 <= espaco < pos else ini
    t = texto[ini:ini + tamanho].replace("\n", " ").strip()
    return ("…" if ini > 0 else "") + t + ("…" if ini + tamanho < len(texto) else "")
