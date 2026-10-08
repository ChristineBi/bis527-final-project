"""Turn the raw .dbc files into files the database can load.

SINAN: each yearly file is converted to Parquet with every column kept as
text, so we can still change case definitions later without re-reading the
raw files.

SINASC: we only need the number of live births per municipality of
residence and year, so each state-year file is reduced to those counts.
"""
import re

import pandas as pd

from .config import PROCESSED, RAW
from .dbf import read_dbc


def is_current(out_path, source_path):
    return (out_path.exists()
            and out_path.stat().st_mtime >= source_path.stat().st_mtime)


def convert_sinan():
    out_dir = PROCESSED / "sinan"
    out_dir.mkdir(parents=True, exist_ok=True)
    files = sorted((RAW / "sinan").glob("*.dbc"))
    print(f"sinan: converting {len(files)} files")
    for dbc in files:
        out = out_dir / (dbc.stem.upper() + ".parquet")
        if is_current(out, dbc):
            print(f"  {dbc.name}: up to date")
            continue
        columns = read_dbc(dbc)
        table = pd.DataFrame(columns)
        table["source_file"] = dbc.name.upper()
        table.to_parquet(out, index=False)
        print(f"  {dbc.name}: {len(table):,} records, "
              f"{len(columns)} columns")


def convert_sinasc():
    out_dir = PROCESSED / "sinasc_counts"
    out_dir.mkdir(parents=True, exist_ok=True)
    files = sorted((RAW / "sinasc").glob("*.dbc"))
    print(f"sinasc: counting births in {len(files)} files")
    for dbc in files:
        out = out_dir / (dbc.stem.upper() + ".csv")
        if is_current(out, dbc):
            continue
        year = int(re.match(r"DN[A-Z]{2}(\d{4})", dbc.stem.upper()).group(1))
        codes = read_dbc(dbc, columns=["CODMUNRES"])["CODMUNRES"]
        # Some years store 7-digit codes; the first 6 digits are the code
        # that SINAN uses.
        counts = (pd.Series(codes).str[:6].value_counts()
                  .rename_axis("code6").reset_index(name="births"))
        counts.insert(1, "year", year)
        counts["source_file"] = dbc.name.upper()
        counts.to_csv(out, index=False)
        print(f"  {dbc.name}: {len(codes):,} births")

    parts = [pd.read_csv(p, dtype={"code6": str})
             for p in sorted(out_dir.glob("*.csv"))]
    if parts:
        births = pd.concat(parts, ignore_index=True)
        births.to_parquet(PROCESSED / "births_by_file.parquet", index=False)
        print(f"sinasc: {births.births.sum():,} births in total")


def run():
    convert_sinan()
    convert_sinasc()
