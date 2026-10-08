"""Download tables from DATASUS TabNet.

TabNet is the Ministry of Health's public tabulation site. It counts cases
the same way the national syphilis bulletin does: confirmed cases by the
mother's municipality of residence and year of diagnosis. (The DATASUS FTP
server with the raw files does not accept connections from outside Brazil,
so this is also the route that works for us.)

Each query fills in TabNet's web form, the same as clicking "Mostra" with
the "Colunas separadas por ;" output option. The raw response is saved to
data/raw/tabnet/ and parsed into a long table: one row per municipality,
year, and (for some tables) category.
"""
import csv
import hashlib
import html
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser

from .config import PROCESSED, RAW, STUDY_YEARS

BASE = "http://tabnet.datasus.gov.br/cgi"
ENCODING = "cp1252"  # TabNet pages and forms use Windows-1252
ALL = "TODAS_AS_CATEGORIAS__"
RAW_DIR = RAW / "tabnet"
MANIFEST = RAW_DIR / "manifest.csv"

GESTATIONAL = "sinannet/cnv/sifilisgestantebr.def"
CONGENITAL = "sinannet/cnv/sifilisbr.def"
BIRTHS = "sinasc/cnv/nvbr.def"

# Counts by municipality (rows) and year (columns).
COUNT_TABLES = {
    "gestational_cases": dict(form=GESTATIONAL,
                              row="Município_de_residência",
                              col="Ano_de_Diagnóstico",
                              measure="Casos_confirmados"),
    "congenital_cases": dict(form=CONGENITAL,
                             row="Município_de_residência",
                             col="Ano_Diagnóstico",
                             measure="Casos_confirmados"),
    "births": dict(form=BIRTHS,
                   row="Município",
                   col="Ano_do_nascimento",
                   measure="Nascim_p/resid.mãe",
                   files_for_study_years=True),
}

# Congenital cases by municipality (rows) and a category (columns), one
# query per year of diagnosis. Used for the descriptive aim.
CATEGORY_TABLES = {
    "congenital_prenatal_care": dict(form=CONGENITAL,
                                     row="Município_de_residência",
                                     col="Realizou_Pré-Natal",
                                     measure="Casos_confirmados",
                                     year_filter="SAno_Diagnóstico"),
    "congenital_maternal_diagnosis": dict(form=CONGENITAL,
                                          row="Município_de_residência",
                                          col="Sífilis_materna",
                                          measure="Casos_confirmados",
                                          year_filter="SAno_Diagnóstico"),
}


# ---------- reading the form ----------

class FormParser(HTMLParser):
    """Collect every <select> in the page: name -> [(value, label)]."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.selects = {}
        self._select = None
        self._option = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "select":
            self._select = attrs.get("name")
            self.selects.setdefault(self._select, [])
        elif tag == "option" and self._select is not None:
            self._finish_option()
            self._option = [attrs.get("value", ""), ""]

    def handle_data(self, data):
        if self._option is not None:
            self._option[1] += data

    def handle_endtag(self, tag):
        if tag in ("option", "select"):
            self._finish_option()
        if tag == "select":
            self._select = None

    def _finish_option(self):
        if self._option is not None and self._select is not None:
            value, label = self._option
            self.selects[self._select].append((value, " ".join(label.split())))
        self._option = None


def parse_form(page_html):
    parser = FormParser()
    parser.feed(page_html)
    parser.close()
    return parser.selects


# ---------- talking to TabNet ----------

def fetch(url, data=None, tries=4, timeout=600):
    request = urllib.request.Request(
        url, data=data, headers={"User-Agent": "bis527-syphilis-pipeline"})
    for attempt in range(1, tries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                return resp.read().decode(ENCODING, errors="replace")
        except OSError as err:  # includes URLError and timeouts
            if attempt == tries:
                raise
            wait = 15 * attempt
            print(f"    TabNet problem ({err}); retrying in {wait}s")
            time.sleep(wait)


def build_request(selects, row, col, measure, files, filters=None):
    """Form fields in the order the browser sends them."""
    pairs = [("Linha", row), ("Coluna", col), ("Incremento", measure)]
    pairs += [("Arquivos", f) for f in files]
    filters = filters or {}
    for name in selects:
        if name.startswith("S"):
            for value in filters.get(name, [ALL]):
                pairs.append((name, value))
    pairs += [("formato", "prn"), ("mostre", "Mostra")]
    return urllib.parse.urlencode(pairs, encoding=ENCODING).encode("ascii")


def check_choice(selects, field, value):
    values = [v for v, _ in selects.get(field, [])]
    if value not in values:
        raise ValueError(f"TabNet form has no {value!r} in {field}; "
                         f"choices are {values[:40]}")


def option_for_label(selects, field, label):
    for value, text in selects.get(field, []):
        if text == label:
            return value
    raise ValueError(f"no option labeled {label!r} in {field}")


# ---------- reading the result ----------

def extract_table(page_html):
    """Return the semicolon-separated table inside <PRE> as a list of rows."""
    match = re.search(r"<pre>(.*?)</pre>", page_html, re.S | re.I)
    if not match:
        text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ",
                                             page_html)).split())
        raise ValueError(f"TabNet returned no table: {text[:400]}")
    text = html.unescape(re.sub(r"<[^>]+>", "", match.group(1)))
    lines = [ln.strip() for ln in text.strip().splitlines()]
    lines = [ln for ln in lines if ln and ln != "&"]
    return list(csv.reader(lines, delimiter=";", quotechar='"'))


def to_number(cell):
    cell = cell.strip()
    if cell in ("-", ""):
        return 0
    return int(cell.replace(".", ""))


def split_place(label):
    """'522205 VICENTINOPOLIS' -> ('522205', 'VICENTINOPOLIS')."""
    match = re.match(r"^(\d{6,7})\s+(.*)$", label.strip())
    if not match:
        return None, label.strip()
    return match.group(1)[:6], match.group(2)


def long_rows(table, column_name):
    """Turn the wide TabNet table into rows of (code6, name, column, value).

    Skips the Total row and Total column. Rows whose label has no code
    (for example 'Ignorado ou exterior') get code6 = None.
    """
    header = table[0]
    out = []
    for row in table[1:]:
        if not row or row[0].strip() == "Total":
            continue
        code6, name = split_place(row[0])
        for label, cell in zip(header[1:], row[1:]):
            if label.strip() == "Total":
                continue
            out.append({"code6": code6, "name": name,
                        column_name: label.strip(), "value": to_number(cell)})
    return out


# ---------- running the queries ----------

def save_raw(name, page_html, url, fields):
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / f"{name}.html"
    path.write_text(page_html, encoding=ENCODING, errors="replace")
    rows = []
    if MANIFEST.exists():
        with open(MANIFEST, newline="", encoding="utf-8") as f:
            rows = [r for r in csv.DictReader(f) if r["name"] != name]
    rows.append({
        "name": name, "url": url, "fields": fields,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "retrieved_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
    })
    with open(MANIFEST, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda r: r["name"]))


def write_csv(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


_forms = {}


def get_form(form):
    if form not in _forms:
        _forms[form] = parse_form(fetch(f"{BASE}/deftohtm.exe?{form}"))
    return _forms[form]


def run_query(name, spec, filters=None):
    selects = get_form(spec["form"])
    for field, key in (("Linha", "row"), ("Coluna", "col"),
                       ("Incremento", "measure")):
        check_choice(selects, field, spec[key])
    files = [v for v, label in selects["Arquivos"]
             if not spec.get("files_for_study_years")
             or (label.isdigit() and int(label) in STUDY_YEARS)]
    data = build_request(selects, spec["row"], spec["col"], spec["measure"],
                         files, filters)
    url = f"{BASE}/tabcgi.exe?{spec['form']}"
    page = fetch(url, data)
    save_raw(name, page, url, data.decode("ascii"))
    return extract_table(page)


def run():
    for name, spec in COUNT_TABLES.items():
        print(f"tabnet: {name} ...", end=" ", flush=True)
        table = run_query(name, spec)
        rows = long_rows(table, "year")
        rows = [r for r in rows if r["year"].isdigit()]  # drop blank year
        write_csv(PROCESSED / f"{name}.csv", rows,
                  ["code6", "name", "year", "value"])
        total_2024 = sum(r["value"] for r in rows if r["year"] == "2024")
        print(f"{len(table) - 2} places, 2024 total {total_2024:,}")

    for name, spec in CATEGORY_TABLES.items():
        print(f"tabnet: {name} (one query per year)")
        selects = get_form(spec["form"])
        all_rows = []
        for year in STUDY_YEARS:
            option = option_for_label(selects, spec["year_filter"], str(year))
            table = run_query(f"{name}_{year}", spec,
                              filters={spec["year_filter"]: [option]})
            for r in long_rows(table, "category"):
                r["year"] = year
                all_rows.append(r)
            print(f"  {year}: {len(table) - 2} places")
        write_csv(PROCESSED / f"{name}.csv", all_rows,
                  ["code6", "name", "year", "category", "value"])
