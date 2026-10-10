"""SEC EDGAR daily form index -> US deal-filing activity ("filings pulse").

Every US-registered IPO, follow-on, secondary sale and public-company merger
leaves a filing trail. Counting those filings per day is a leading indicator
of deal flow, and each row links straight to the filing.
"""

from __future__ import annotations

import os
import re
from datetime import date, timedelta
from typing import Any

from .. import http
from .. import models as m

INDEX_URL = "https://www.sec.gov/Archives/edgar/daily-index/{y}/QTR{q}/form.{ymd}.idx"

# (group label, category, market, form types). Amendments (/A) are excluded.
FORM_GROUPS: list[tuple[str, str, str | None, tuple[str, ...]]] = [
    ("IPO registration (S-1/F-1)", m.ECM, m.PRIMARY_MARKET, ("S-1", "F-1")),
    ("Priced offering (424B4)", m.ECM, m.PRIMARY_MARKET, ("424B4",)),
    ("Shelf takedown (424B5)", m.ECM, m.PRIMARY_MARKET, ("424B5",)),
    ("Selling-holder resale (424B7)", m.ECM, m.SECONDARY_MARKET, ("424B7",)),
    ("Merger proxy (DEFM14A/PREM14A)", m.MNA, None, ("DEFM14A", "PREM14A", "DEFM14C", "PREM14C")),
    ("Merger registration (S-4/F-4)", m.MNA, None, ("S-4", "F-4")),
    ("Third-party tender offer (SC TO-T)", m.MNA, None, ("SC TO-T", "SCHEDULE TO-T", "SC 14D9", "SC14D9")),
    ("Going-private (SC 13E3)", m.MNA, None, ("SC 13E3", "SCHEDULE 13E3")),
]
_GROUP_BY_FORM = {form: g for g in FORM_GROUPS for form in g[3]}

_LINE = re.compile(
    r"^(?P<form>\S.*?)\s{2,}(?P<company>\S.*?)\s{2,}(?P<cik>\d+)\s+"
    r"(?P<date>\d{8}|\d{4}-\d{2}-\d{2})\s+(?P<file>edgar/\S+)\s*$"
)


def parse_index(text: str) -> list[dict[str, Any]]:
    filings = []
    for line in text.splitlines():
        mt = _LINE.match(line)
        if not mt:
            continue
        form = mt.group("form").strip()
        group = _GROUP_BY_FORM.get(form)
        if not group:
            continue
        d = mt.group("date").replace("-", "")
        filename = mt.group("file")
        accession = filename.rsplit("/", 1)[-1].removesuffix(".txt")
        cik = str(int(mt.group("cik")))
        filings.append({
            "accession": accession,
            "date": f"{d[:4]}-{d[4:6]}-{d[6:]}",
            "form": form,
            "group": group[0],
            "category": group[1],
            "market": group[2],
            "company": mt.group("company").strip(),
            "cik": cik,
            "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{accession}-index.htm",
        })
    return filings


def fetch(cfg: dict[str, Any], today: date, lookback_days: int) -> list[dict[str, Any]]:
    ua = os.environ.get("SEC_USER_AGENT") or cfg.get("user_agent")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if repo and not os.environ.get("SEC_USER_AGENT"):
        ua = f"{ua} +https://github.com/{repo}"
    headers = {"User-Agent": ua, "Accept": "text/plain"}
    out: list[dict[str, Any]] = []
    fetched = 0
    for back in range(lookback_days + 1):
        day = today - timedelta(days=back)
        if day.weekday() >= 5:
            continue
        url = INDEX_URL.format(y=day.year, q=(day.month - 1) // 3 + 1, ymd=day.strftime("%Y%m%d"))
        try:
            text = http.get(url, headers=headers).decode("latin-1")
        except http.NotFound:
            continue  # holiday, or today's index not published yet
        fetched += 1
        out.extend(parse_index(text))
    if fetched == 0:
        raise RuntimeError("no EDGAR daily index files could be fetched")
    return out
