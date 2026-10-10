"""Deal record shared by every source, the store and the dashboard."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Any

# --- Vocabulary -------------------------------------------------------------

ECM = "ECM"
MNA = "M&A"

# ECM deal types. "Primary" raises new money for the issuer; "Secondary" is a
# sale of existing shares by holders (sell-downs, block trades).
IPO = "IPO"
FOLLOW_ON = "Follow-on"
SECONDARY = "Secondary / Block"
CONVERTIBLE = "Convertible"
# M&A deal types.
ACQUISITION = "Acquisition"
MERGER = "Merger"
TENDER = "Tender offer"
BUYOUT = "Take-private / LBO"

PRIMARY_MARKET = "Primary"
SECONDARY_MARKET = "Secondary"

MARKET_BY_TYPE = {
    IPO: PRIMARY_MARKET,
    FOLLOW_ON: PRIMARY_MARKET,
    CONVERTIBLE: PRIMARY_MARKET,
    SECONDARY: SECONDARY_MARKET,
}
CATEGORY_BY_TYPE = {
    IPO: ECM, FOLLOW_ON: ECM, SECONDARY: ECM, CONVERTIBLE: ECM,
    ACQUISITION: MNA, MERGER: MNA, TENDER: MNA, BUYOUT: MNA,
}

# Status, in lifecycle order. A later status wins when records are merged.
STATUS_ORDER = [
    "Rumored",
    "Filed",
    "Expected",
    "Announced",
    "Pending",
    "Priced",
    "Completed",
    "Withdrawn",
    "Terminated",
]


def status_rank(status: str | None) -> int:
    try:
        return STATUS_ORDER.index(status or "")
    except ValueError:
        return -1


_SUFFIXES = re.compile(
    r"\b(inc|incorporated|corp|corporation|co|company|plc|ltd|limited|llc|lp|"
    r"group|holdings?|sa|s\.a|ag|nv|n\.v|se|spa|s\.p\.a|ab|asa|oyj|bhd|tbk|"
    r"the|class [a-c]|ordinary shares|ads|adr)\b\.?"
)


def normalize_name(name: str | None) -> str:
    """Canonical form of a company name for matching ("Acme Corp." -> "acme")."""
    if not name:
        return ""
    s = name.lower().replace("&", " and ")
    s = re.sub(r"[’'`]s\b", "", s)
    s = _SUFFIXES.sub(" ", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def names_match(a: str | None, b: str | None) -> bool:
    """Same company under a short and a long name ("Altair" ~ "Altair Engineering")?

    Exact match on the normalized form, or the shorter name's words are the
    leading words of the longer one ("nova robotics" ~ "nova robotics systems").
    """
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    ta, tb = na.split(), nb.split()
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return len(" ".join(short)) >= 4 and long_[: len(short)] == short


def name_key(name: str | None) -> str:
    """Index key under which names that may match each other share a bucket."""
    n = normalize_name(name)
    return n.split()[0] if n else ""


@dataclass
class Source:
    name: str
    url: str | None = None
    title: str | None = None
    published: str | None = None


@dataclass
class Deal:
    category: str                       # ECM | M&A
    deal_type: str                      # see vocabulary above
    date: str                           # ISO date of the latest milestone
    status: str
    issuer: str | None = None           # ECM issuer, or M&A target
    acquirer: str | None = None         # M&A only
    value: float | None = None          # in `currency`
    currency: str | None = None
    value_usd: float | None = None
    country: str | None = None
    region: str | None = None           # Americas | EMEA | APAC
    exchange: str | None = None
    sector: str | None = None
    ticker: str | None = None
    announced: str | None = None        # first time we saw the deal
    origin: str = "news"                # structured | news | manual
    confidence: float = 0.5
    sources: list[Source] = field(default_factory=list)
    id: str = ""

    @property
    def market(self) -> str | None:
        return MARKET_BY_TYPE.get(self.deal_type)

    def match_key(self) -> str:
        """Key for recognising the same deal across sources and days."""
        if self.category == MNA:
            parties = normalize_name(self.issuer)
            if not parties:
                return ""
            # The target identifies an M&A deal; competing bidders stay separate.
            return f"mna|{parties}|{normalize_name(self.acquirer)}"
        issuer = normalize_name(self.issuer)
        return f"ecm|{self.deal_type}|{issuer}" if issuer else ""

    def ensure_id(self) -> str:
        if not self.id:
            basis = self.match_key() or "|".join(
                [self.category, self.deal_type, self.sources[0].title if self.sources else "", self.date]
            )
            self.id = hashlib.sha1(basis.encode()).hexdigest()[:12]
        return self.id

    def to_dict(self) -> dict[str, Any]:
        self.ensure_id()
        d = asdict(self)
        d["market"] = self.market
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Deal":
        d = dict(d)
        d.pop("market", None)
        sources = [Source(**s) for s in d.pop("sources", [])]
        known = {f for f in cls.__dataclass_fields__}
        return cls(sources=sources, **{k: v for k, v in d.items() if k in known})
