"""CSV drop-in for licensed data (Dealogic, LSEG, Bloomberg, PitchBook exports).

Any *.csv in the configured folder is loaded on every run. Column names are
matched case-insensitively; see data/manual/README.md for the layout.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .. import models as m
from ..extract import region_for

_TYPE_ALIASES = {
    "ipo": m.IPO, "initial public offering": m.IPO,
    "follow-on": m.FOLLOW_ON, "follow on": m.FOLLOW_ON, "fo": m.FOLLOW_ON, "rights issue": m.FOLLOW_ON,
    "secondary": m.SECONDARY, "block": m.SECONDARY, "block trade": m.SECONDARY,
    "secondary / block": m.SECONDARY, "abb": m.SECONDARY,
    "convertible": m.CONVERTIBLE, "cb": m.CONVERTIBLE, "exchangeable": m.CONVERTIBLE,
    "acquisition": m.ACQUISITION, "m&a": m.ACQUISITION, "merger": m.MERGER,
    "tender offer": m.TENDER, "tender": m.TENDER,
    "lbo": m.BUYOUT, "buyout": m.BUYOUT, "take-private": m.BUYOUT, "take-private / lbo": m.BUYOUT,
}


def _f(v: Any) -> float | None:
    try:
        return float(str(v).replace(",", "").strip()) if str(v or "").strip() else None
    except ValueError:
        return None


def load(folder: str | Path, fx: Any) -> list[m.Deal]:
    deals: list[m.Deal] = []
    for path in sorted(Path(folder).glob("*.csv")):
        with path.open(newline="", encoding="utf-8-sig") as fh:
            for raw in csv.DictReader(fh):
                row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
                deal_type = _TYPE_ALIASES.get(row.get("deal_type", "").lower())
                if not deal_type or not row.get("date"):
                    continue
                value = _f(row.get("value"))
                currency = (row.get("currency") or "USD").upper() if value else None
                value_usd = _f(row.get("value_usd")) or fx.to_usd(value, currency)
                country = row.get("country") or None
                deals.append(m.Deal(
                    category=m.CATEGORY_BY_TYPE[deal_type],
                    deal_type=deal_type,
                    date=row["date"][:10],
                    status=row.get("status") or "Announced",
                    issuer=row.get("issuer") or row.get("target") or None,
                    acquirer=row.get("acquirer") or None,
                    value=value,
                    currency=currency,
                    value_usd=value_usd,
                    country=country,
                    region=row.get("region") or region_for(country),
                    exchange=row.get("exchange") or None,
                    sector=row.get("sector") or None,
                    ticker=row.get("ticker") or None,
                    origin="manual",
                    confidence=1.0,
                    sources=[m.Source(name=row.get("source") or path.stem, url=row.get("url") or None,
                                      title=row.get("title") or None, published=row["date"][:10])],
                ))
    return deals
