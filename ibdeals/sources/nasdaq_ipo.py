"""US IPO calendar from api.nasdaq.com (covers Nasdaq, NYSE and NYSE American).

Gives sized deals: price, shares offered and dollar proceeds for priced IPOs,
plus the upcoming / filed / withdrawn pipeline.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from .. import http
from .. import models as m

URL = "https://api.nasdaq.com/api/ipo/calendar?date={month}"
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.nasdaq.com",
    "Referer": "https://www.nasdaq.com/",
}


def _months(today: date, back: int, ahead: int) -> list[str]:
    out = []
    for k in range(-back, ahead + 1):
        y, mo = divmod(today.month - 1 + k, 12)
        out.append(f"{today.year + y:04d}-{mo + 1:02d}")
    return out


def _date(v: Any) -> str | None:
    s = str(v or "").strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def _amount(v: Any) -> float | None:
    s = re.sub(r"[^\d.]", "", str(v or ""))
    try:
        return float(s) if s else None
    except ValueError:
        return None


def _rows(section: Any) -> list[dict[str, Any]]:
    if not isinstance(section, dict):
        return []
    rows = section.get("rows")
    if rows is None and isinstance(section.get("upcomingTable"), dict):
        rows = section["upcomingTable"].get("rows")
    return rows or []


def parse(payload: dict[str, Any]) -> list[m.Deal]:
    data = (payload or {}).get("data") or {}
    deals: list[m.Deal] = []
    buckets = [
        ("priced", "Priced", "pricedDate"),
        ("upcoming", "Expected", "expectedPriceDate"),
        ("filed", "Filed", "filedDate"),
        ("withdrawn", "Withdrawn", "withdrawDate"),
    ]
    for bucket, status, date_field in buckets:
        for row in _rows(data.get(bucket)):
            name = (row.get("companyName") or "").strip()
            when = _date(row.get(date_field)) or _date(row.get("filedDate"))
            if not name or not when:
                continue
            value = _amount(row.get("dollarValueOfSharesOffered"))
            ticker = (row.get("proposedTickerSymbol") or "").strip() or None
            deals.append(m.Deal(
                category=m.ECM,
                deal_type=m.IPO,
                date=when,
                status=status,
                issuer=name,
                value=value,
                currency="USD" if value else None,
                value_usd=value,
                country="United States",
                region="Americas",
                exchange=(row.get("proposedExchange") or "").strip() or None,
                ticker=ticker,
                origin="structured",
                confidence=0.95,
                sources=[m.Source(
                    name="Nasdaq IPO calendar",
                    url=f"https://www.nasdaq.com/market-activity/ipos/overview?dealId={row['dealID']}"
                    if row.get("dealID") else "https://www.nasdaq.com/market-activity/ipos",
                    title=f"{name} IPO ({status.lower()})",
                    published=when,
                )],
            ))
    return deals


def fetch(cfg: dict[str, Any], today: date) -> list[m.Deal]:
    deals: list[m.Deal] = []
    for month in _months(today, cfg.get("months_back", 1), cfg.get("months_ahead", 1)):
        deals.extend(parse(http.get_json(URL.format(month=month), headers=HEADERS)))
    return deals
