"""Merge each day's records into the persistent history in data/.

Outputs (all JSON, read directly by the dashboard):
  deals.json    rolling deal history, de-duplicated across sources and days
  filings.json  EDGAR filing counts per day/group + the latest filing rows
  meta.json     run timestamp and per-source health
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

from . import models as m

ORIGIN_RANK = {"news": 0, "structured": 1, "manual": 2}
MAX_SOURCES = 5
# How long two records with the same parties are treated as the same deal.
MATCH_WINDOW_DAYS = {m.IPO: 365, m.ACQUISITION: 365, m.MERGER: 365, m.TENDER: 365, m.BUYOUT: 365,
                     m.FOLLOW_ON: 21, m.SECONDARY: 14, m.CONVERTIBLE: 21}
FUZZY_WINDOW_DAYS = 10
FUZZY_THRESHOLD = 0.6


def _d(s: str | None) -> date | None:
    try:
        return date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


def _tokens(text: str | None) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(t) > 2}


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _within(a: m.Deal, b: m.Deal, days: int) -> bool:
    da, db = _d(a.date), _d(b.date)
    da0, db0 = _d(a.announced) or da, _d(b.announced) or db
    if not (da and db):
        return False
    # Compare the closest pair of milestones of the two records.
    gap = min(abs((da - db).days), abs((da0 - db).days), abs((da - db0).days))
    return gap <= days


def _close_values(a: m.Deal, b: m.Deal, tolerance: float = 0.05) -> bool:
    if not a.value_usd or not b.value_usd:
        return False
    return abs(a.value_usd - b.value_usd) <= tolerance * max(a.value_usd, b.value_usd)


def same_deal(a: m.Deal, b: m.Deal) -> bool:
    if a.category != b.category:
        return False
    # Outlets name the same buyer or target differently ("Wittington Investments"
    # vs "Weston family"); the same size plus one shared party settles it.
    if (a.category == m.MNA and _close_values(a, b) and _within(a, b, FUZZY_WINDOW_DAYS)
            and (m.names_match(a.issuer, b.issuer) or m.names_match(a.acquirer, b.acquirer))):
        return True
    if a.category == m.ECM and a.deal_type != b.deal_type:
        return False
    ta, tb = m.normalize_name(a.issuer), m.normalize_name(b.issuer)
    if ta and tb:
        if not m.names_match(ta, tb):
            return False
        if a.category == m.MNA and a.acquirer and b.acquirer and not m.names_match(a.acquirer, b.acquirer):
            return False  # competing bidders for the same target
        return _within(a, b, MATCH_WINDOW_DAYS.get(a.deal_type, 30))
    # At least one side lacks parties: fall back to headline similarity.
    if a.deal_type != b.deal_type or not _within(a, b, FUZZY_WINDOW_DAYS):
        return False
    ta_set = set().union(*(_tokens(s.title) for s in a.sources)) if a.sources else set()
    tb_set = set().union(*(_tokens(s.title) for s in b.sources)) if b.sources else set()
    return _jaccard(ta_set, tb_set) >= FUZZY_THRESHOLD


def merge_into(a: m.Deal, b: m.Deal) -> m.Deal:
    """Fold record `b` into `a` (a keeps its id)."""
    b_better = (ORIGIN_RANK[b.origin], b.confidence) > (ORIGIN_RANK[a.origin], a.confidence)
    if b.value_usd is not None and (a.value_usd is None or b_better):
        a.value, a.currency, a.value_usd = b.value, b.currency, b.value_usd
    for f in ("issuer", "acquirer", "country", "region", "exchange", "sector", "ticker"):
        bv = getattr(b, f)
        if bv and (not getattr(a, f) or (b_better and f in ("issuer", "acquirer", "country", "region"))):
            setattr(a, f, bv)
    if m.status_rank(b.status) > m.status_rank(a.status):
        a.status = b.status
    if a.category == m.MNA and b.deal_type != a.deal_type and b_better:
        a.deal_type = b.deal_type
    dates = [d for d in (a.date, b.date) if d]
    firsts = [d for d in (a.announced, b.announced, a.date, b.date) if d]
    a.date, a.announced = max(dates), min(firsts)
    if ORIGIN_RANK[b.origin] > ORIGIN_RANK[a.origin]:
        a.origin = b.origin
    a.confidence = max(a.confidence, b.confidence)
    seen = {(s.url or s.title) for s in a.sources}
    for s in b.sources:
        if (s.url or s.title) not in seen and len(a.sources) < MAX_SOURCES:
            a.sources.append(s)
            seen.add(s.url or s.title)
    return a


def merge(existing: Iterable[m.Deal], incoming: Iterable[m.Deal]) -> list[m.Deal]:
    deals = list(existing)
    ids = {d.ensure_id() for d in deals}
    # Candidate indexes keep matching cheap on a large history: by party name,
    # and (for records without parties) by deal type for the fuzzy fallback.
    by_party: dict[str, list[m.Deal]] = {}
    by_acquirer: dict[str, list[m.Deal]] = {}
    unnamed: dict[str, list[m.Deal]] = {}

    def index(d: m.Deal) -> None:
        key = m.name_key(d.issuer)
        (by_party.setdefault(key, []) if key else unnamed.setdefault(d.deal_type, [])).append(d)
        if key and d.acquirer:
            by_acquirer.setdefault(m.name_key(d.acquirer), []).append(d)

    for d in deals:
        index(d)
    for new in incoming:
        key = m.name_key(new.issuer)
        if key:
            candidates = by_party.get(key, []) + unnamed.get(new.deal_type, [])
            if new.acquirer:
                candidates += by_acquirer.get(m.name_key(new.acquirer), [])
        else:
            candidates = unnamed.get(new.deal_type, []) + [
                d for ds in by_party.values() for d in ds if d.deal_type == new.deal_type
                and _within(d, new, FUZZY_WINDOW_DAYS)]
        match = next((d for d in candidates if same_deal(d, new)), None)
        if match:
            had_party, old_type = bool(m.normalize_name(match.issuer)), match.deal_type
            merge_into(match, new)
            if not had_party and m.normalize_name(match.issuer):
                unnamed[old_type].remove(match)
                index(match)
            continue
        if not new.announced:
            new.announced = new.date
        base, n = new.ensure_id(), 2
        while new.id in ids:  # distinct deals whose party-derived ids collide
            new.id, n = f"{base}-{n}", n + 1
        ids.add(new.id)
        deals.append(new)
        index(new)
    return deals


def prune(deals: list[m.Deal], today: date, retention_days: int, unsized_news_days: int,
          min_keep_usd: float) -> list[m.Deal]:
    keep = []
    for d in deals:
        dd = _d(d.date)
        if not dd or (today - dd).days > retention_days:
            continue
        small_news = d.origin == "news" and (d.value_usd is None or d.value_usd < min_keep_usd)
        if small_news and (today - dd).days > unsized_news_days:
            continue
        keep.append(d)
    keep.sort(key=lambda d: (d.date, d.value_usd or 0), reverse=True)
    return keep


# --- Filings ----------------------------------------------------------------

def merge_filings(existing: dict[str, Any], new_rows: list[dict[str, Any]], today: date,
                  retention_days: int, recent_days: int = 14) -> dict[str, Any]:
    recent = {r["accession"] + r["form"]: r for r in existing.get("recent", [])}
    for r in new_rows:
        recent[r["accession"] + r["form"]] = r
    # Daily counts are recomputed for every day we hold rows for, and carried
    # forward unchanged for older days.
    counts: dict[str, dict[str, int]] = {d: dict(g) for d, g in existing.get("daily_counts", {}).items()}
    fresh: dict[str, dict[str, int]] = {}
    for r in recent.values():
        fresh.setdefault(r["date"], {}).setdefault(r["group"], 0)
        fresh[r["date"]][r["group"]] += 1
    counts.update(fresh)
    cutoff = (today - timedelta(days=retention_days)).isoformat()
    recent_cutoff = (today - timedelta(days=recent_days)).isoformat()
    return {
        "daily_counts": {d: g for d, g in sorted(counts.items()) if d >= cutoff},
        "recent": sorted((r for r in recent.values() if r["date"] >= recent_cutoff),
                         key=lambda r: (r["date"], r["group"], r["company"]), reverse=True),
    }


# --- IO ----------------------------------------------------------------------

def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return default


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")
    tmp.replace(path)


def load_deals(path: Path) -> list[m.Deal]:
    return [m.Deal.from_dict(d) for d in read_json(path, {}).get("deals", [])]
