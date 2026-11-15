---
name: diarios-falencias
description: Busca nos diários oficiais brasileiros — Diário Oficial da União (DOU), Diário de Justiça Eletrônico Nacional (DJEN/CNJ, com os 27 Tribunais de Justiça) e Diário Oficial do Estado de São Paulo — publicações de falência, recuperação judicial, recuperação extrajudicial, massa falida e liquidação extrajudicial de empresas, e grava os anúncios em CSV estruturado (empresa, CNPJ, processo, vara, administrador judicial, tipo de ato, link). Use sempre que o usuário quiser monitorar, levantar, coletar ou listar falências, quebras, recuperações judiciais ou empresas em insolvência publicadas em diário oficial, DOU, DJE, DJEN ou diário de justiça — inclusive pedidos como "quais empresas faliram ontem", "rode a coleta de falências de hoje", "atualize a planilha de recuperações judiciais" ou "veja se saiu alguma falência no diário", mesmo que o usuário não cite a palavra "diário".
---

# Coleta de falências e recuperações nos diários oficiais

Esta skill roda um coletor em Python que consulta as fontes oficiais, separa os
anúncios reais das menções de passagem e grava tudo num CSV acumulado, sem
duplicatas. O seu trabalho é rodar o coletor com os parâmetros certos, conferir
o resultado e apresentar um resumo útil ao usuário.

## Fontes cobertas

| Esfera | Fonte | O que traz |
|---|---|---|
| Federal | DOU (in.gov.br) | Liquidações extrajudiciais (BCB, ANS, SUSEP), editais de terceiros |
| Judicial | DJEN – comunicaapi.pje.jus.br | Publicações dos 27 TJs: decretação de falência, deferimento de RJ, editais de credores, habilitações etc. É a fonte principal. |
| Estadual | DOE-SP | Atos da Jucesp (anotação de falência/encerramento), leilões de massas, editais |

Detalhes técnicos das APIs e como acrescentar outros diários estaduais estão em
`references/fontes.md`. Leia esse arquivo só quando for mexer nos coletores ou
quando uma fonte falhar.

## Como rodar

O coletor está em `scripts/coletar.py` (caminho relativo a esta skill). Requer
Python 3.9+ com `requests` (já presente em instalações Anaconda; senão,
`pip install requests`).

```bash
python <skill>/scripts/coletar.py --saida <pasta>
```

Padrões: período = **ontem e hoje**; fontes = `dou,djen,doesp`; tribunais = os
27 TJs; pasta de saída = `./falencias`. Se o usuário não indicar a pasta, use
`falencias/` na raiz do projeto atual, para que o acumulado fique sempre no
mesmo lugar.

A execução completa (27 TJs, um dia) leva de 10 a 25 minutos, quase tudo
download: o DJEN limita a 20 consultas por minuto e o coletor respeita esse
limite. Com `--tribunais` restrito a poucos estados, leva 2 a 3 minutos. Rode em
segundo plano e avise o usuário que vai demorar. O progresso sai no stderr; o resumo em
JSON sai no stdout no final.

Opções úteis:

| Opção | Quando usar |
|---|---|
| `--fontes djen` / `--fontes dou,doesp` | O usuário quer só algumas fontes, ou uma fonte está fora do ar |
| `--tribunais TJSP,TJRJ` | Interesse restrito a alguns estados (fica bem mais rápido) |
| `--tribunais todos` | Incluir também os TRFs (casos com a União como parte) |
| `--data-inicio AAAA-MM-DD --data-fim AAAA-MM-DD` | Período diferente de ontem/hoje (ex.: segunda-feira cobrindo o fim de semana) |
| `--desde-ultima` | Execuções agendadas ou "atualize a planilha": começa na data mais recente já gravada e vai até hoje, cobrindo dias em que a coleta não rodou |
| `--nivel-minimo media` | O usuário quer também as **menções**: processos comuns em que uma das partes está em falência/RJ |
| `--brutos arq.json` / `--de-brutos arq.json` | Salvar o que foi baixado / reprocessar sem baixar de novo (para ajustar a classificação) |

Às segundas-feiras, ou se o usuário disser que não rodou a coleta em algum dia,
sugira ampliar `--data-inicio` para cobrir os dias perdidos. O CSV não duplica
nada, então sobrepor períodos é seguro.

## O que é gravado

Arquivos na pasta de saída:
- `anuncios_falencia.csv` — acumulado de todas as execuções (chave única: `id`).
- `novos_AAAA-MM-DD_HHMM.csv` — só o que entrou nesta execução.

CSV com separador `;` e codificação UTF-8 com BOM, para abrir direto no Excel em português.
Colunas:

`id, fonte, esfera, diario, data_publicacao, tipo_ato, relevancia, empresa, cnpj,
numero_processo, vara_orgao, tribunal_uf, classe_processual, administrador_judicial,
termos_encontrados, titulo, link, trecho, coletado_em`

- **tipo_ato**: Decretação de falência, Convolação em falência, Pedido de falência,
  Encerramento de falência, Deferimento de recuperação judicial, Concessão /
  homologação de plano, Assembleia geral de credores, Edital / habilitação de
  créditos, Alienação / leilão de bens da massa, Liquidação extrajudicial, e
  "Outros atos – …" quando é do processo mas sem ato específico identificado.
  "Decretação" e "Convolação" só são marcadas quando a própria publicação
  decide ("DECRETO A FALÊNCIA", "fixo o termo legal", "convolo"). Uma decisão
  que só cita uma falência antiga ("a quebra foi decretada em 2017") fica em
  "Outros atos – falência". Ainda assim, leia o `trecho` antes de afirmar ao
  usuário que uma falência foi decretada naquele dia.
- **relevancia**: `alta` = publicação do próprio caso de insolvência (no DJEN: a
  classe do processo é falência, RJ, habilitação/impugnação de crédito etc.; no
  DOU/DOE: o texto traz um ato ou edital típico). `media` = outro processo que
  só cita uma empresa falida ou em RJ. Por padrão só `alta` é gravada.
- **empresa / cnpj / administrador_judicial** são extraídos do texto por
  padrões; podem vir vazios ou com mais de um valor (separados por ` | `).
- **link**: no DJEN é a certidão oficial da publicação (PDF); no DOU e no DOE-SP, a página da matéria.

## Depois de rodar

1. Leia o JSON do stdout. Se `falhas` não estiver vazio, diga quais fontes ou
   tribunais falharam. O DJEN às vezes responde "sistema muito ocupado" por
   vários minutos. Ofereça rodar de novo só o que falhou, por exemplo
   `--fontes djen --tribunais TJMG`.
2. Apresente um resumo curto: quantos registros novos, a divisão por tipo de ato
   e, principalmente, os **atos centrais** (decretações, convolações, pedidos
   de falência, deferimentos de RJ, liquidações extrajudiciais), com empresa,
   tribunal e link. As habilitações e impugnações de crédito costumam ser a
   maioria e são menos interessantes. Cite só o total delas, a menos que o
   usuário peça.
3. Informe o caminho dos dois CSVs.

Não cole o CSV inteiro na conversa. São centenas de linhas por dia só no TJSP.

## Limitações (diga ao usuário quando for relevante)

- **Diários estaduais:** por enquanto só São Paulo. As publicações judiciais de
  todos os estados já vêm pelo DJEN. Os diários do executivo dos outros estados
  precisam de um coletor próprio cada (veja `references/fontes.md`).
- **CNPJ:** as intimações do DJEN raramente trazem o CNPJ, então a coluna fica
  vazia na maioria das linhas judiciais.
- **Várias empresas na mesma publicação:** publicações como as listas da Jucesp
  no DOE-SP citam muitas empresas. Ficam numa linha só, com até 5 nomes.
- **Extração por padrões de texto:** nomes de empresa e de administrador podem
  sair truncados ou errados em textos mal formatados. O `trecho` e o `link`
  permitem conferir.
