# Fontes: detalhes técnicos

Notas sobre cada API, verificadas em outubro de 2026. Consulte este arquivo ao
depurar uma falha ou ao acrescentar uma fonte.

## DJEN — Diário de Justiça Eletrônico Nacional (CNJ)

- Endpoint: `GET https://comunicaapi.pje.jus.br/api/v1/comunicacao`
- Parâmetros: `siglaTribunal`, `texto`, `dataDisponibilizacaoInicio`,
  `dataDisponibilizacaoFim` (AAAA-MM-DD), `pagina`, `itensPorPagina` (máx. 100).
- Resposta: `{"status","message","count","items":[...]}`. Campos úteis do item:
  `id`, `hash`, `data_disponibilizacao`, `siglaTribunal`, `tipoComunicacao`,
  `nomeOrgao`, `texto` (HTML), `numeroprocessocommascara`, `nomeClasse`,
  `codigoClasse`, `destinatarios[].nome`/`polo`, `ativo`.
- Certidão (PDF) da publicação: `/api/v1/comunicacao/{hash}/certidao`.
- **Limite: 20 consultas por minuto** (cabeçalhos `X-RateLimit-Limit` e
  `X-RateLimit-Remaining`). O coletor espera 3,2 s entre as consultas.
- Busca **sem** `siglaTribunal` costuma dar HTTP 500 com "O sistema está muito
  ocupado". Por isso o coletor consulta um tribunal de cada vez. Mesmo por
  tribunal, esse erro aparece de vez em quando. O coletor tenta 4 vezes, esperando
  15, 30, 60 e 120 s.
- O `texto` busca palavras no conteúdo, então a busca traz muita coisa que só cita
  "falência" (por exemplo, o nome da vara). A classificação em `extrair.py` filtra isso.
- Siglas: TJAC … TJTO (o do DF é `TJDFT`), TRF1–TRF6, TRT1–TRT24, STJ etc.

## DOU — Diário Oficial da União

- Busca: `GET https://www.in.gov.br/consulta/-/buscar/dou` com `q` (frase entre
  aspas), `s=todos`, `exactDate=personalizado`, `publishFrom`/`publishTo`
  (DD-MM-AAAA), `sortType=0`.
- Os resultados vêm em JSON dentro de
  `<script id="_br_com_seatecnologia_in_buscadou_BuscaDouPortlet_params">`
  (`jsonArray`), com 20 por página.
- Próxima página: repetir a busca com `newPage=N`, `currentPage=N-1`, e `score`,
  `id` (=`classPK`) e `displayDate` (=`displayDateSortable`) do último item.
- Texto completo: `https://www.in.gov.br/web/dou/-/{urlTitle}`, dentro de
  `<div class="texto-dou">`.
- No DOU, "falência" aparece quase sempre em exigências de licitação. Os anúncios
  úteis são as liquidações extrajudiciais e os editais de terceiros (Seção 3).

## DOE-SP — Diário Oficial do Estado de São Paulo

- Busca: `GET https://do-api-web-search.doe.sp.gov.br/v2/advanced-search/publications`
  com `periodStartingDate=personalized`, `FromDate`/`ToDate` (AAAA-MM-DD),
  `Terms[0]`, `PageNumber`, `PageSize` (100). Sem `periodStartingDate=personalized`,
  o filtro de data é ignorado e a busca volta vazia.
- Resposta: `items[]` (`id`, `title`, `slug`, `date`, `excerpt`, `hierarchy`),
  `hasNextPage`.
- Texto completo: `GET https://do-api-web-search.doe.sp.gov.br/v2/publications/{id}`
  (campo `content`, em HTML). Link público: `https://doe.sp.gov.br/{slug}`.

## Como acrescentar um diário estadual

1. Em `scripts/fontes.py`, escreva `def doe_xx(inicio, fim, falhas=None)` que
   devolva uma lista de dicts com as chaves: `id` (único e com prefixo da fonte,
   ex. `doemg:123`), `fonte`, `esfera="Estadual"`, `diario`, `data_publicacao`
   (AAAA-MM-DD), `titulo`, `orgao`, `tribunal_uf` (UF), `numero_processo` (pode ser ""),
   `classe` (""), `partes` ([]), `texto` (o texto **completo**, HTML ou texto puro)
   e `link`.
2. Use `pedir()` para as requisições, porque ele já faz as novas tentativas. Registre os
   problemas em `falhas`, sem levantar exceção.
3. Registre a função em `FONTES` com um nome curto (ex. `"doemg": doe_mg`).
4. Teste com `--fontes doemg --nivel-minimo baixa --brutos teste.json`. Confira
   no CSV se os anúncios reais ficaram com relevância `alta`.

Para descobrir a API de um diário, abra a busca do site no navegador com as
ferramentas do desenvolvedor (aba Rede) e veja qual requisição devolve os
resultados em JSON. A maioria dos diários novos funciona assim.

## Classificação (scripts/extrair.py)

- `RUIDO`: trechos apagados antes de classificar, como exigências de
  licitação, nomes de varas e rótulos de assunto do e-SAJ. Se aparecerem falsos
  positivos novos, o lugar de corrigir costuma ser aqui.
- `TIPOS`: lista ordenada de (tipo de ato, nível, regex). O primeiro que casar vence.
- `CLASSES_RELACIONADAS`: classes do DJEN que fazem a publicação contar como do
  próprio caso de insolvência.
