"""End-to-end run with the network replaced by fixtures."""

import json
import tomllib
from datetime import date
from pathlib import Path

import pytest

from ibdeals import enrich, http, pipeline
from ibdeals import models as m

ROOT = Path(__file__).resolve().parent.parent
FIX = Path(__file__).parent / "fixtures"
TODAY = date(2026, 10, 9)


@pytest.fixture
def config():
    cfg = tomllib.loads((ROOT / "config.toml").read_text())
    cfg["sources"]["news"]["editions"] = ["en-US|US|US:en"]
    cfg["sources"]["news"]["queries"] = ["q1", "q2"]
    cfg["sources"]["news"]["request_delay_seconds"] = 0
    cfg["sources"]["manual"]["enabled"] = False
    return cfg


@pytest.fixture
def fake_net(monkeypatch):
    calls = []

    def fake_get(url, headers=None, **kw):
        calls.append(url)
        if "frankfurter" in url:
            return json.dumps({"date": "2026-10-08", "rates": {"HKD": 7.8, "INR": 88.0, "EUR": 0.9}}).encode()
        if "api.nasdaq.com" in url:
            if "2026-10" in url:
                return (FIX / "nasdaq_calendar.json").read_bytes()
            return b'{"data":{}}'
        if "sec.gov" in url:
            assert headers and headers.get("User-Agent")
            if url.endswith("form.20261008.idx"):
                return (FIX / "form.idx").read_bytes()
            raise http.NotFound(url)
        if "news.google.com" in url:
            return (FIX / "news.xml").read_bytes()
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(http, "get", fake_get)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return calls


def load(tmp_path, name):
    return json.loads((tmp_path / name).read_text())


def test_full_run_merges_sources(tmp_path, config, fake_net):
    assert pipeline.run(tmp_path, config, TODAY) == 0
    deals = load(tmp_path, "deals.json")["deals"]
    meta = load(tmp_path, "meta.json")
    filings = load(tmp_path, "filings.json")

    assert {n: s["status"] for n, s in meta["sources"].items()} == {
        "nasdaq_ipo": "ok", "edgar": "ok", "news": "ok", "manual": "skipped"}
    assert meta["sources"]["news"]["mode"] == "rules"
    assert meta["fx"].startswith("ECB")

    by_issuer = {d["issuer"]: d for d in deals}
    # Nasdaq record and the CNBC headline about the same IPO collapse into one deal.
    nova = [d for d in deals if "Nova Robotics" in (d["issuer"] or "")]
    assert len(nova) == 1 and nova[0]["value_usd"] == 525e6 and len(nova[0]["sources"]) == 2
    # Two outlets reporting Siemens/Altair -> one deal.
    altair = [d for d in deals if d["category"] == "M&A"]
    assert len(altair) == 1 and len(altair[0]["sources"]) == 2
    assert by_issuer["Mixue"]["value_usd"] == pytest.approx(3.45e9 / 7.8)
    assert by_issuer["Mixue"]["region"] == "APAC"
    assert by_issuer["T-Mobile"]["market"] == m.SECONDARY_MARKET
    assert by_issuer["LG Electronics India"]["value_usd"] == pytest.approx(116.07e9 / 88.0)
    assert not any("Stocks to Buy" in (s["title"] or "") for d in deals for s in d["sources"])

    assert filings["daily_counts"]["2026-10-08"]["Selling-holder resale (424B7)"] == 1
    assert len(filings["groups"]) == 8

    # Second run on the same inputs is idempotent.
    assert pipeline.run(tmp_path, config, TODAY) == 0
    again = load(tmp_path, "deals.json")["deals"]
    assert sorted(d["id"] for d in again) == sorted(d["id"] for d in deals)
    assert load(tmp_path, "meta.json")["sources"]["news"]["last_success"]


def test_failing_source_is_isolated(tmp_path, config, fake_net, monkeypatch):
    real = http.get

    def flaky(url, headers=None, **kw):
        if "api.nasdaq.com" in url:
            raise RuntimeError("503 from nasdaq")
        return real(url, headers=headers, **kw)

    monkeypatch.setattr(http, "get", flaky)
    assert pipeline.run(tmp_path, config, TODAY) == 0
    meta = load(tmp_path, "meta.json")
    assert meta["sources"]["nasdaq_ipo"]["status"] == "error"
    assert "503" in meta["sources"]["nasdaq_ipo"]["message"]
    assert meta["sources"]["news"]["status"] == "ok"


def test_all_sources_failing_exits_nonzero(tmp_path, config, monkeypatch):
    def down(url, headers=None, **kw):
        raise RuntimeError("network down")

    monkeypatch.setattr(http, "get", down)
    assert pipeline.run(tmp_path, config, TODAY) == 1
    assert load(tmp_path, "meta.json")["fx"].startswith("fallback")


def test_claude_enrichment_overrides_rules(tmp_path, config, fake_net, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

    def fake_classify(headlines, cfg):
        out = {}
        for i, h in enumerate(headlines):
            if h.startswith("Hong Kong's Mixue"):
                out[i] = {"index": i, "is_deal": True, "deal_type": m.IPO, "status": "Priced",
                          "issuer_or_target": "Mixue Group", "acquirer": None, "value": 3.45e9,
                          "currency": "HKD", "country": "China", "sector": "Consumer"}
            elif "block trade" in h:
                out[i] = {"index": i, "is_deal": False, "deal_type": None, "status": None,
                          "issuer_or_target": None, "acquirer": None, "value": None,
                          "currency": None, "country": None, "sector": None}
        return out

    monkeypatch.setattr(enrich, "classify", fake_classify)
    pipeline.run(tmp_path, config, TODAY, only={"news"})
    deals = load(tmp_path, "deals.json")["deals"]
    mixue = next(d for d in deals if d["issuer"] == "Mixue Group")
    assert (mixue["country"], mixue["sector"], mixue["confidence"]) == ("China", "Consumer", 0.7)
    assert not any(d["issuer"] == "T-Mobile" for d in deals)  # Claude said not a deal
    meta = load(tmp_path, "meta.json")
    assert meta["sources"]["news"]["mode"] == "claude"


def test_enrichment_handles_api_errors(monkeypatch):
    """A failing Claude call degrades to rules instead of crashing the run."""
    anthropic = pytest.importorskip("anthropic")

    class Boom:
        def __init__(self, *a, **k):
            class _M:
                def create(self, **kw):
                    raise anthropic.APIConnectionError(request=None)
            self.beta = type("B", (), {"messages": _M()})()

    monkeypatch.setattr(anthropic, "Anthropic", Boom)
    assert enrich.classify(["X to buy Y"], {"batch_size": 10}) == {}
