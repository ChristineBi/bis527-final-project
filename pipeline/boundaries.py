"""Download municipal boundaries with geobr (IPEA) and add health regions.

Writes data/processed/municipalities.parquet with one row per
municipality: 7-digit IBGE code, 6-digit code, name, state, health region,
a representative point, and the full-resolution boundary as WKB so the
database can build neighbor networks later.

Health regions come from data/reference/health_regions_2023.csv, our saved
copy of geobr's 2023 health-region file. Newer geobr data releases no
longer include that year, so we do not download it anymore.
"""
import geobr
import pandas as pd
import shapely

from .config import BOUNDARY_YEAR, HEALTH_REGION_YEAR, PROCESSED, ROOT

HEALTH_REGIONS = (ROOT / "data" / "reference"
                  / f"health_regions_{HEALTH_REGION_YEAR}.csv")


def pick(columns, *candidates):
    for name in candidates:
        if name in columns:
            return name
    raise KeyError(f"none of {candidates} in {list(columns)}")


def run():
    PROCESSED.mkdir(parents=True, exist_ok=True)
    print(f"boundaries: downloading municipalities ({BOUNDARY_YEAR})")
    muni = geobr.read_municipality(year=BOUNDARY_YEAR, code_muni="all",
                                   simplified=False)
    code7 = muni["code_muni"].astype("int64").astype(str)
    point = muni.geometry.representative_point()
    table = pd.DataFrame({
        "code7": code7,
        "code6": code7.str[:6],
        "name": muni["name_muni"],
        "uf": muni[pick(muni.columns, "abbrev_state", "abbrev_uf")],
        "code_state": muni["code_state"].astype("int64").astype(str),
        "lon": point.x,
        "lat": point.y,
        "geom_wkb": shapely.to_wkb(muni.geometry.values),
    })

    print(f"boundaries: adding health regions ({HEALTH_REGION_YEAR}) "
          f"from {HEALTH_REGIONS.name}")
    regions = pd.read_csv(HEALTH_REGIONS, dtype=str)
    table = table.merge(regions, on="code7", how="left")
    unmatched = table["health_region"].isna().sum()
    print(f"  {unmatched} municipalities without a health region")
    if unmatched:
        raise ValueError(f"{unmatched} municipalities have no health region; "
                         f"check {HEALTH_REGIONS}")

    out = PROCESSED / "municipalities.parquet"
    table.to_parquet(out, index=False)
    print(f"boundaries: {len(table):,} municipalities written to {out.name}")
