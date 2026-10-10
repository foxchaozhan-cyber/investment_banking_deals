"""Daily refresh: fetch every source, merge into data/, record source health.

    python -m ibdeals.pipeline                 # normal daily run
    python -m ibdeals.pipeline --only news     # run a subset of sources
    python -m ibdeals.pipeline --today 2026-10-09

A failing source never aborts the run: its error is recorded in meta.json
(shown on the dashboard) and the other sources still update. The process
exits non-zero only when every enabled source failed, so CI flags a real
outage without blocking partial updates.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
import tomllib
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import enrich, extract, store
from . import models as m
from .fx import FX
from .sources import edgar, manual, nasdaq_ipo, news

log = logging.getLogger("ibdeals")
ROOT = Path(__file__).resolve().parent.parent


def headlines_to_deals(items: list[dict[str, Any]], fx: FX, enrich_cfg: dict[str, Any] | None,
                       today: date) -> tuple[list[m.Deal], dict[str, Any]]:
    """Turn raw news headlines into deal records (rules first, Claude if configured)."""
    llm: dict[int, dict[str, Any]] = {}
    info: dict[str, Any] = {"mode": "rules"}
    if enrich_cfg is not None and enrich.available() and items:
        limit = int(enrich_cfg.get("max_headlines", 400))
        try:
            llm = enrich.classify([it["headline"] for it in items[:limit]], enrich_cfg)
            info = {"mode": "claude", "model": enrich_cfg.get("model"), "classified": len(llm),
                    "sent_to_claude": min(limit, len(items))}
        except Exception as e:  # noqa: BLE001 - enrichment is best-effort
            log.warning("Claude enrichment unavailable: %s", e)
            info = {"mode": "rules", "enrich_error": str(e)}

    deals = []
    for i, it in enumerate(items):
        h = it["headline"]
        rule = extract.classify(h)
        ai = llm.get(i)
        if ai is not None:
            if not ai.get("is_deal") or ai.get("deal_type") not in m.CATEGORY_BY_TYPE:
                continue
            deal_type = ai["deal_type"]
            category = m.CATEGORY_BY_TYPE[deal_type]
        elif rule:
            category, deal_type = rule
        else:
            continue

        issuer, acquirer = extract.parties(category, h)
        money = extract.deal_size(h, category)
        value, currency = (money.amount, money.currency) if money else (None, None)
        status = extract.status_for(category, h, deal_type)
        country, sector, confidence = extract.country_for(h), None, 0.4
        if ai is not None:
            issuer = ai.get("issuer_or_target") or issuer
            acquirer = (ai.get("acquirer") or acquirer) if category == m.MNA else None
            if ai.get("value") and ai.get("currency"):
                value, currency = float(ai["value"]), str(ai["currency"]).upper()
            status = ai.get("status") or status
            country = ai.get("country") or country
            sector = ai.get("sector")
            confidence = 0.7
        published = it.get("published") or today.isoformat()
        deals.append(m.Deal(
            category=category,
            deal_type=deal_type,
            date=published,
            status=status,
            issuer=issuer,
            acquirer=acquirer,
            value=value,
            currency=currency,
            value_usd=fx.to_usd(value, currency),
            country=country,
            region=extract.region_for(country),
            sector=sector,
            origin="news",
            confidence=confidence,
            sources=[m.Source(name=it.get("source") or "News", url=it.get("url"), title=h,
                              published=published)],
        ))
    return deals, info


def run(data_dir: Path, config: dict[str, Any], today: date, only: set[str] | None = None) -> int:
    pcfg = config.get("pipeline", {})
    scfg = config.get("sources", {})
    lookback = int(pcfg.get("lookback_days", 7))
    meta: dict[str, Any] = {"sources": {}}
    incoming: list[m.Deal] = []
    filing_rows: list[dict[str, Any]] | None = None

    def enabled(name: str) -> bool:
        return scfg.get(name, {}).get("enabled", True) and (only is None or name in only)

    def step(name: str, fn: Callable[[], Any]) -> Any:
        if not enabled(name):
            meta["sources"][name] = {"status": "skipped"}
            return None
        t0 = time.monotonic()
        try:
            result = fn()
        except Exception as e:  # noqa: BLE001 - isolate source failures
            log.exception("source %s failed", name)
            meta["sources"][name] = {"status": "error", "message": str(e)[:300],
                                     "seconds": round(time.monotonic() - t0, 1)}
            return None
        meta["sources"][name] = {"status": "ok", "seconds": round(time.monotonic() - t0, 1)}
        return result

    fx = FX.load()
    meta["fx"] = fx.source

    ipo = step("nasdaq_ipo", lambda: nasdaq_ipo.fetch(scfg.get("nasdaq_ipo", {}), today))
    if ipo is not None:
        incoming += ipo
        meta["sources"]["nasdaq_ipo"]["records"] = len(ipo)

    filing_rows = step("edgar", lambda: edgar.fetch(scfg.get("edgar", {}), today, lookback))
    if filing_rows is not None:
        meta["sources"]["edgar"]["records"] = len(filing_rows)

    fetched = step("news", lambda: news.fetch(scfg.get("news", {})))
    if fetched is not None:
        items, errors = fetched
        news_deals, info = headlines_to_deals(items, fx, config.get("enrich"), today)
        incoming += news_deals
        meta["sources"]["news"].update(records=len(news_deals), headlines=len(items), **info)
        if errors:
            meta["sources"]["news"].update(status="partial", failed_requests=len(errors),
                                           message="; ".join(errors[:3])[:300])

    folder = ROOT / scfg.get("manual", {}).get("folder", "data/manual")
    man = step("manual", lambda: manual.load(folder, fx))
    if man is not None:
        incoming += man
        meta["sources"]["manual"]["records"] = len(man)

    # Merge into history.
    deals_path, filings_path = data_dir / "deals.json", data_dir / "filings.json"
    merged = store.merge(store.load_deals(deals_path), incoming)
    merged = store.prune(
        merged, today,
        retention_days=int(pcfg.get("retention_days", 400)),
        unsized_news_days=int(pcfg.get("unsized_news_days", 30)),
        min_keep_usd=float(pcfg.get("min_keep_usd", 25_000_000)),
    )
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    store.write_json(deals_path, {
        "generated_at": generated,
        "thresholds": {"ecm_usd": pcfg.get("major_ecm_usd", 100_000_000),
                       "mna_usd": pcfg.get("major_mna_usd", 500_000_000)},
        "deals": [d.to_dict() for d in merged],
    })
    if filing_rows is not None:
        filings = store.merge_filings(store.read_json(filings_path, {}), filing_rows, today,
                                      retention_days=int(pcfg.get("retention_days", 400)))
        filings["groups"] = [{"label": g[0], "category": g[1], "market": g[2], "forms": list(g[3])}
                             for g in edgar.FORM_GROUPS]
        store.write_json(filings_path, filings)

    # Keep the last successful time per source so the dashboard can flag stale data.
    previous = store.read_json(data_dir / "meta.json", {}).get("sources", {})
    for name, s in meta["sources"].items():
        if s["status"] in ("ok", "partial"):
            s["last_success"] = generated
        elif previous.get(name, {}).get("last_success"):
            s["last_success"] = previous[name]["last_success"]
    meta.update(generated_at=generated, as_of=today.isoformat(), deal_count=len(merged),
                new_records=len(incoming))
    store.write_json(data_dir / "meta.json", meta)

    ran = [s for s in meta["sources"].values() if s["status"] != "skipped"]
    failed = [n for n, s in meta["sources"].items() if s["status"] == "error"]
    log.info("deals: %d total, %d incoming; failed sources: %s", len(merged), len(incoming), failed or "none")
    return 1 if ran and len(failed) == len(ran) else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default=str(ROOT / "data"))
    ap.add_argument("--config", default=str(ROOT / "config.toml"))
    ap.add_argument("--today", help="as-of date (YYYY-MM-DD); default: today UTC")
    ap.add_argument("--only", help="comma-separated sources: nasdaq_ipo,edgar,news,manual")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = tomllib.loads(Path(args.config).read_text())
    today = date.fromisoformat(args.today) if args.today else datetime.now(timezone.utc).date()
    only = set(args.only.split(",")) if args.only else None
    return run(Path(args.data_dir), config, today, only)


if __name__ == "__main__":
    sys.exit(main())
