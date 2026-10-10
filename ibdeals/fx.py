"""Currency conversion to USD.

Live rates come from the ECB reference feed via frankfurter.dev (free, no key).
If that fails, approximate fallback rates keep the pipeline running; the run
metadata records which one was used.
"""

from __future__ import annotations

import logging

from . import http

log = logging.getLogger(__name__)

# Units of currency per 1 USD. Approximate; used only when the live feed fails.
FALLBACK_PER_USD = {
    "USD": 1.0, "EUR": 0.92, "GBP": 0.78, "JPY": 150.0, "CNY": 7.2, "HKD": 7.8,
    "INR": 85.0, "AUD": 1.52, "CAD": 1.37, "SGD": 1.34, "CHF": 0.88, "KRW": 1380.0,
    "SEK": 10.5, "NOK": 10.8, "DKK": 6.9, "BRL": 5.5, "MXN": 18.5, "ZAR": 18.0,
    "SAR": 3.75, "AED": 3.67, "TWD": 32.0, "IDR": 16000.0, "MYR": 4.5, "THB": 35.0,
    "NZD": 1.66, "PLN": 4.0, "TRY": 38.0, "ILS": 3.7, "PHP": 57.0,
}


class FX:
    def __init__(self, per_usd: dict[str, float], source: str):
        self.per_usd = per_usd
        self.source = source

    @classmethod
    def load(cls) -> "FX":
        try:
            data = http.get_json("https://api.frankfurter.dev/v1/latest?base=USD", retries=2)
            rates = {k.upper(): float(v) for k, v in data["rates"].items()}
            rates["USD"] = 1.0
            # Pegged currencies the ECB does not publish.
            rates.setdefault("SAR", 3.75)
            rates.setdefault("AED", 3.6725)
            merged = {**FALLBACK_PER_USD, **rates}
            return cls(merged, f"ECB via frankfurter.dev ({data.get('date', 'latest')})")
        except Exception as e:  # noqa: BLE001 - any failure falls back
            log.warning("FX feed unavailable (%s); using fallback rates", e)
            return cls(dict(FALLBACK_PER_USD), "fallback (approximate)")

    def to_usd(self, amount: float | None, currency: str | None) -> float | None:
        if amount is None or not currency:
            return None
        rate = self.per_usd.get(currency.upper())
        if not rate:
            return None
        return amount / rate
