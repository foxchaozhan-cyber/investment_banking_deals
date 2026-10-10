import json
from datetime import date
from pathlib import Path

from ibdeals import models as m
from ibdeals.fx import FX, FALLBACK_PER_USD
from ibdeals.sources import edgar, manual, nasdaq_ipo, news

FIX = Path(__file__).parent / "fixtures"


def test_nasdaq_parse_all_buckets():
    deals = nasdaq_ipo.parse(json.loads((FIX / "nasdaq_calendar.json").read_text()))
    by_name = {d.issuer: d for d in deals}
    nova = by_name["Nova Robotics Holdings, Inc."]
    assert (nova.status, nova.date, nova.value_usd, nova.ticker) == ("Priced", "2026-10-08", 525e6, "NOVA")
    assert nova.exchange == "NASDAQ Global Select" and nova.market == m.PRIMARY_MARKET
    assert "dealId=1234567-111111" in nova.sources[0].url
    assert by_name["Gridline Energy Inc."].status == "Expected"
    assert by_name["Gridline Energy Inc."].date == "2026-10-15"
    assert by_name["Cobalt Payments Ltd"].status == "Filed"
    assert len(deals) == 4


def test_nasdaq_months_wrap_year():
    assert nasdaq_ipo._months(date(2026, 12, 5), 1, 1) == ["2026-11", "2026-12", "2027-01"]
    assert nasdaq_ipo._months(date(2026, 1, 5), 1, 0) == ["2025-12", "2026-01"]


def test_edgar_index_parsing_keeps_deal_forms_only():
    rows = edgar.parse_index((FIX / "form.idx").read_text())
    forms = sorted(r["form"] for r in rows)
    # 10-Q and the S-1/A amendment are excluded.
    assert forms == ["424B4", "424B5", "424B5", "424B7", "DEFM14A", "S-1", "S-4", "SC TO-T"]
    # A company name that fills its whole column (one space before the CIK) still parses.
    long_name = next(r for r in rows if r["cik"] == "1999999")
    assert long_name["form"] == "424B5" and long_name["company"].startswith("Extremely Long Company")
    r = next(r for r in rows if r["form"] == "424B7")
    assert r["market"] == m.SECONDARY_MARKET and r["date"] == "2026-10-08"
    assert r["url"] == ("https://www.sec.gov/Archives/edgar/data/1800002/000119312526123458/"
                        "0001193125-26-123458-index.htm")
    assert next(r for r in rows if r["form"] == "S-4")["company"] == "Merging Bank & Trust Co"


def test_news_rss_parsing():
    items = news.parse_rss((FIX / "news.xml").read_bytes(), edition="US")
    assert len(items) == 7
    first = items[0]
    assert first["headline"] == "Siemens agrees to acquire Altair Engineering for $10.6 billion"
    assert first["source"] == "Reuters" and first["published"] == "2026-10-08"
    assert first["url"].startswith("https://news.google.com/rss/articles/")


def test_manual_csv(tmp_path):
    (tmp_path / "export.csv").write_text(
        "Date,Deal_Type,Status,Target,Acquirer,Value,Currency,Country,Source,URL\n"
        "2026-10-01,M&A,Announced,Target AG,Buyer SE,2500,EUR,Germany,LSEG,https://example.com/1\n"
        "2026-10-02,ABB,Priced,Issuer plc,,300000000,GBP,United Kingdom,Dealogic,\n"
        "2026-10-02,unknown type,Priced,Skip Me,,1,USD,,x,\n"
    )
    fx = FX(dict(FALLBACK_PER_USD), "test")
    deals = manual.load(tmp_path, fx)
    assert len(deals) == 2
    mna, block = deals
    assert (mna.category, mna.deal_type, mna.region, mna.origin) == (m.MNA, m.ACQUISITION, "EMEA", "manual")
    assert block.deal_type == m.SECONDARY and block.value_usd == 300e6 / FALLBACK_PER_USD["GBP"]
