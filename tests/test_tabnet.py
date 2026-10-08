"""Tests for reading TabNet pages, using real pages saved in tests/fixtures.

These run without internet access.
"""
import sys
import urllib.parse
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline import tabnet  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def read(name):
    return (FIXTURES / name).read_text(encoding=tabnet.ENCODING)


@pytest.fixture(scope="module")
def selects():
    return tabnet.parse_form(read("tabnet_form_sample.html"))


def test_form_has_the_fields_we_use(selects):
    for field in ("Linha", "Coluna", "Incremento", "Arquivos",
                  "SAno_Diagnóstico", "SRealizou_Pré-Natal"):
        assert field in selects


def test_option_labels_are_decoded(selects):
    labels = dict(selects["SSífilis_materna"])
    assert labels["2"] == "Durante o pré-natal"
    assert dict(selects["Arquivos"])["sifcbr24.dbf"] == "2024"


def test_option_for_label(selects):
    assert tabnet.option_for_label(selects, "SAno_Diagnóstico",
                                   "1975") == "3"
    with pytest.raises(ValueError):
        tabnet.option_for_label(selects, "SAno_Diagnóstico", "1850")


def test_check_choice_rejects_unknown_row(selects):
    tabnet.check_choice(selects, "Linha", "Ano_Diagnóstico")
    with pytest.raises(ValueError):
        tabnet.check_choice(selects, "Linha", "Not_a_field")


def test_request_is_windows_1252_and_has_all_filters(selects):
    body = tabnet.build_request(selects, "Município_de_residência",
                                "Ano_Diagnóstico", "Casos_confirmados",
                                ["sifcbr24.dbf"],
                                filters={"SAno_Diagnóstico": ["3"]})
    text = body.decode("ascii")
    assert "Linha=Munic%EDpio_de_resid%EAncia" in text  # cp1252 bytes
    pairs = urllib.parse.parse_qsl(text, encoding=tabnet.ENCODING)
    names = [k for k, _ in pairs]
    filters = [n for n in selects if n.startswith("S")]
    assert all(n in names for n in filters)
    assert ("SAno_Diagnóstico", "3") in pairs
    assert ("SAno_Diagnóstico", tabnet.ALL) not in pairs
    assert ("formato", "prn") in pairs


def test_extract_table_from_real_result():
    table = tabnet.extract_table(read("tabnet_result_sample.html"))
    assert table[0][0] == "UF de residência"
    assert table[0][-1] == "Total"
    assert table[-1][0] == "Total"
    by_label = {row[0]: row for row in table}
    assert by_label["35 São Paulo"][-1] == "4234"


def test_long_rows_and_totals_add_up():
    table = tabnet.extract_table(read("tabnet_result_sample.html"))
    rows = tabnet.long_rows(table, "year")
    total_row = table[-1]
    for i, year in enumerate(table[0][1:-1], start=1):
        ours = sum(r["value"] for r in rows if r["year"] == year)
        assert ours == tabnet.to_number(total_row[i]), year


def test_split_place():
    assert tabnet.split_place("522205 VICENTINOPOLIS") == (
        "522205", "VICENTINOPOLIS")
    assert tabnet.split_place("3550308 São Paulo") == ("355030", "São Paulo")
    assert tabnet.split_place("Ignorado ou exterior") == (
        None, "Ignorado ou exterior")


def test_dash_means_zero():
    assert tabnet.to_number("-") == 0
    assert tabnet.to_number("1443") == 1443


def test_page_without_table_raises():
    with pytest.raises(ValueError):
        tabnet.extract_table("<html><body>Erro na tabulação</body></html>")
