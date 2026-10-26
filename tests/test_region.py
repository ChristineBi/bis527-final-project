"""Checks on the Member 1 deliverables in data/shared/.

Run after `python run_pipeline.py`:  python -m pytest -q
"""
import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.config import STUDY_YEARS  # noqa: E402
from pipeline.region import EXPECTED_REGIONS, SHARED  # noqa: E402


def read(name):
    path = SHARED / name
    if not path.exists():
        pytest.skip(f"{name} not built yet; run python run_pipeline.py")
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def panel():
    return read("region_panel.csv")


def test_no_failed_checks():
    failed = [r for r in read("data_checks.csv") if r["status"] == "FAIL"]
    assert failed == []


def test_one_row_per_region_and_year(panel):
    keys = {(r["health_region"], r["year"]) for r in panel}
    assert len(keys) == len(panel) == EXPECTED_REGIONS * len(STUDY_YEARS)
    assert sorted({int(r["year"]) for r in panel}) == STUDY_YEARS


def test_region_codes_are_plain_integers(panel):
    assert all(r["health_region"].isdigit() for r in panel)


def test_counts_are_whole_and_births_positive(panel):
    for r in panel:
        assert int(r["Y"]) >= 0
        assert int(r["B"]) > 0, r


def test_rate_is_computed_after_summing(panel):
    for r in panel:
        expected = 1000 * int(r["Y"]) / int(r["B"])
        assert abs(float(r["rate_per_1000"]) - expected) < 1e-3, r


def test_each_region_stays_in_one_state(panel):
    states = {}
    for r in panel:
        states.setdefault(r["health_region"], set()).add(r["uf"])
    assert all(len(s) == 1 for s in states.values())
