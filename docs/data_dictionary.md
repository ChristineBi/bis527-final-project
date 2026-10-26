# Data dictionary (Member 1)

Files in `data/shared/`, made by `python run_pipeline.py region` (the last
step of `python run_pipeline.py`). They are kept in Git so the whole team
uses the same snapshot.

## region_panel.csv

One row per health region and year: 450 regions × 12 years (2013–2024) =
5,400 rows. 2013 is there only to give 2014 its previous-year value.

| Column | Meaning |
|---|---|
| `health_region` | Health region (Região de Saúde, CIR) code, as text, e.g. `11005`. Keep it as text. |
| `health_region_name` | Region name. |
| `uf` | State abbreviation. Every region is inside one state. |
| `year` | Year of diagnosis (cases) and year of birth (births). |
| `Y` | Congenital syphilis cases: confirmed cases by the mother's municipality of residence and year of diagnosis, summed over the region's municipalities. |
| `B` | Live births by the mother's municipality of residence, summed over the region's municipalities. |
| `rate_per_1000` | `1000 * Y / B`, computed after summing. |
| `n_municipalities` | Number of municipalities in the region. |

## Where the numbers come from

| Count | Source | TabNet query |
|---|---|---|
| `Y` | SINAN, Sífilis Congênita, via DATASUS TabNet | rows: Município de residência; columns: Ano Diagnóstico; measure: Casos confirmados; all files |
| `B` | SINASC, Nascidos Vivos, via DATASUS TabNet | rows: Município; columns: Ano do nascimento; measure: Nascimentos por residência da mãe |
| Regions | geobr (IPEA): municipality boundaries 2022, health regions 2023 | |

The exact query sent and the download date for each table are in
`data/raw/tabnet/manifest.csv`; the raw TabNet pages are next to it. TabNet
data are as of June 30, 2025; 2024 is preliminary.

## Rules

- **One fixed mapping.** Each municipality belongs to the health region it
  had in geobr's 2023 health-region file, for every year.
- **Sum first, then rate.** Cases and births are added up across a region's
  municipalities, then divided.
- **Zeros.** TabNet does not list a municipality that had no cases in any
  year, so a municipality with no TabNet row has zero cases *reported*. These
  are real zeros, not unknown values. 236 of the 5,400 region-years have
  `Y = 0`.
- **Unknown municipality.** A few cases and births are recorded only as
  "municipality ignored" for a state. They cannot be placed in a region, so
  they are left out and listed in `exclusions_log.csv`. Over 2013–2024 this is
  8 congenital cases and 1,140 births nationally (under 0.01%).
- **Births of a single year.** Each year's rate uses that year's births. The
  2025 bulletin divided 2024 cases by 2023 births, so our 2024 rates are
  higher than the bulletin's.

## Totals: full national vs. our sample

National totals (every TabNet row, including unknown municipality) are kept
separate from the totals in `region_panel.csv`; `data_checks.csv` lists both
for every year. The national 2024 congenital total, 24,443, matches the 2025
bulletin exactly.

## data_checks.csv

One row per check: `check`, `year` (if by year), `value`, `expected`,
`status` (`pass`, `FAIL`, or `info` for numbers recorded without a
pass/fail rule), and `note`. Checks include: 450 regions; no municipality
without a region; no region crossing a state line; no duplicate keys or
missing values; births above zero in every region-year; region totals equal
municipality totals every year; national totals vs. the bulletin; the
database vs. a fresh read of the raw TabNet pages; and that each TabNet query
was by residence and year.

## exclusions_log.csv

`measure`, `year`, `code6`, `name`, `value`, `action` (`left out` or
`kept`), `reason`. It lists the unknown-municipality counts that were left
out, and municipality-years worth a second look (one municipality-year with
zero births: Borá, SP, 2023; kept, since its region's births are still above
zero).

## Reproducing one regional total (for Member 3)

Pick a region and year in `region_panel.csv`, then from
`data/processed/panel.csv` keep the rows with that `health_region` and
`year` (match `health_region` as a number, since `panel.csv` may show it as
`11005.0`), and add up `congenital_cases` and `births`. They should equal `Y`
and `B`, and `1000 * Y / B` should equal `rate_per_1000`.
