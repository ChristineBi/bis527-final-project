"""Download municipal boundaries and health regions with geobr (IPEA).

Writes data/processed/municipalities.parquet with one row per
municipality: 7-digit IBGE code, 6-digit code, name, state, health region,
a representative point, and the full-resolution boundary as WKB so the
database can build neighbor networks later.
"""
import geobr
import pandas as pd
import shapely

from .config import BOUNDARY_YEAR, HEALTH_REGION_YEAR, PROCESSED


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

    print(f"boundaries: downloading health regions ({HEALTH_REGION_YEAR})")
    try:
        hr = geobr.read_health_region(year=HEALTH_REGION_YEAR)
        hr_code = pick(hr.columns, "code_health_region")
        hr_name = pick(hr.columns, "name_health_region")
        regions = pd.DataFrame({
            "code7": hr["code_muni"].astype("int64").astype(str),
            "health_region": hr[hr_code].astype(str),
            "health_region_name": hr[hr_name],
        }).drop_duplicates("code7")
        table = table.merge(regions, on="code7", how="left")
        unmatched = table["health_region"].isna().sum()
        print(f"  {unmatched} municipalities without a health region")
    except Exception as err:  # health regions are only needed later
        print(f"  WARNING: health regions not loaded ({err})")
        table["health_region"] = None
        table["health_region_name"] = None

    out = PROCESSED / "municipalities.parquet"
    table.to_parquet(out, index=False)
    print(f"boundaries: {len(table):,} municipalities written to {out.name}")
