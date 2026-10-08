"""Load everything into one DuckDB database (db/syphilis.duckdb).

Tables
  municipalities                 one row per municipality, with boundary
                                 (WKB) and health region
  priority                       the 100 Sifilis Nao priority municipalities
  tabnet_gestational_cases       TabNet counts, long format (includes rows
  tabnet_congenital_cases        for 'ignored' places with code6 = NULL)
  tabnet_births
  congenital_prenatal_care       congenital cases by municipality, year,
  congenital_maternal_diagnosis  and category (descriptive aim)

Views
  gestational_cases, congenital_cases, births   per municipality-year
  panel   municipality x year for 2013-2024 with cases, births, and the
          priority flag; zero where nothing was reported
"""
import duckdb

from .config import DB_PATH, PROCESSED, REFERENCE, STUDY_YEARS

COUNT_FILES = {
    "tabnet_gestational_cases": "gestational_cases.csv",
    "tabnet_congenital_cases": "congenital_cases.csv",
    "tabnet_births": "births.csv",
}
CATEGORY_FILES = {
    "congenital_prenatal_care": "congenital_prenatal_care.csv",
    "congenital_maternal_diagnosis": "congenital_maternal_diagnosis.csv",
}


def run():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH))
    p = PROCESSED.as_posix()

    con.execute(f"""
        CREATE OR REPLACE TABLE municipalities AS
        SELECT * FROM read_parquet('{p}/municipalities.parquet')
    """)
    con.execute(f"""
        CREATE OR REPLACE TABLE priority AS
        SELECT * FROM read_csv('{REFERENCE.as_posix()}/sifilis_nao_priority.csv',
                               all_varchar = true)
    """)
    for table, file in COUNT_FILES.items():
        con.execute(f"""
            CREATE OR REPLACE TABLE {table} AS
            SELECT code6, name, CAST(year AS INTEGER) AS year,
                   CAST(value AS INTEGER) AS value
            FROM read_csv('{p}/{file}', all_varchar = true)
        """)
    for table, file in CATEGORY_FILES.items():
        if (PROCESSED / file).exists():
            con.execute(f"""
                CREATE OR REPLACE TABLE {table} AS
                SELECT code6, name, CAST(year AS INTEGER) AS year, category,
                       CAST(value AS INTEGER) AS value
                FROM read_csv('{p}/{file}', all_varchar = true)
            """)

    for view, table, column in (
            ("gestational_cases", "tabnet_gestational_cases", "cases"),
            ("congenital_cases", "tabnet_congenital_cases", "cases"),
            ("births", "tabnet_births", "births")):
        con.execute(f"""
            CREATE OR REPLACE VIEW {view} AS
            SELECT code6, year, sum(value) AS {column}
            FROM {table} WHERE code6 IS NOT NULL
            GROUP BY code6, year
        """)

    first, last = STUDY_YEARS[0], STUDY_YEARS[-1]
    con.execute(f"""
        CREATE OR REPLACE VIEW panel AS
        WITH years AS (SELECT range AS year FROM range({first}, {last + 1}))
        SELECT m.code7, m.code6, m.name, m.uf, m.health_region, y.year,
               coalesce(g.cases, 0) AS gestational_cases,
               coalesce(c.cases, 0) AS congenital_cases,
               coalesce(b.births, 0) AS births,
               (pr.code6 IS NOT NULL) AS priority
        FROM municipalities m
        CROSS JOIN years y
        LEFT JOIN gestational_cases g ON g.code6 = m.code6 AND g.year = y.year
        LEFT JOIN congenital_cases c ON c.code6 = m.code6 AND c.year = y.year
        LEFT JOIN births b ON b.code6 = m.code6 AND b.year = y.year
        LEFT JOIN priority pr ON pr.code6 = m.code6
    """)

    con.execute(f"COPY (SELECT * FROM panel ORDER BY code6, year) "
                f"TO '{p}/panel.csv' (HEADER)")
    n = con.execute("SELECT count(*) FROM panel").fetchone()[0]
    print(f"database: {DB_PATH.name} built; panel has {n:,} rows "
          f"(also saved as data/processed/panel.csv)")
    con.close()
