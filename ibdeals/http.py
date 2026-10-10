"""Small stdlib HTTP helper with retries (no third-party dependencies)."""

from __future__ import annotations

import gzip
import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger(__name__)

BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class NotFound(Exception):
    """HTTP 404: the resource does not exist (e.g. no EDGAR index on a holiday)."""


def get(url: str, headers: dict[str, str] | None = None, timeout: float = 30,
        retries: int = 3, backoff: float = 2.0) -> bytes:
    hdrs = {"User-Agent": BROWSER_UA, "Accept-Encoding": "gzip"}
    hdrs.update(headers or {})
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                return body
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise NotFound(url) from e
            last = e
            # 4xx other than throttling will not get better with retries.
            if e.code < 500 and e.code not in (403, 408, 429):
                break
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = e
        if attempt < retries:
            wait = backoff * (2 ** attempt)
            log.debug("retrying %s in %.0fs after %s", url, wait, last)
            time.sleep(wait)
    raise RuntimeError(f"GET {url} failed: {last}")


def get_json(url: str, headers: dict[str, str] | None = None, **kw: Any) -> Any:
    return json.loads(get(url, headers=headers, **kw))
