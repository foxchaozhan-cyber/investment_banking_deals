"""Rule-based extraction of deal facts from a news headline.

This is the keyless baseline. When an Anthropic API key is configured,
`enrich.py` re-extracts the same headlines with Claude and overrides these
results; anything Claude cannot process falls back to what is computed here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import models as m

# --- Money -----------------------------------------------------------------

_SCALE = {
    "trillion": 1e12, "tn": 1e12, "tln": 1e12,
    "billion": 1e9, "bn": 1e9, "bln": 1e9, "b": 1e9,
    "million": 1e6, "mln": 1e6, "mn": 1e6, "m": 1e6,
    "crore": 1e7, "cr": 1e7, "lakh": 1e5,
}
_PREFIX_CCY = {
    "US$": "USD", "USD": "USD", "$": "USD", "HK$": "HKD", "HKD": "HKD",
    "A$": "AUD", "AU$": "AUD", "AUD": "AUD", "C$": "CAD", "CA$": "CAD", "CAD": "CAD",
    "S$": "SGD", "SGD": "SGD", "NZ$": "NZD", "R$": "BRL", "€": "EUR", "EUR": "EUR",
    "£": "GBP", "GBP": "GBP", "¥": "JPY", "JPY": "JPY", "CNY": "CNY", "RMB": "CNY",
    "Rs": "INR", "Rs.": "INR", "INR": "INR", "₹": "INR", "CHF": "CHF", "SEK": "SEK",
    "NOK": "NOK", "DKK": "DKK", "SAR": "SAR", "AED": "AED", "KRW": "KRW", "₩": "KRW",
}
_SUFFIX_CCY = {
    "yuan": "CNY", "renminbi": "CNY", "yen": "JPY", "euro": "EUR", "euros": "EUR",
    "pounds": "GBP", "rupees": "INR", "riyals": "SAR", "riyal": "SAR",
    "dirhams": "AED", "dollars": "USD", "francs": "CHF", "crowns": "SEK",
}
_NUM = r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
_UNIT = r"(trillion|billion|million|crore|lakh|tln|bln|mln|tn|bn|mn|cr|b|m)\b"
_PREFIX_RE = re.compile(
    r"(US\$|HK\$|AU\$|NZ\$|CA\$|A\$|C\$|S\$|R\$|USD|HKD|AUD|CAD|SGD|EUR|GBP|JPY|CNY|RMB|INR|"
    r"CHF|SEK|NOK|DKK|SAR|AED|KRW|Rs\.?|\$|€|£|¥|₹|₩)\s?" + _NUM + r"(?:\s?-?(?i:" + _UNIT + r"))?",
)
_SUFFIX_RE = re.compile(
    _NUM + r"\s?" + _UNIT + r"\s+(" + "|".join(_SUFFIX_CCY) + r")\b", re.IGNORECASE
)
# Amounts that are not the deal size: per-share prices and valuations.
_NOT_SIZE_AFTER = re.compile(r"^\s*(?:per|a|each)\s+(?:share|ADS|unit)", re.IGNORECASE)
_VALUATION_BEFORE = re.compile(
    r"(?:valu\w*|market (?:cap\w*|value)|price target)\b[^$€£¥₹\d]{0,25}$", re.IGNORECASE
)


@dataclass
class Money:
    amount: float
    currency: str
    start: int


def find_amounts(text: str) -> list[Money]:
    out: list[Money] = []
    for mt in _PREFIX_RE.finditer(text):
        sym, num, unit = mt.group(1), mt.group(2), mt.group(3)
        # Reject "$" that is the tail of an unrecognised prefix like "NT$".
        if sym == "$" and mt.start() > 0 and text[mt.start() - 1].isalpha():
            continue
        amount = float(num.replace(",", ""))
        if unit:
            amount *= _SCALE[unit.lower()]
        elif amount < 1e6:
            continue  # "$18" is a share price, not a deal size
        if _NOT_SIZE_AFTER.match(text[mt.end():]):
            continue
        out.append(Money(amount, _PREFIX_CCY[sym], mt.start()))
    for mt in _SUFFIX_RE.finditer(text):
        amount = float(mt.group(1).replace(",", "")) * _SCALE[mt.group(2).lower()]
        out.append(Money(amount, _SUFFIX_CCY[mt.group(3).lower()], mt.start()))
    out.sort(key=lambda x: x.start)
    return out


def deal_size(text: str, category: str | None) -> Money | None:
    """First amount in the headline that plausibly describes the deal size."""
    for money in find_amounts(text):
        before = text[: money.start]
        if category == m.ECM and _VALUATION_BEFORE.search(before):
            continue  # "IPO valuing the company at $10bn" -> not proceeds
        return money
    return None


# --- Classification --------------------------------------------------------

def _rx(p: str) -> re.Pattern[str]:
    return re.compile(p, re.IGNORECASE)


_NOISE = _rx(
    r"\b(stocks? to buy|shares to buy|buy rating|strong buy|should you buy|buy the dip|"
    r"buy or sell|buyback|share repurchase|repurchase program|price target|analysts?|"
    r"top \d+|best (?:stocks|ipos)|how to|what is|explained|opinion|podcast|webinar|"
    r"etf|mutual fund|crypto(?:currency)?|bitcoin|token sale|watchlist|grey market premium|gmp|"
    r"mini-tender|corporate actions?|stocks that|IPO market|IPO pipeline|IPOs? (?:this|next) week|IPO calendar|"
    r"upcoming IPOs|IPO frenzy|fully valued|undervalued|overvalued|what it means|should investors|is it time|"
    r"key takeaways|things to know|week ahead|funding round|series [a-h]|seed round|from investors|"
    r"venture capital|tender results|dutch auction|self-tender|"
    r"tender offers? for (?:its |any and all |all |outstanding |certain |the )*(?:[\w.%$-]+ ){0,4}"
    r"(?:notes|bonds|debentures|debt|securities))\b"
)
_ECM_SECONDARY = _rx(
    r"\b(block trade|block sale|accelerated bookbuild|overnight placing|sell-?down|"
    r"secondary (?:share )?(?:offering|sale)|share sale by|offloads?|sells? (?:a |its |part of its )?"
    r"(?:\d+(?:\.\d+)?% )?(?:stake|shares|holding)s? (?:in|of) .+ (?:via|through|in a) (?:placement|placing|block|bookbuild|share sale|offering))\b"
)
_ECM_CONVERTIBLE = _rx(r"\b(convertible (?:bonds?|notes?|senior notes|debt|offering)|exchangeable (?:bonds?|notes?))\b")
_MNA_TENDER = _rx(r"\b(tender offer)\b")
_MNA_BUYOUT = _rx(r"\b(take[- ]private|taking .+ private|to take .+ private|go[- ]private|leveraged buyout|LBO|buyout)\b")
_MNA_MERGER = _rx(r"\b(merger|merge|merges|merging|all-stock combination|combine with)\b")
_MNA_ACQ = _rx(
    r"\b(acquire|acquires|acquired|acquiring|acquisition|to buy|buys|bought|agrees to buy|"
    r"agreed to buy|purchase of|to purchase|purchases|takeover|take over|takes over|snaps? up|"
    r"bid for|deal for|offer for|takeover bid|takeover offer|hostile bid|unsolicited (?:bid|offer))\b"
    r"|(?:'s|’s)\s+(?:[$€£¥][\d.,]+\s*\w+\s+)?(?:\w+\s+)?(?:bid|offer|approach)\b"
)
_ECM_IPO = _rx(r"\b(IPO|IPOs|initial public offering|listing debut|market debut|trading debut|debuts? on|"
               r"to list on|lists? on|DRHP|draft red herring|direct listing)\b")
_ECM_FOLLOW_ON = _rx(
    r"\b(follow-on offering|follow-on|share offering|stock offering|equity offering|equity raise|"
    r"capital raise|capital increase|rights issue|rights offering|QIP|qualified institutional placement|"
    r"share placement|placement of new shares|private placement|raises? .{0,40}(?:share sale|stock sale|equity))\b"
)


# Commentary phrased as a question ("Is X fully valued after ...?").
_QUESTION = re.compile(r"^(?:is|are|why|what|how|did|does|do|should|can|could|will|would|has|have)\b.*\?\s*$",
                       re.IGNORECASE)


def classify(headline: str) -> tuple[str, str] | None:
    """Return (category, deal_type) or None when the headline is not a deal."""
    if _NOISE.search(headline) or _QUESTION.match(headline):
        return None
    if _ECM_SECONDARY.search(headline):
        return m.ECM, m.SECONDARY
    if _ECM_CONVERTIBLE.search(headline):
        return m.ECM, m.CONVERTIBLE
    if _MNA_TENDER.search(headline):
        return m.MNA, m.TENDER
    if _MNA_BUYOUT.search(headline):
        return m.MNA, m.BUYOUT
    if _ECM_IPO.search(headline):
        # "X to acquire Y ahead of IPO" is still M&A.
        if _MNA_ACQ.search(headline) and not re.search(r"\bIPO\b.*\b(acquire|buy)", headline, re.I):
            return m.MNA, m.ACQUISITION
        return m.ECM, m.IPO
    if _MNA_MERGER.search(headline) and not _MNA_ACQ.search(headline):
        return m.MNA, m.MERGER
    if _MNA_ACQ.search(headline):
        return m.MNA, m.ACQUISITION
    if _ECM_FOLLOW_ON.search(headline):
        return m.ECM, m.FOLLOW_ON
    return None


_MNA_STATUS = [
    ("Terminated", _rx(r"\b(terminat\w*|calls? off|called off|scrap\w*|abandon\w*|walks? away|collaps\w*|"
                       r"blocks?|blocked|withdraws? (?:its )?(?:bid|offer)|drops? (?:bid|pursuit|offer))\b")),
    ("Completed", _rx(r"\b(complet(?:es|ed|ion)|closes|closed|finali[sz](?:es|ed))\b")),
    ("Pending", _rx(r"\b(approv\w*|clears|cleared|wins? (?:\w+ )?(?:nod|approval)|shareholders back|vote)\b")),
    ("Rumored", _rx(r"\b(in talks|talks to|held talks|consider\w*|explor\w*|weigh\w*|mull\w*|eyes|eyeing|"
                    r"nears?|said to|sources|reportedly|approach\w*|could|may|might|interest in|"
                    r"preparing (?:a )?bid|potential|possible|hires? (?:\w+ )?advis[eo]rs?|advis[eo]rs)\b")),
]
_ECM_STATUS = [
    ("Withdrawn", _rx(r"\b(postpon\w*|withdraw\w*|pulls?|pulled|shelv\w*|scrap\w*|delays?|delayed|cancel\w*)\b")),
    ("Completed", _rx(r"\b(debut\w*|begins trading|starts trading|first day of trading|lists? on|listed on|"
                      r"completes?|completed|closes|closed)\b")),
    ("Listed", _rx(r"\bshares (?:jump|soar|surge|fall|slide|rise|climb|sink|tumble|pop)\w*")),
    ("Priced", _rx(r"\b(prices|priced|pricing|raises|raised|raising|fetch\w*|nets|netted|upsiz\w*|"
                   r"oversubscribed|subscribed \d+)\b")),
    ("Filed", _rx(r"\b(files|filed|filing|confidentially|DRHP|draft red herring|prospectus)\b")),
    ("Expected", _rx(r"\b(plans?|planning|consider\w*|eyes|eyeing|weigh\w*|mull\w*|prepar\w*|seeks?|"
                     r"targets?|aims?|could|may|said to|set to|to launch|launch\w*|kicks? off|opens?|"
                     r"hires?|picks? banks|sounds out)\b")),
]


def status_for(category: str, headline: str, deal_type: str | None = None) -> str:
    rules = _MNA_STATUS if category == m.MNA else _ECM_STATUS
    for status, rx in rules:
        if status == "Listed":
            # A share-price move on listing day means the IPO is done; for a
            # follow-on it is just market colour.
            if deal_type == m.IPO and rx.search(headline):
                return "Completed"
            continue
        if rx.search(headline):
            return status
    return "Announced"


# --- Parties ---------------------------------------------------------------

_LEAD_NOISE = re.compile(
    r"^(?:(?:exclusive|breaking|update\s*\d*|brief|correct(?:ed|ion)|refile|analysis|"
    r"factbox|deals day ahead|reuters|bloomberg|watch|video|live|insight)\s*[-:|–—]\s*)+",
    re.IGNORECASE,
)
_STOP = (r"(?=\s+(?:for|in|at|from|valued|worth|with|amid|after|as|to|via|on|by|deal|"
         r"plans?|seeks?|that|which|while|ahead|over|blocked|rejected|approved|cleared|wins|clears|"
         r"is|was|gets|faces|draws|sparks|collapses|ends|shares|stock|sees|hits|nears|receives|attracts|"
         r"reaches|passes)\b|\s*[,;:(|–—]|\s+-\s|$)")
_VERBS_ACQ = (r"(?:(?:agrees?|agreed|is set|set|moves|plans|is|are|nears deal|in talks|"
              r"said|announces|announced|signs deal|reaches deal|strikes deal|seals deal|will)\s+)?"
              r"(?:to\s+)?(?:acquire|acquires|acquired|buy|buys|bought|purchase|purchases|"
              r"take over|takes over|snap up|snaps up)"
              r"(?:\s+(?:a\s+|an\s+|the\s+)?(?:\d+(?:\.\d+)?%\s+|majority\s+|minority\s+|controlling\s+|"
              r"remaining\s+)?(?:stake|holding|interest)\s+in)?")
_STAKE = re.compile(r"^(?:(?:a|an|the)\s+)?(?:\d+(?:\.\d+)?%\s+|majority\s+|minority\s+|controlling\s+|"
                    r"remaining\s+)?(?:stake|holding|interest)\s+in\s+", re.IGNORECASE)
_TRIM_ARTICLE = re.compile(r"^(?:(?:the|a|an|rival|peer|fellow|smaller|larger)\s+)+", re.IGNORECASE)
# "Hong Kong's Mixue raises ..." -> "Mixue"; "Japan's Toyota" -> "Toyota".
_PLACE_POSSESSIVE = re.compile(
    r"^(?:Hong Kong|China|Chinese|India|Indian|Japan|Japanese|South Korea|Korea|Taiwan|Singapore|"
    r"Australia|Indonesia|Malaysia|Thailand|Vietnam|Saudi Arabia|Saudi|UAE|Dubai|Abu Dhabi|Qatar|"
    r"Israel|Turkey|Britain|UK|U\.K\.|Germany|France|Italy|Spain|Sweden|Norway|Denmark|Finland|"
    r"Switzerland|Netherlands|Canada|Brazil|Mexico|U\.S\.|US|America|Europe)(?:'s|’s)\s+"
)
_ACQUIRER_TAIL = re.compile(
    r"\s+(?:is\s+|are\s+)?(?:in\s+(?:advanced\s+|early\s+|exclusive\s+)?talks|nears?\s+deal|said\s+to\s+be|"
    r"reportedly|plans|planning|agrees|agreed|is\s+set|set|moves|considers|considering|weighs|explores|"
    r"is|are|will|could|may)$",
    re.IGNORECASE,
)
_ISSUER_TAIL = re.compile(
    r"\s+(?:IPO|initial public offering|share sale|listing|offering|stock|shares?)$", re.IGNORECASE
)

_MNA_PATTERNS = [
    re.compile(r"^(?P<a>.+?)\s+(?:completes|completed|closes|closed|finali[sz]es)\s+(?:its\s+|the\s+)?"
               r"(?:[$€£¥][\d.,]+\s*\w+\s+)?(?:acquisition|purchase|takeover|buyout|merger)\s+(?:of|with)\s+"
               r"(?P<t>.+?)" + _STOP, re.IGNORECASE),
    re.compile(r"^(?P<a>.+?)\s+to\s+take\s+(?P<t>.+?)\s+private\b", re.IGNORECASE),
    # "Pacira to be acquired by Viatris"
    re.compile(r"^(?P<t>.+?)\s+(?:to\s+be|is\s+being|will\s+be|agrees\s+to\s+be|set\s+to\s+be)\s+"
               r"(?:acquired|bought|taken\s+private|purchased)\s+by\s+(?P<a>.+?)" + _STOP, re.IGNORECASE),
    # "Copart extends ACV Auctions tender offer", "KKR postpones Taiyo Holdings tender offer"
    re.compile(r"^(?P<a>.+?)\s+(?i:extends|raises|delays|postpones|launches|completes|lifts|sweetens|ups|"
               r"increases|begins|commences|withdraws|drops|abandons|wins|closes|advances|starts|confirms|"
               r"announces|makes|revises)\s+(?i:its\s+|the\s+)?(?:[$€£¥][\d.,]+\s*\w+\s+)?(?P<t>[A-Z][\w&.\'-]*"
               r"(?:\s+[A-Z0-9][\w&.\'-]*){0,4})\s+(?:tender\s+offer|takeover\s+bid|takeover\s+offer|takeover|"
               r"buyout|acquisition|bid)\b", re.IGNORECASE),
    # "Target rejects Bidder's $47 billion offer"
    re.compile(r"^(?P<t>.+?)\s+(?:rejects|rebuffs|spurns|accepts|backs|weighs|considers|receives|gets)\s+"
               r"(?P<a>.+?)(?:'s|’s)\s+(?:[$€£¥][\d.,]+\s*\w+\s+)?(?:\w+\s+)?(?:bid|offer|approach|proposal)\b",
               re.IGNORECASE),
    re.compile(r"^(?P<a>.+?)(?:'s|’s)\s+(?:[$€£¥][\d.,]+\s*\w+\s+)?(?:hostile\s+|all-cash\s+)?(?:tender\s+)?"
               r"(?:bid|offer|takeover|acquisition|purchase|deal|merger)\s+(?:for|of|with)\s+(?P<t>.+?)" + _STOP,
               re.IGNORECASE),
    re.compile(r"^(?P<a>.+?)\s+(?:launches|commences|makes|lodges|submits|tables|ups|raises|sweetens|confirms|"
               r"announces|extends|amends|completes|increases|improves|revises|prepares|plans|weighs|considers)\s+"
               r"(?:an?\s+|its\s+|the\s+)?(?:preliminary\s+|final\s+|revised\s+|improved\s+|possible\s+)?(?:[$€£¥][\d.,]+\s*\w+\s+)?(?:hostile\s+|unsolicited\s+|all-cash\s+|cash\s+)?"
               r"(?:tender\s+offer|takeover\s+bid|takeover\s+offer|bid|offer)\s+for\s+(?P<t>.+?)" + _STOP,
               re.IGNORECASE),
    re.compile(r"^(?P<a>.+?)\s+(?:and|&)\s+(?P<t>.+?)\s+(?:to\s+merge|agree\s+to\s+merge|announce\s+merger|"
               r"in\s+merger|merge)\b", re.IGNORECASE),
    re.compile(r"^(?P<a>.+?)\s+(?:to\s+merge|merges|agrees\s+to\s+merge|will\s+merge)\s+with\s+(?P<t>.+?)" + _STOP,
               re.IGNORECASE),
    re.compile(r"^(?P<a>.+?)\s+" + _VERBS_ACQ + r"\s+(?P<t>.+?)" + _STOP, re.IGNORECASE),
]

_ECM_ISSUER_PATTERNS = [
    # "Seller sells stake in Issuer via block trade"
    re.compile(r"\b(?:stake|shares|holding)s?\s+in\s+(?P<i>.+?)" + _STOP, re.IGNORECASE),
    re.compile(r"\bblock\s+(?:trade|sale)\s+(?:of|in)\s+(?P<i>.+?)(?:\s+shares)?" + _STOP, re.IGNORECASE),
    # "Issuer's $1bn IPO ..."
    re.compile(r"^(?P<i>.+?)(?:'s|’s)\s+(?:[$€£¥₹][\d.,]+\s*\w+\s+|\w+\s+)?(?:IPO|initial public offering|"
               r"share sale|listing|placement|rights issue|offering|debut|convertible)", re.IGNORECASE),
    # "Issuer prices / raises / files for ..."
    re.compile(r"^(?P<i>.+?)\s+(?:prices?|priced|raises?|raised|files?|filed|launch(?:es|ed)?|plans?|planning|"
               r"seeks?|eyes|weighs|considers|is set|sets?|kicks? off|opens?|targets?|aims?|debuts?|jumps?|"
               r"soars?|surges?|slumps?|falls?|rises?|climbs?|crash(?:es)?|plunges?|tanks?|slides?|sinks?|"
               r"tumbles?|gains?|drops?|gets?|wins?|receives?|announces?|announced|proposes?|postpones?|"
               r"withdraws?|pulls?|shelves|to raise|to launch|to list|lists?|sells?|sold|offers?|pops?|"
               r"hires?|picks?|approves?|fixes|confidentially|board)\b", re.IGNORECASE),
]


def _clean_party(s: str | None) -> str | None:
    if not s:
        return None
    s = _PLACE_POSSESSIVE.sub("", s.strip(" '\"‘’“”.-"))
    s = re.sub(r"^.*\b[\w-]+-(?:led|backed|owned|based|listed)\s+", "", s, flags=re.IGNORECASE)
    if re.search(r"\b(?:block trade|on-market|placement|offering|IPO market)\b", s, re.IGNORECASE):
        return None
    s = _TRIM_ARTICLE.sub("", s)
    s = _STAKE.sub("", s)
    for _ in range(2):
        s = _ACQUIRER_TAIL.sub("", s)
        s = _ISSUER_TAIL.sub("", s)
    s = re.sub(r"\s+(?:shares?|stock|unit|business)$", "", s, flags=re.IGNORECASE).strip()
    if not s or len(s) > 60 or len(s.split()) > 8:
        return None
    if not (s[0].isupper() or s[0].isdigit()):
        return None
    return s


def clean_headline(title: str, source_name: str | None = None) -> str:
    t = title.strip()
    if source_name and t.endswith(f" - {source_name}"):
        t = t[: -len(source_name) - 3]
    elif " - " in t:
        head, _, tail = t.rpartition(" - ")
        if len(tail) <= 40:  # Google News appends " - Publisher"
            t = head
    return _LEAD_NOISE.sub("", t).strip()


_REPORTING_VERB = re.compile(r"\s+(?:announces?|confirms?|extends?|completes?|launches|says|reports|"
                             r"updates|welcomes|backs)\b.*$", re.IGNORECASE)


def parties(category: str, headline: str) -> tuple[str | None, str | None]:
    """Return (issuer_or_target, acquirer)."""
    h = _LEAD_NOISE.sub("", headline)
    if category == m.MNA:
        for rx in _MNA_PATTERNS:
            mt = rx.search(h)
            if mt:
                target = _clean_party(mt.group("t"))
                acquirer = _clean_party(_REPORTING_VERB.sub("", mt.group("a")))
                if target:
                    return target, acquirer
        return None, None
    for rx in _ECM_ISSUER_PATTERNS:
        mt = rx.search(h)
        if mt:
            issuer = _clean_party(mt.group("i"))
            if issuer:
                return issuer, None
    return None, None


# --- Geography -------------------------------------------------------------

# Checked in order; the first match wins. Case-sensitive on purpose so that
# tickers/acronyms do not collide with ordinary words.
_GEO = [
    (r"Hong Kong|HKEX|Hang Seng|HK\$", "Hong Kong"),
    (r"Nasdaq Stockholm|Stockholm|Sweden|Swedish", "Sweden"),
    (r"Shanghai|Shenzhen|STAR Market|ChiNext|Beijing|China|Chinese|yuan|RMB", "China"),
    (r"India|Indian|NSE|BSE|Mumbai|SEBI|Sebi|QIP|DRHP|crore|₹|Rs\.?\s?\d", "India"),
    (r"Japan|Japanese|Tokyo|TSE|yen", "Japan"),
    (r"South Korea|Korea|Korean|KOSPI|KOSDAQ|Seoul", "South Korea"),
    (r"Taiwan|Taipei", "Taiwan"),
    (r"Singapore|SGX|S\$", "Singapore"),
    (r"Australia|Australian|ASX|A\$", "Australia"),
    (r"New Zealand|NZX", "New Zealand"),
    (r"Indonesia|Jakarta", "Indonesia"),
    (r"Malaysia|Bursa", "Malaysia"),
    (r"Thailand|Thai|Bangkok", "Thailand"),
    (r"Vietnam|Vietnamese", "Vietnam"),
    (r"Philippines|Philippine|Manila", "Philippines"),
    (r"Saudi|Tadawul|Aramco|riyal", "Saudi Arabia"),
    (r"UAE|Dubai|Abu Dhabi|ADX|DFM|Emirati|dirham", "United Arab Emirates"),
    (r"Qatar|Doha", "Qatar"),
    (r"Israel|Israeli|Tel Aviv", "Israel"),
    (r"Turkey|Turkish|Istanbul", "Turkey"),
    (r"South Africa|Johannesburg|JSE", "South Africa"),
    (r"Egypt|Nigeria|Kenya", "Africa"),
    (r"Britain|British|U\.K\.|UK|London|LSE|FTSE|£", "United Kingdom"),
    (r"Germany|German|Frankfurt|DAX", "Germany"),
    (r"France|French|Paris", "France"),
    (r"Netherlands|Dutch|Amsterdam", "Netherlands"),
    (r"Spain|Spanish|Madrid", "Spain"),
    (r"Italy|Italian|Milan", "Italy"),
    (r"Switzerland|Swiss|Zurich|CHF", "Switzerland"),
    (r"Norway|Norwegian|Oslo", "Norway"),
    (r"Denmark|Danish|Copenhagen", "Denmark"),
    (r"Finland|Finnish|Helsinki", "Finland"),
    (r"Poland|Polish|Warsaw", "Poland"),
    (r"Ireland|Irish|Dublin", "Ireland"),
    (r"Belgium|Belgian|Brussels", "Belgium"),
    (r"Austria|Austrian|Vienna", "Austria"),
    (r"Canada|Canadian|TSX|Toronto|C\$", "Canada"),
    (r"Brazil|Brazilian|B3|Sao Paulo|São Paulo", "Brazil"),
    (r"Mexico|Mexican", "Mexico"),
    (r"Argentina|Chile|Colombia|Peru", "Latin America"),
    (r"NYSE|Nasdaq|U\.S\.|US|Wall Street|American", "United States"),
    (r"€|Europe|European|Euronext", "Europe"),
]
_GEO_RX = [(re.compile(r"(?<![A-Za-z])(?:" + p + r")(?![a-z])"), c) for p, c in _GEO]

REGION_BY_COUNTRY = {
    "United States": "Americas", "Canada": "Americas", "Brazil": "Americas",
    "Mexico": "Americas", "Latin America": "Americas",
    "United Kingdom": "EMEA", "Germany": "EMEA", "France": "EMEA", "Netherlands": "EMEA",
    "Spain": "EMEA", "Italy": "EMEA", "Switzerland": "EMEA", "Sweden": "EMEA", "Norway": "EMEA",
    "Denmark": "EMEA", "Finland": "EMEA", "Poland": "EMEA", "Ireland": "EMEA", "Belgium": "EMEA",
    "Austria": "EMEA", "Saudi Arabia": "EMEA", "United Arab Emirates": "EMEA", "Qatar": "EMEA",
    "Israel": "EMEA", "Turkey": "EMEA", "South Africa": "EMEA", "Africa": "EMEA", "Europe": "EMEA",
    "Luxembourg": "EMEA", "Portugal": "EMEA", "Greece": "EMEA",
    "Hong Kong": "APAC", "China": "APAC", "India": "APAC", "Japan": "APAC", "South Korea": "APAC",
    "Taiwan": "APAC", "Singapore": "APAC", "Australia": "APAC", "New Zealand": "APAC",
    "Indonesia": "APAC", "Malaysia": "APAC", "Thailand": "APAC", "Vietnam": "APAC",
    "Philippines": "APAC",
}


def country_for(text: str) -> str | None:
    for rx, country in _GEO_RX:
        if rx.search(text):
            return country
    return None


def region_for(country: str | None) -> str | None:
    return REGION_BY_COUNTRY.get(country or "")
