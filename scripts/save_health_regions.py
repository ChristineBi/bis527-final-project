"""Save the municipality -> health region mapping as a file in the repo.

The pipeline used to download the 2023 health regions with geobr each time.
Newer geobr data releases no longer include that file, so we keep our own
copy in data/reference/health_regions_2023.csv. It was taken from geobr
(IPEA) health regions, year 2023, and is the mapping behind
data/shared/region_panel.csv.

This script rebuilds the file from the committed panel files:
    python scripts/save_health_regions.py
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
panel = pd.read_csv(ROOT / "data/processed/panel.csv", dtype=str)
regions = pd.read_csv(ROOT / "data/shared/region_panel.csv", dtype=str)

# '11005.0' -> '11005' in case an older panel.csv is used
panel["health_region"] = (pd.to_numeric(panel["health_region"])
                          .astype("Int64").astype(str))
names = regions[["health_region", "health_region_name"]].drop_duplicates()
out = (panel[["code7", "health_region"]].drop_duplicates()
       .merge(names, on="health_region", how="left")
       .sort_values("code7"))

assert len(out) == 5570 and out["code7"].is_unique
assert out["health_region"].nunique() == 450
assert out["health_region_name"].notna().all()

path = ROOT / "data/reference/health_regions_2023.csv"
out.to_csv(path, index=False)
print(f"wrote {len(out):,} municipalities in "
      f"{out['health_region'].nunique()} health regions to {path.name}")
