"""Member 1: build the health-region-year panel and its checks.

Writes to data/shared/ (kept in Git so the whole team uses one snapshot):
  region_panel.csv   one row per health region and year, 2013-2024:
                     health_region, health_region_name, uf, year,
                     Y (congenital cases), B (live births),
                     rate_per_1000 (computed after summing),
                     n_municipalities
  data_checks.csv    every check, its value, what we expected, pass/fail
  exclusions_log.csv counts left out of the panel or worth a second look

Rules (see docs/data_dictionary.md):
  - One fixed mapping of municipality -> health region (geobr, 2023).
  - Cases and births are summed first; the rate is computed after summing.
  - TabNet leaves out municipalities with no cases in any year, so a
    missing municipality-year means zero cases REPORTED. This is recorded in
    the dictionary; it is not an unknown count.
  - Cases or births whose municipality is unknown cannot be placed in a
    region. They are left out and listed in the exclusions log.
"""
import csv
from pathlib import Path

import duckdb

from . import tabnet
from .config import (BULLETIN_2024, BULLETIN_BIRTHS, DB_PATH, RAW, ROOT,
                     STUDY_YEARS)

SHARED = ROOT / "data" / "shared"
EXPECTED_REGIONS = 450

# The TabNet query each count must come from (checked against the manifest).
EXPECTED_QUERIES = {
    "congenital_cases": ["Linha=Munic%EDpio_de_resid%EAncia",
                         "Coluna=Ano_Diagn%F3stico",
                         "Incremento=Casos_confirmados"],
    "births": ["Linha=Munic%EDpio", "Coluna=Ano_do_nascimento",
               "Incremento=Nascim_p%2Fresid.m%E3e"],
}


class Checks:
    def __init__(self):
        self.rows = []

    def add(self, check, value, expected=None, ok=None, year="", note=""):
        if ok is None:
            status = "info"
        else:
            status = "pass" if ok else "FAIL"
        self.rows.append({"check": check, "year": year, "value": value,
                          "expected": "" if expected is None else expected,
                          "status": status, "note": note})

    def failures(self):
        return [r for r in self.rows if r["status"] == "FAIL"]


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def raw_yearly_totals(name):
    """Re-read the saved TabNet page and total it by year, independently of
    the database, to confirm the database matches the raw query."""
    page = (RAW / "tabnet" / f"{name}.html").read_text(
        encoding=tabnet.ENCODING)
    totals = {}
    for r in tabnet.long_rows(tabnet.extract_table(page), "year"):
        if r["year"].isdigit():
            totals[int(r["year"])] = totals.get(int(r["year"]), 0) + r["value"]
    return totals


def run():
    con = duckdb.connect(str(DB_PATH), read_only=True)
    checks = Checks()
    first, last = STUDY_YEARS[0], STUDY_YEARS[-1]

    def one(sql):
        return con.execute(sql).fetchone()[0]

    # Fixed municipality -> region mapping. Codes are cleaned to plain
    # integers as text ('11005', not '11005.0').
    con.execute("""
        CREATE TEMP TABLE mapping AS
        SELECT code6, uf, health_region_name,
               CAST(CAST(CAST(health_region AS DOUBLE) AS BIGINT) AS VARCHAR)
                   AS health_region
        FROM municipalities
    """)

    # ---- the mapping ----
    n_regions = one("SELECT count(DISTINCT health_region) FROM mapping")
    checks.add("health regions in the mapping", n_regions,
               EXPECTED_REGIONS, n_regions == EXPECTED_REGIONS)
    unmapped = one("SELECT count(*) FROM mapping WHERE health_region IS NULL")
    checks.add("municipalities without a health region", unmapped, 0,
               unmapped == 0)
    dup_muni = one("SELECT count(*) - count(DISTINCT code6) FROM mapping")
    checks.add("municipalities listed twice in the mapping", dup_muni, 0,
               dup_muni == 0)
    cross = one("""SELECT count(*) FROM (SELECT health_region FROM mapping
                   GROUP BY 1 HAVING count(DISTINCT uf) > 1)""")
    checks.add("health regions that cross a state line", cross, 0,
               cross == 0)

    # ---- the region panel: sum first, rate after ----
    con.execute(f"""
        CREATE TEMP TABLE muni_year AS
        WITH years AS (SELECT range AS year FROM range({first}, {last + 1}))
        SELECT m.code6, m.health_region, m.health_region_name, m.uf, y.year,
               coalesce(c.y, 0) AS y, coalesce(b.b, 0) AS b
        FROM mapping m CROSS JOIN years y
        LEFT JOIN (SELECT code6, year, sum(value) AS y
                   FROM tabnet_congenital_cases WHERE code6 IS NOT NULL
                   GROUP BY 1, 2) c ON c.code6 = m.code6 AND c.year = y.year
        LEFT JOIN (SELECT code6, year, sum(value) AS b
                   FROM tabnet_births WHERE code6 IS NOT NULL
                   GROUP BY 1, 2) b ON b.code6 = m.code6 AND b.year = y.year
    """)
    panel = con.execute("""
        SELECT health_region, any_value(health_region_name) AS health_region_name,
               any_value(uf) AS uf, year,
               CAST(sum(y) AS INTEGER) AS Y, CAST(sum(b) AS INTEGER) AS B,
               round(1000.0 * sum(y) / nullif(sum(b), 0), 4) AS rate_per_1000,
               count(*) AS n_municipalities
        FROM muni_year GROUP BY health_region, year
        ORDER BY uf, health_region, year
    """).fetchall()
    fields = ["health_region", "health_region_name", "uf", "year", "Y", "B",
              "rate_per_1000", "n_municipalities"]
    rows = [dict(zip(fields, r)) for r in panel]
    write_csv(SHARED / "region_panel.csv", rows, fields)

    expected_rows = n_regions * len(STUDY_YEARS)
    checks.add("rows in region_panel.csv", len(rows), expected_rows,
               len(rows) == expected_rows)
    keys = {(r["health_region"], r["year"]) for r in rows}
    checks.add("duplicate (health_region, year) keys", len(rows) - len(keys),
               0, len(rows) == len(keys))
    missing = sum(1 for r in rows for f in fields if r[f] is None)
    checks.add("missing values in region_panel.csv", missing, 0, missing == 0)
    no_births = sum(1 for r in rows if not r["B"] or r["B"] <= 0)
    checks.add("region-years with births <= 0", no_births, 0, no_births == 0)
    zero_y = sum(1 for r in rows if r["Y"] == 0)
    checks.add("region-years with zero congenital cases", zero_y,
               note="real zeros: no case reported for any town in the region")

    # ---- totals before and after aggregating, by year ----
    for year in STUDY_YEARS:
        y_muni, b_muni = con.execute(
            f"SELECT sum(y), sum(b) FROM muni_year WHERE year = {year}"
        ).fetchone()
        y_reg = sum(r["Y"] for r in rows if r["year"] == year)
        b_reg = sum(r["B"] for r in rows if r["year"] == year)
        checks.add("congenital cases: municipalities vs regions", y_reg,
                   y_muni, y_reg == y_muni, year)
        checks.add("births: municipalities vs regions", b_reg, b_muni,
                   b_reg == b_muni, year)

    # ---- national totals (all TabNet rows) vs the included sample ----
    exclusions = []
    for measure, table, column in (("congenital cases", "tabnet_congenital_cases", "Y"),
                                   ("births", "tabnet_births", "B")):
        for year in STUDY_YEARS:
            national = one(f"SELECT coalesce(sum(value), 0) FROM {table} "
                           f"WHERE year = {year}")
            included = sum(r[column] for r in rows if r["year"] == year)
            checks.add(f"{measure}: national total vs included in panel",
                       included, national, None, year,
                       f"{national - included:,} left out "
                       f"(unknown municipality); see exclusions_log.csv")
        for name, code6, year, value in con.execute(f"""
                SELECT t.name, t.code6, t.year, sum(t.value)
                FROM {table} t LEFT JOIN mapping m ON m.code6 = t.code6
                WHERE m.code6 IS NULL AND t.value > 0
                  AND t.year BETWEEN {first} AND {last}
                GROUP BY 1, 2, 3 ORDER BY 3, 1""").fetchall():
            exclusions.append({
                "measure": measure, "year": year, "code6": code6 or "",
                "name": name, "value": value, "action": "left out",
                "reason": "municipality unknown, so it cannot be placed in "
                          "a health region"})

    for code6, name, uf, year in con.execute("""
            SELECT m.code6, mu.name, m.uf, m.year FROM muni_year m
            JOIN municipalities mu ON mu.code6 = m.code6
            WHERE m.b = 0 ORDER BY 4, 1""").fetchall():
        exclusions.append({
            "measure": "births", "year": year, "code6": code6,
            "name": f"{name} ({uf})", "value": 0, "action": "kept",
            "reason": "no live births reported this year; kept because its "
                      "region total is still positive; worth confirming"})
    write_csv(SHARED / "exclusions_log.csv", exclusions,
              ["measure", "year", "code6", "name", "value", "action",
               "reason"])

    # ---- bulletin cross-checks (full national totals, not the sample) ----
    nat_y = one("SELECT sum(value) FROM tabnet_congenital_cases "
                "WHERE year = 2024")
    checks.add("national congenital cases vs bulletin", nat_y,
               BULLETIN_2024["congenital"],
               nat_y == BULLETIN_2024["congenital"], 2024,
               "Boletim Epidemiologico de Sifilis 2025, Table 1")
    nat_b = one(f"SELECT sum(value) FROM tabnet_births "
                f"WHERE year = {BULLETIN_BIRTHS['year']}")
    checks.add("national births vs bulletin denominator", nat_b,
               BULLETIN_BIRTHS["births"], nat_b == BULLETIN_BIRTHS["births"],
               BULLETIN_BIRTHS["year"],
               "the bulletin divides 2024 cases by 2023 births")

    # ---- the database matches the raw TabNet records ----
    manifest_path = RAW / "tabnet" / "manifest.csv"
    with open(manifest_path, newline="", encoding="utf-8") as f:
        manifest = {r["name"]: r for r in csv.DictReader(f)}
    for name, needles in EXPECTED_QUERIES.items():
        fields_sent = manifest.get(name, {}).get("fields", "")
        ok = all(n in fields_sent for n in needles)
        checks.add(f"{name}: TabNet query is by residence and year", ok, True,
                   ok, note=f"retrieved {manifest.get(name, {}).get('retrieved_utc', '?')} UTC")
    for name, table in (("congenital_cases", "tabnet_congenital_cases"),
                        ("births", "tabnet_births")):
        raw = raw_yearly_totals(name)
        for year in STUDY_YEARS:
            db_total = one(f"SELECT coalesce(sum(value), 0) FROM {table} "
                           f"WHERE year = {year}")
            checks.add(f"{name}: database vs raw TabNet page", db_total,
                       raw.get(year, 0), db_total == raw.get(year, 0), year)

    con.close()
    write_csv(SHARED / "data_checks.csv", checks.rows,
              ["check", "year", "value", "expected", "status", "note"])

    failed = checks.failures()
    print(f"region: {len(rows):,} region-years written to "
          f"data/shared/region_panel.csv")
    print(f"region: {len(checks.rows)} checks, {len(failed)} failed "
          f"(data/shared/data_checks.csv)")
    print(f"region: {len(exclusions)} entries in data/shared/exclusions_log.csv")
    for r in failed:
        print(f"  FAILED: {r['check']} {r['year']}: got {r['value']}, "
              f"expected {r['expected']}")
