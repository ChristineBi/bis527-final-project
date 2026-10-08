"""Match the 100 Sifilis Nao priority municipalities to IBGE codes.

Usage:
    python scripts/match_priority_list.py MUNICIPIOS_CSV ESTADOS_CSV

MUNICIPIOS_CSV and ESTADOS_CSV are the municipality and state lists
(columns codigo_ibge, nome, codigo_uf / codigo_uf, uf). Writes
data/reference/sifilis_nao_priority.csv with both the 7-digit IBGE code
and the 6-digit code that SINAN and SINASC use.
"""
import csv
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "reference" / "sifilis_nao_priority_raw.csv"
OUT = ROOT / "data" / "reference" / "sifilis_nao_priority.csv"


def normalize(name):
    """Lowercase and strip accents so 'Maceió' matches 'Maceio'."""
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    return " ".join(name.lower().replace("'", " ").split())


def main(municipios_csv, estados_csv):
    with open(estados_csv, encoding="utf-8-sig") as f:
        uf_by_code = {row["codigo_uf"]: row["uf"] for row in csv.DictReader(f)}

    lookup = {}
    with open(municipios_csv, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            key = (normalize(row["nome"]), uf_by_code[row["codigo_uf"]])
            lookup[key] = (row["codigo_ibge"], row["nome"])

    matched, missing = [], []
    with open(RAW, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (normalize(row["municipio"]), row["uf"])
            if key in lookup:
                code7, official_name = lookup[key]
                matched.append({
                    "municipio": official_name,
                    "uf": row["uf"],
                    "code_ibge7": code7,
                    "code6": code7[:6],
                })
            else:
                missing.append(row)

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["municipio", "uf", "code_ibge7", "code6"])
        writer.writeheader()
        writer.writerows(matched)

    print("matched:", len(matched))
    print("not matched:", len(missing))
    for row in missing:
        print("  missing:", row["municipio"], row["uf"])
    print("unique codes:", len({m["code_ibge7"] for m in matched}))
    print("wrote", OUT)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
