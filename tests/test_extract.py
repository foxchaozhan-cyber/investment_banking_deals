import pytest

from ibdeals import extract as x
from ibdeals import models as m

# headline, deal_type, status, issuer/target, acquirer, (amount, currency) | None, country
CASES = [
    ("Synopsys agrees to buy Ansys for $35 billion in cash-and-stock deal",
     m.ACQUISITION, "Announced", "Ansys", "Synopsys", (35e9, "USD"), None),
    ("Exclusive: Blackstone in talks to take Jamf private for about $2.2 billion",
     m.BUYOUT, "Rumored", "Jamf", "Blackstone", (2.2e9, "USD"), None),
    ("Chevron completes acquisition of Hess", m.ACQUISITION, "Completed", "Hess", "Chevron", None, None),
    ("Hong Kong's Mixue raises HK$3.45 billion in IPO", m.IPO, "Priced", "Mixue", None, (3.45e9, "HKD"), "Hong Kong"),
    ("LG Electronics India IPO priced at Rs 1,140 per share to raise Rs 11,607 crore",
     m.IPO, "Priced", "LG Electronics India", None, (116.07e9, "INR"), "India"),
    ("SoftBank sells stake in T-Mobile via block trade worth $4.8 billion",
     m.SECONDARY, "Announced", "T-Mobile", None, (4.8e9, "USD"), None),
    ("Klarna prices IPO at $40 a share, valuing it at $15 billion", m.IPO, "Priced", "Klarna", None, None, None),
    ("Capital One and Discover to merge in $35 billion deal",
     m.MERGER, "Announced", "Discover", "Capital One", (35e9, "USD"), None),
    ("Shell launches $3bn tender offer for BG Group", m.TENDER, "Announced", "BG Group", "Shell", (3e9, "USD"), None),
    ("Strategy announces $2 billion convertible notes offering",
     m.CONVERTIBLE, "Announced", "Strategy", None, (2e9, "USD"), None),
    ("Unilever plans €1.5bn rights issue", m.FOLLOW_ON, "Expected", "Unilever", None, (1.5e9, "EUR"), "Europe"),
    ("Nippon Steel's $14.9 billion bid for U.S. Steel blocked by Biden",
     m.ACQUISITION, "Terminated", "U.S. Steel", "Nippon Steel", (14.9e9, "USD"), "United States"),
    ("Mubadala buys 20% stake in Getir for $500 million",
     m.ACQUISITION, "Announced", "Getir", "Mubadala", (5e8, "USD"), None),
    ("Japan's Seven & i rejects Couche-Tard's $47 billion offer",
     m.ACQUISITION, "Announced", "Seven & i", "Couche-Tard", (47e9, "USD"), "Japan"),
    ("Shein files confidentially for Hong Kong IPO", m.IPO, "Filed", "Shein", None, None, "Hong Kong"),
    ("Aramco raises $11.2 billion in secondary share offering",
     m.SECONDARY, "Priced", "Aramco", None, (11.2e9, "USD"), "Saudi Arabia"),
    # Real headline shapes from the first live run.
    ("Crescent Energy to Buy Devon Eagle Ford Assets for $4.22 Billion, Secures $2.0 Billion Bridge",
     m.ACQUISITION, "Announced", "Devon Eagle Ford Assets", "Crescent Energy", (4.22e9, "USD"), None),
    ("PTC Industries Raises Nearly ₹18,000 Crore Via Institutional Share Placement",
     m.FOLLOW_ON, "Priced", "PTC Industries", None, (180e9, "INR"), "India"),
    ("Copart Extends ACV Auctions Tender Offer to Oct. 15 as Tendered Shares Pass 50%",
     m.TENDER, "Announced", "ACV Auctions", "Copart", None, None),
    ("Tata Motors Unit Raises Iveco Group Tender Offer To €14.40 Per Share, total Outlay ₹34,778 crore",
     m.TENDER, "Announced", "Iveco Group", "Tata Motors", (347.78e9, "INR"), "India"),
    ("Pacira BioSciences to Be Acquired by Viatris in $36.50-Per-Share All-Cash Tender Offer",
     m.TENDER, "Announced", "Pacira BioSciences", "Viatris", None, None),
    ("Starbucks hires advisors for possible Chipotle takeover bid",
     m.ACQUISITION, "Rumored", None, None, None, None),
    ("Ola Electric Shares Crash 8% As Board Sets Rs 27 Rights Issue Price",
     m.FOLLOW_ON, "Announced", "Ola Electric", None, None, "India"),
    ("Infineon Completes Acquisition of C2i Semiconductors",
     m.ACQUISITION, "Completed", "C2i Semiconductors", "Infineon", None, None),
]


@pytest.mark.parametrize("headline,deal_type,status,target,acquirer,money,country", CASES)
def test_headline_extraction(headline, deal_type, status, target, acquirer, money, country):
    category, got_type = x.classify(headline)
    assert got_type == deal_type
    assert category == m.CATEGORY_BY_TYPE[deal_type]
    assert x.status_for(category, headline, deal_type) == status
    assert x.parties(category, headline) == (target, acquirer)
    size = x.deal_size(headline, category)
    if money is None:
        assert size is None
    else:
        assert size.amount == pytest.approx(money[0])
        assert size.currency == money[1]
    assert x.country_for(headline) == country


@pytest.mark.parametrize("headline", [
    "Top 5 stocks to buy before the Fed meeting",
    "Apple announces $110 billion share buyback",
    "Analysts raise price target on Nvidia to $250",
    "Fed holds rates steady as inflation cools",
    "Hudson Pacific Properties Announces Expiration and Tender Results of Cash Tender Offer for Outstanding Notes",
    "CrowdStrike warns shareholders against mini-tender offer",
    "India’s IPO Market Raises Record Dollar 12.5 Billion in Nine Months",
    "Dividend, Rights Issue, Stock Split Alert: Five stocks that will see corporate actions next week",
    "Is InPost (ENXTAM:INPST) Fully Valued On Its Completed €7b Take Private Deal?",
    "Jeff Bezos Says Blue Origin IPO Likely in Coming Years After Space Company Raises $10 Billion From Investors",
])

def test_noise_is_not_a_deal(headline):
    assert x.classify(headline) is None


def test_clean_headline_strips_publisher_and_wire_prefix():
    assert x.clean_headline("UPDATE 2-Novartis to buy Avidity - Reuters", "Reuters") == "Novartis to buy Avidity"
    assert x.clean_headline("Exclusive: X weighs IPO - The Wall Street Journal") == "X weighs IPO"


def test_amount_formats():
    amounts = [(a.amount, a.currency) for a in x.find_amounts(
        "US$1.2 billion, €300m, £45 mln, 5 billion yuan, ¥200bn, A$2.5bn and $18 per share")]
    assert amounts == [(1.2e9, "USD"), (3e8, "EUR"), (4.5e7, "GBP"), (5e9, "CNY"), (2e11, "JPY"), (2.5e9, "AUD")]


def test_question_headline_with_a_real_deal_is_kept():
    h = "Sun Pharma’s Biggest Global Bet, Buys Organon in $11.75 Billion Deal; Pharma Stock Surge 7% - Time to Buy?"
    assert x.classify(h) == (m.MNA, m.ACQUISITION)
    assert x.deal_size(h, m.MNA).amount == pytest.approx(11.75e9)
