"""Write data/processed/check_report.txt: our totals next to the bulletin's,
and how many cases and births could not be placed in a municipality."""
import duckdb

from .config import BULLETIN_2024, BULLETIN_BIRTHS, DB_PATH, PROCESSED, STUDY_YEARS

REPORT = PROCESSED / "check_report.txt"


def run():
    con = duckdb.connect(str(DB_PATH), read_only=True)
    lines = []
    out = lines.append

    def one(sql):
        return con.execute(sql).fetchone()

    for key, table in (("gestational", "tabnet_gestational_cases"),
                       ("congenital", "tabnet_congenital_cases"),
                       ("births", "tabnet_births")):
        out(f"===== {key} =====")
        rows = con.execute(f"""
            SELECT year, sum(value) FROM {table}
            WHERE year BETWEEN {STUDY_YEARS[0]} AND {STUDY_YEARS[-1]}
            GROUP BY 1 ORDER BY 1""").fetchall()
        for y, n in rows:
            out(f"  {y}: {n:,}")
        if key == "births":
            year, target = BULLETIN_BIRTHS["year"], BULLETIN_BIRTHS["births"]
            label = (f"{year} births (the bulletin used this as its 2024 "
                     f"denominator)")
        else:
            year, target = 2024, BULLETIN_2024[key]
            label = "2024 national total"
        ours = one(f"SELECT coalesce(sum(value), 0) FROM {table} "
                   f"WHERE year = {year}")[0]
        out(f"{label}: ours {ours:,} vs bulletin {target:,} "
            f"(difference {ours - target:+,})")
        unplaced, total = one(f"""
            SELECT coalesce(sum(t.value) FILTER (WHERE m.code6 IS NULL), 0),
                   coalesce(sum(t.value), 0)
            FROM {table} t LEFT JOIN municipalities m ON m.code6 = t.code6
            WHERE t.year BETWEEN {STUDY_YEARS[0]} AND {STUDY_YEARS[-1]}""")
        out(f"2013-2024 counts not matched to a municipality: {unplaced:,} "
            f"of {total:,} ({100 * unplaced / max(total, 1):.2f}%)")
        examples = con.execute(f"""
            SELECT t.name, sum(t.value) FROM {table} t
            LEFT JOIN municipalities m ON m.code6 = t.code6
            WHERE m.code6 IS NULL AND t.value > 0
            GROUP BY 1 ORDER BY 2 DESC LIMIT 8""").fetchall()
        if examples:
            out("  largest unmatched rows: " + "; ".join(
                f"{name} ({n:,})" for name, n in examples))
        out("")

    out("===== municipalities and panel =====")
    out(f"municipalities: {one('SELECT count(*) FROM municipalities')[0]:,}")
    out(f"without health region: "
        f"{one('SELECT count(*) FROM municipalities WHERE health_region IS NULL')[0]}")
    out(f"priority municipalities found: "
        f"{one('SELECT count(*) FROM priority p JOIN municipalities m ON m.code7 = p.code_ibge7')[0]} of 100")
    mn, mx = one("SELECT min(n), max(n) FROM "
                 "(SELECT count(*) n FROM panel GROUP BY year)")
    out(f"panel rows per year: {mn:,} to {mx:,}")

    con.close()
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"check: report saved to {REPORT}")
