# diarios-falencias

Agent skill para Claude que busca nos diários oficiais brasileiros publicações de
falência, recuperação judicial e extrajudicial, massa falida e liquidação
extrajudicial, e grava os anúncios em CSV estruturado.

Fontes: Diário Oficial da União (DOU), Diário de Justiça Eletrônico Nacional
(DJEN/CNJ, 27 Tribunais de Justiça) e Diário Oficial do Estado de São Paulo.

## Instalação

Copie esta pasta para `.claude/skills/diarios-falencias` no seu projeto (ou em
`~/.claude/skills/`). Requer Python 3.9+ com `requests`.

## Uso direto

```bash
python scripts/coletar.py --saida falencias
python scripts/coletar.py --saida falencias --desde-ultima
python scripts/coletar.py --saida falencias --tribunais TJSP,TJRJ --data-inicio 2026-11-01 --data-fim 2026-11-07
```

Instruções completas para o agente em [SKILL.md](SKILL.md); detalhes das APIs em
[references/fontes.md](references/fontes.md). Casos de avaliação em `evals/`.

## API e dados coletados

- `api/servidor.py`: API somente leitura (Flask) sobre `falencias/anuncios_falencia.csv`,
  com filtros, paginação, exportação em CSV e resumo. `pip install flask` e
  `python api/servidor.py` (http://127.0.0.1:8000).
- `falencias/`: planilha acumulada, os CSVs de cada execução e o
  `coletar_agendado.cmd` usado no Agendador do Windows (os caminhos dele são
  desta máquina; ajuste ao instalar em outra).

## Versões

- **v1.1.0**: opção `--desde-ultima`; decretação/convolação só quando a própria
  publicação decide; filtro de relevância aplicado antes da extração; evals.
- **v1.0.0**: primeira versão (DOU, DJEN, DOE-SP).
