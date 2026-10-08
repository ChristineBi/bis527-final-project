# BIS 527 project data pipeline

Builds the database for our project on maternal and congenital syphilis in
Brazilian municipalities, 2013–2024. One command downloads the public data,
loads it into a DuckDB database, and checks it.

## Setup (once)

Needs Python 3.10 or newer. With conda:

```bash
cd ~/bis527-final-project
conda create -n bis527 python=3.12 -y
conda activate bis527
pip install -r requirements.txt
```

## Run

```bash
conda activate bis527
python run_pipeline.py          # all steps, about 10-20 minutes
python -m pytest -q             # data checks
```

You can also run one step at a time, for example
`python run_pipeline.py tabnet`. Each run writes a log to `logs/`.

| Step | What it does |
|------|--------------|
| `tabnet` | Downloads counts from DATASUS TabNet: syphilis in pregnancy and congenital syphilis by mother's municipality of residence and year of diagnosis (SINAN), live births by mother's municipality of residence and year (SINASC), and congenital cases by prenatal care and by when the mother was diagnosed. Raw responses are kept in `data/raw/tabnet/` with a manifest of every query. |
| `boundaries` | Downloads municipal boundaries (2022) and health regions (2023) with the geobr package. |
| `build` | Loads everything into `db/syphilis.duckdb` and saves the analysis panel as `data/processed/panel.csv`. |
| `check` | Writes `data/processed/check_report.txt`: yearly national totals, the 2024 totals next to the Ministry's bulletin, and how many counts could not be placed in a municipality. |

## Why TabNet

TabNet is the Ministry of Health's own tabulation site, and it counts
confirmed cases the same way the national syphilis bulletin does. When we
built this, its 2024 case totals matched the 2025 bulletin exactly: 89,724
cases in pregnancy and 24,443 congenital cases.

Births: the bulletin lists 2,537,576 live births for 2024, but that is the
SINASC count for 2023. The bulletin divided 2024 cases by 2023 births,
probably because 2024 births were not final yet. We use each year's own
births (2,389,325 in 2024), so our 2024 rates are higher than the
bulletin's (for example 37.6 instead of 35.4 per 1,000 for syphilis in
pregnancy).

The raw microdata files are on the DATASUS FTP server, but that server does
not accept connections from outside Brazil. The optional `download` and
`convert` steps (`pipeline/download.py`, `pipeline/convert.py`,
`pipeline/dbf.py`) can fetch and read them from a Brazilian connection if we
ever need record-level data.

## Using the database

The main view is `panel`: one row per municipality and year (2013–2024)
with `gestational_cases`, `congenital_cases`, `births`, `priority`
(Sífilis Não), and `health_region`. If you just want a spreadsheet, use
`data/processed/panel.csv`.

Other tables: `congenital_prenatal_care` and
`congenital_maternal_diagnosis` (congenital cases by municipality, year,
and category), and `municipalities` (with each boundary in `geom_wkb` for
building neighbor networks: `LOAD spatial; ST_GeomFromWKB(geom_wkb)`).

From R:

```r
library(duckdb)
con <- dbConnect(duckdb(), "db/syphilis.duckdb", read_only = TRUE)
panel <- dbGetQuery(con, "SELECT * FROM panel")
```

From Python:

```python
import duckdb
con = duckdb.connect("db/syphilis.duckdb", read_only=True)
panel = con.sql("SELECT * FROM panel").df()
```

## Things to know

- Municipality codes: IBGE uses 7 digits; SINAN and SINASC use 6 (the
  7th is a check digit). The database has both, `code7` and `code6`, and
  joins on `code6`.
- Cases whose municipality is unknown ("Ignorado ou exterior") are kept in
  the `tabnet_*` tables with an empty `code6` but are not in `panel`.
- TabNet data are as of June 30, 2025, and 2024 is still preliminary.
- `data/reference/sifilis_nao_priority.csv` is the Ministry's 2017 list of
  100 priority municipalities, matched to IBGE codes by
  `scripts/match_priority_list.py`.
- `tests/test_tabnet.py` checks the TabNet parsing against saved real
  pages and runs without internet; `tests/test_data.py` checks the built
  database.
