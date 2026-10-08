"""Not used by the main pipeline.

TabNet already counts confirmed cases the way the Ministry of Health does
(its 2024 totals match the 2025 bulletin exactly), so we do not need our
own case definitions. This file would only matter if we later work with
the raw microdata from the optional download/convert steps.
"""

CASE_FILTERS = {
    "sifg_raw": [],
    "sifc_raw": [],
}
