"""Optional: structure news headlines with Claude.

Runs only when ANTHROPIC_API_KEY is set. Each batch of headlines goes out in
one request with a JSON-schema constrained response. Any failure (network,
refusal, malformed output) leaves the rule-based extraction in place.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from . import models as m

log = logging.getLogger(__name__)

DEAL_TYPES = [m.IPO, m.FOLLOW_ON, m.SECONDARY, m.CONVERTIBLE, m.ACQUISITION, m.MERGER, m.TENDER, m.BUYOUT]


def _nullable(t: str, **extra: Any) -> dict[str, Any]:
    return {"anyOf": [{"type": t, **extra}, {"type": "null"}]}


SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "is_deal": {"type": "boolean"},
                    "deal_type": _nullable("string", enum=DEAL_TYPES),
                    "status": _nullable("string", enum=m.STATUS_ORDER),
                    "issuer_or_target": _nullable("string"),
                    "acquirer": _nullable("string"),
                    "value": _nullable("number"),
                    "currency": _nullable("string"),
                    "country": _nullable("string"),
                    "sector": _nullable("string"),
                },
                "required": ["index", "is_deal", "deal_type", "status", "issuer_or_target", "acquirer",
                             "value", "currency", "country", "sector"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}

INSTRUCTIONS = f"""You extract investment-banking deal facts from news headlines.

For each numbered headline return one item with the same index.
- is_deal: true only if the headline reports a specific equity capital markets
  transaction (IPO, follow-on, rights issue, placement, block trade / secondary
  sell-down, convertible) or an M&A transaction (acquisition, merger, tender
  offer, take-private / LBO, including stake purchases). False for market
  commentary, stock tips, buybacks, debt-only financing, funds, crypto, and
  venture/private funding rounds.
- deal_type: one of {", ".join(DEAL_TYPES)}. "Secondary / Block" means existing
  holders sell shares; primary issuance by the company is "Follow-on".
- status: one of {", ".join(m.STATUS_ORDER)}. Talks/considering = Rumored;
  signed/agreed = Announced; regulatory or shareholder approval = Pending;
  IPO/offering priced or money raised = Priced; listed/closed = Completed.
- issuer_or_target: ECM issuer, or M&A target (the company being bought).
  Use the company's common name without "Inc."/"Ltd" etc.
- acquirer: M&A buyer, else null.
- value: deal size as a plain number in full units (e.g. 5200000000 for
  "$5.2 billion"; 50000000000 for "Rs 5,000 crore"). For ECM use proceeds, not
  valuation. null if not stated.
- currency: ISO 4217 code of `value` (USD, EUR, HKD, INR, JPY, CNY, ...).
- country: country of the issuer/target (or listing venue), full English name.
- sector: short industry label (e.g. "Technology", "Banks", "Pharma") or null.
Use only what the headline states or what is common knowledge about the
named companies; when unsure, use null."""


def available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def classify(headlines: list[str], cfg: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """Return {headline index: extracted fields}. Missing indexes = not processed."""
    import anthropic  # optional dependency, imported only when enrichment runs

    client = anthropic.Anthropic()
    batch_size = int(cfg.get("batch_size", 40))
    out: dict[int, dict[str, Any]] = {}
    for start in range(0, len(headlines), batch_size):
        chunk = headlines[start:start + batch_size]
        listing = "\n".join(f"{start + i}. {h}" for i, h in enumerate(chunk))
        try:
            response = client.beta.messages.create(
                model=cfg.get("model", "claude-opus-5-5"),
                max_tokens=16000,
                system=INSTRUCTIONS,
                messages=[{"role": "user", "content": f"Headlines:\n{listing}"}],
                output_config={"effort": cfg.get("effort", "low"),
                               "format": {"type": "json_schema", "schema": SCHEMA}},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.APIError as e:
            log.warning("Claude enrichment batch %d failed: %s", start // batch_size, e)
            continue
        if response.stop_reason != "end_turn":
            log.warning("Claude enrichment batch %d stopped with %s", start // batch_size, response.stop_reason)
            continue
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            items = json.loads(text)["items"]
        except (ValueError, KeyError, TypeError) as e:
            log.warning("Claude enrichment batch %d returned unparseable output: %s", start // batch_size, e)
            continue
        for item in items:
            idx = item.get("index")
            if isinstance(idx, int) and start <= idx < start + len(chunk):
                out[idx] = item
    return out
