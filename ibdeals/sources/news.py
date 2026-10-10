"""Global deal headlines from Google News RSS search (no key required).

Several regional editions are searched so that Asian, European and Middle
Eastern deals surface alongside US ones. Output is raw headlines; turning them
into deals happens in `pipeline.py` (rules) and `enrich.py` (Claude).
"""

from __future__ import annotations

import logging
import time
import urllib.parse
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import Any

from .. import http
from ..extract import clean_headline

log = logging.getLogger(__name__)

URL = "https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={ceid}"


def parse_rss(xml_bytes: bytes, edition: str = "") -> list[dict[str, Any]]:
    root = ET.fromstring(xml_bytes)
    items = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        src = item.find("source")
        source_name = (src.text or "").strip() if src is not None else None
        published = None
        raw_date = item.findtext("pubDate")
        if raw_date:
            try:
                published = parsedate_to_datetime(raw_date).date().isoformat()
            except (TypeError, ValueError):
                pass
        items.append({
            "title": title,
            "headline": clean_headline(title, source_name),
            "url": (item.findtext("link") or "").strip() or None,
            "source": source_name or "Google News",
            "source_url": src.get("url") if src is not None else None,
            "published": published,
            "edition": edition,
        })
    return items


def fetch(cfg: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (unique headlines, per-request error messages)."""
    window = cfg.get("window", "2d")
    delay = float(cfg.get("request_delay_seconds", 1.0))
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    requests = 0
    for edition in cfg.get("editions", ["en-US|US|US:en"]):
        hl, gl, ceid = edition.split("|")
        for query in cfg.get("queries", []):
            q = urllib.parse.quote_plus(f"{query} when:{window}")
            url = URL.format(q=q, hl=hl, gl=gl, ceid=urllib.parse.quote(ceid))
            requests += 1
            try:
                batch = parse_rss(http.get(url, retries=2), edition=gl)
            except Exception as e:  # noqa: BLE001 - one failed query must not sink the run
                errors.append(f"{gl} '{query[:40]}': {e}")
                continue
            finally:
                time.sleep(delay)
            for it in batch:
                key = it["headline"].lower()
                if key not in seen:
                    seen.add(key)
                    items.append(it)
    if requests and len(errors) == requests:
        raise RuntimeError(f"all {requests} news requests failed; first error: {errors[0]}")
    return items, errors
