"""Settings shared by every pipeline step."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
REFERENCE = DATA / "reference"
DB_PATH = ROOT / "db" / "syphilis.duckdb"

# DATASUS public file server. Final files are listed first so they win over
# preliminary files for the same year.
FTP_HOST = "ftp.datasus.gov.br"
SINAN_DIRS = [
    ("final", "/dissemin/publicos/SINAN/DADOS/FINAIS"),
    ("preliminary", "/dissemin/publicos/SINAN/DADOS/PRELIM"),
]
SINASC_DIRS = [
    ("final", "/dissemin/publicos/SINASC/1996_/Dados/DNRES"),
    ("preliminary", "/dissemin/publicos/SINASC/PRELIM/DNRES"),
]

# Study period from the proposal.
STUDY_YEARS = list(range(2013, 2025))

# SINAN files are split by notification year, but we count cases by year of
# diagnosis. A case diagnosed in 2024 can be notified in 2025, so we also
# download the 2025 file.
SINAN_FILE_YEARS = list(range(2013, 2026))
SINAN_DISEASES = {"SIFG": "gestational", "SIFC": "congenital"}

UFS = ["AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG",
       "MS", "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR",
       "RS", "SC", "SE", "SP", "TO"]

# geobr years.
BOUNDARY_YEAR = 2022
HEALTH_REGION_YEAR = 2023

# National 2024 figures from the Ministry of Health, Boletim Epidemiologico
# de Sifilis 2025, Table 1 (data as of June 30, 2025).
BULLETIN_2024 = {
    "gestational": 89_724,
    "congenital": 24_443,
}
# The bulletin lists 2,537,576 live births for 2024, but that number is the
# SINASC count for 2023: the bulletin divided both 2023 and 2024 cases by
# 2023 births (89,724 / 2,537,576 = 35.4 per 1,000), probably because 2024
# births were not final yet. We use each year's own births, so our 2024
# rates are higher than the bulletin's.
BULLETIN_BIRTHS = {"year": 2023, "births": 2_537_576}
