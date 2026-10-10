from datetime import date

from ibdeals import models as m
from ibdeals import store


def deal(**kw):
    base = dict(category=m.MNA, deal_type=m.ACQUISITION, date="2026-10-01", status="Announced",
                sources=[m.Source(name="src", title=kw.pop("title", "headline"), url=kw.pop("url", None))])
    base.update(kw)
    return m.Deal(**base)


def test_same_deal_from_two_outlets_merges_and_keeps_both_sources():
    a = deal(issuer="Altair Engineering Inc.", acquirer="Siemens AG", value_usd=10.6e9, url="u1")
    b = deal(issuer="Altair", acquirer="Siemens", date="2026-10-02", url="u2")
    out = store.merge([], [a, b])
    assert len(out) == 1
    assert [s.url for s in out[0].sources] == ["u1", "u2"]
    assert (out[0].announced, out[0].date) == ("2026-10-01", "2026-10-02")


def test_status_progresses_across_days_and_never_regresses():
    first = store.merge([], [deal(issuer="Hess", acquirer="Chevron", status="Announced")])
    later = store.merge(first, [deal(issuer="Hess", acquirer="Chevron", status="Completed", date="2027-03-01")])
    assert len(later) == 1 and later[0].status == "Completed"
    again = store.merge(later, [deal(issuer="Hess", status="Rumored", date="2027-03-02")])
    assert again[0].status == "Completed"


def test_competing_bidders_stay_separate():
    out = store.merge([], [deal(issuer="Target", acquirer="Bidder One"), deal(issuer="Target", acquirer="Bidder Two")])
    assert len(out) == 2
    assert len({d.id for d in out}) == 2


def test_structured_value_beats_news_value():
    news = deal(category=m.ECM, deal_type=m.IPO, issuer="Nova Robotics", value_usd=500e6, value=500e6,
                currency="USD", origin="news", confidence=0.4)
    nasdaq = deal(category=m.ECM, deal_type=m.IPO, issuer="Nova Robotics Holdings, Inc.", value_usd=525e6,
                  value=525e6, currency="USD", origin="structured", confidence=0.95, status="Priced")
    out = store.merge([news], [nasdaq])
    assert len(out) == 1
    assert (out[0].value_usd, out[0].origin, out[0].status) == (525e6, "structured", "Priced")


def test_repeat_follow_ons_months_apart_are_distinct():
    a = deal(category=m.ECM, deal_type=m.FOLLOW_ON, issuer="Big Pharma", date="2026-03-01")
    b = deal(category=m.ECM, deal_type=m.FOLLOW_ON, issuer="Big Pharma", date="2026-09-01")
    assert len(store.merge([], [a, b])) == 2


def test_unnamed_headlines_dedupe_by_similarity():
    a = deal(issuer=None, title="Mystery buyer agrees to acquire chipmaker for $5 billion")
    b = deal(issuer=None, title="Mystery buyer agrees to acquire chipmaker in $5 billion deal", date="2026-10-02")
    c = deal(issuer=None, title="Completely different headline about a bank merger", date="2026-10-02")
    assert len(store.merge([], [a, b, c])) == 2


def test_prune_drops_old_and_small_unsized_news():
    today = date(2026, 10, 10)
    deals = [
        deal(issuer="Old", date="2025-01-01", value_usd=1e9),
        deal(issuer="Recent unsized", date="2026-10-05"),
        deal(issuer="Stale unsized", date="2026-08-01"),
        deal(issuer="Stale large", date="2026-08-01", value_usd=1e9),
        deal(issuer="Stale manual", date="2026-08-01", origin="manual"),
    ]
    kept = {d.issuer for d in store.prune(deals, today, 400, 30, 25e6)}
    assert kept == {"Recent unsized", "Stale large", "Stale manual"}


def test_roundtrip_serialisation():
    d = deal(issuer="X", acquirer="Y", value_usd=1.0)
    again = m.Deal.from_dict(d.to_dict())
    assert again.to_dict() == d.to_dict()
    assert d.to_dict()["market"] is None


def test_filings_merge_counts_and_retention():
    rows = [
        {"accession": "a1", "form": "S-1", "group": "G1", "date": "2026-10-08", "company": "A"},
        {"accession": "a2", "form": "S-1", "group": "G1", "date": "2026-10-08", "company": "B"},
        {"accession": "a3", "form": "424B7", "group": "G2", "date": "2026-10-07", "company": "C"},
    ]
    existing = {"daily_counts": {"2026-01-02": {"G1": 4}, "2024-01-02": {"G1": 1}}, "recent": [rows[0]]}
    out = store.merge_filings(existing, rows, date(2026, 10, 10), retention_days=400)
    assert out["daily_counts"]["2026-10-08"] == {"G1": 2}  # a1 not double counted
    assert out["daily_counts"]["2026-01-02"] == {"G1": 4}  # carried forward
    assert "2024-01-02" not in out["daily_counts"]
    assert [r["accession"] for r in out["recent"]] == ["a2", "a1", "a3"]


def test_same_size_and_target_with_differently_named_buyers_merge():
    a = deal(issuer="Boots", acquirer="Wittington Investments", value_usd=8.9e9, url="u1")
    b = deal(issuer="Boots", acquirer="Weston family", value_usd=8.9e9, date="2026-10-02", url="u2")
    stake = deal(issuer="Boots", acquirer="Fairfax Financial", value_usd=2.3e9, date="2026-10-02", url="u3")
    out = store.merge([], [a, b, stake])
    assert sorted(len(d.sources) for d in out) == [1, 2]


def test_same_size_and_buyer_with_differently_named_targets_merge():
    a = deal(issuer="Devon Eagle Ford Assets", acquirer="Crescent Energy", value_usd=4.22e9, url="u1")
    b = deal(issuer="Eagle Ford assets", acquirer="Crescent Energy", value_usd=4.2e9, url="u2")
    assert len(store.merge([], [a, b])) == 1
