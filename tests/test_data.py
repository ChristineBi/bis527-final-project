"""Checks that fail when the database is wrong.

Run after the pipeline:  python -m pytest -q
"""
import sys
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.config import (BULLETIN_2024, BULLETIN_BIRTHS, DB_PATH,  # noqa
                             STUDY_YEARS)

# TabNet matched the bulletin exactly when we built this (data as of
# June 30, 2025). Allow a little room in case DATASUS updates TabNet.
CASE_TOLERANCE = 0.02
BIRTH_TOLERANCE = 0.01

# Real IBGE codes whose last digit does not follow the check-digit rule.
CHECK_DIGIT_EXCEPTIONS = {"2201919", "2201988", "2202251", "2611533",
                          "3117836", "3152131", "4305871", "5203939",
                          "5203962"}


@pytest.fixture(scope="module")
def con():
    if not DB_PATH.exists():
        pytest.skip("database not built yet; run python run_pipeline.py")
    c = duckdb.connect(str(DB_PATH), read_only=True)
    yield c
    c.close()


def one(con, sql):
    return con.execute(sql).fetchone()[0]


def check_digit(code6):
    total = 0
    for i, ch in enumerate(code6):
        product = int(ch) * (1 if i % 2 == 0 else 2)
        total += product // 10 + product % 10
    return (10 - total % 10) % 10


def test_municipality_count(con):
    n = one(con, "SELECT count(*) FROM municipalities")
    assert 5560 <= n <= 5575, n


def test_municipality_codes_unique(con):
    assert one(con, "SELECT count(*) - count(DISTINCT code7) "
                    "FROM municipalities") == 0
    assert one(con, "SELECT count(*) - count(DISTINCT code6) "
                    "FROM municipalities") == 0


def test_municipality_check_digits(con):
    codes = [r[0] for r in con.execute(
        "SELECT code7 FROM municipalities").fetchall()]
    bad = [c for c in codes if c not in CHECK_DIGIT_EXCEPTIONS
           and check_digit(c[:6]) != int(c[6])]
    assert bad == []


def test_six_digit_code_is_prefix(con):
    assert one(con, "SELECT count(*) FROM municipalities "
                    "WHERE code6 <> left(code7, 6)") == 0


def test_all_priority_municipalities_matched(con):
    assert one(con, "SELECT count(*) FROM priority") == 100
    assert one(con, "SELECT count(*) FROM priority p JOIN municipalities m "
                    "ON m.code7 = p.code_ibge7") == 100


@pytest.mark.parametrize("table", ["tabnet_gestational_cases",
                                   "tabnet_congenital_cases", "tabnet_births"])
def test_every_study_year_present(con, table):
    years = {r[0] for r in con.execute(
        f"SELECT DISTINCT year FROM {table}").fetchall()}
    assert set(STUDY_YEARS) - years == set()


def test_no_negative_values(con):
    assert one(con, "SELECT count(*) FROM panel WHERE gestational_cases < 0 "
                    "OR congenital_cases < 0 OR births < 0") == 0


def test_panel_has_every_municipality_every_year(con):
    n_muni = one(con, "SELECT count(*) FROM municipalities")
    rows = con.execute("SELECT year, count(*) FROM panel GROUP BY 1").fetchall()
    assert sorted(y for y, _ in rows) == STUDY_YEARS
    assert all(n == n_muni for _, n in rows)


def test_births_match_bulletin_denominator(con):
    """The bulletin's '2024' births are SINASC's 2023 count."""
    year, target = BULLETIN_BIRTHS["year"], BULLETIN_BIRTHS["births"]
    ours = one(con, f"SELECT coalesce(sum(value), 0) FROM tabnet_births "
                    f"WHERE year = {year}")
    assert abs(ours - target) / target <= BIRTH_TOLERANCE, (ours, target)


def test_births_change_little_between_years(con):
    """Catch a missing or half-loaded year: national births never change by
    more than 15% from one year to the next."""
    totals = dict(con.execute(
        "SELECT year, sum(births) FROM births GROUP BY 1").fetchall())
    for year in STUDY_YEARS[1:]:
        change = abs(totals[year] - totals[year - 1]) / totals[year - 1]
        assert change < 0.15, (year, totals[year - 1], totals[year])


@pytest.mark.parametrize("view,key", [("gestational_cases", "gestational"),
                                      ("congenital_cases", "congenital")])
def test_cases_2024_match_bulletin(con, view, key):
    ours = one(con, f"SELECT coalesce(sum(cases), 0) FROM {view} "
                    f"WHERE year = 2024")
    target = BULLETIN_2024[key]
    assert abs(ours - target) / target <= CASE_TOLERANCE, (ours, target)


@pytest.mark.parametrize("table", ["tabnet_gestational_cases",
                                   "tabnet_congenital_cases", "tabnet_births"])
def test_counts_are_placed_in_municipalities(con, table):
    """Almost every case and birth should match a real municipality."""
    share = one(con, f"""
        SELECT coalesce(sum(t.value) FILTER (WHERE m.code6 IS NULL), 0)
               / sum(t.value)
        FROM {table} t LEFT JOIN municipalities m ON m.code6 = t.code6
        WHERE t.year BETWEEN {STUDY_YEARS[0]} AND {STUDY_YEARS[-1]}""")
    assert share < 0.005, share
