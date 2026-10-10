# Global IB deals dashboard

A dashboard of major global investment-banking deals that refreshes itself
every day:

- **ECM, primary market:** IPOs, follow-ons, rights issues, placements, convertibles
- **ECM, secondary market:** block trades, accelerated bookbuilds, sell-downs by existing holders
- **M&A:** acquisitions, mergers, tender offers, take-privates and LBOs

A GitHub Actions job runs at 06:17 UTC each day. It pulls the latest data,
merges it into a rolling history in `data/`, commits that history, and
redeploys the static dashboard in `site/` to GitHub Pages.

```
 Nasdaq IPO calendar ─┐
 SEC EDGAR filings  ──┤                     ┌─ data/deals.json ──┐
 Google News (global)─┼─▶ ibdeals.pipeline ─┼─ data/filings.json ─┼─▶ site/ (GitHub Pages)
 Licensed CSV exports ┘   (+ Claude, opt.)  └─ data/meta.json ───┘
```

## Data sources

| Source | Covers | Gives | Key needed |
|---|---|---|---|
| Nasdaq IPO calendar (`api.nasdaq.com`) | US IPOs on Nasdaq, NYSE, NYSE American | issuer, ticker, exchange, proceeds; priced, upcoming, filed and withdrawn deals | none |
| SEC EDGAR daily form index | every US-registered deal filing | "filings pulse": daily counts of S-1/F-1, 424B4, 424B5, 424B7, merger proxies, S-4, tender offers and going-private filings, each linked to the filing | none (set a contact `SEC_USER_AGENT`) |
| Google News RSS (US, UK, India, Singapore and Australia editions) | global M&A and ECM headlines, including Hong Kong, China, India, Japan, Europe and the Middle East | deal type, parties, size, currency, country and status, extracted from each headline | none |
| Claude (optional) | the same headlines | more accurate extraction, sector, and filtering of non-deals | `ANTHROPIC_API_KEY` |
| `data/manual/*.csv` | anything you license (Dealogic, LSEG, Bloomberg, PitchBook) | authoritative rows, which override news values | — |

Sizes are converted to US$ using ECB reference rates (frankfurter.dev). If
that feed is down, approximate fallback rates are used and the dashboard
footer says so.

**Coverage limits.** The free sources are good at large, widely reported
deals and at US IPOs. They are not a league-table-grade dataset: news-derived
deals can miss undisclosed sizes, get a party wrong, or leave out smaller
non-US deals. Every news-derived row is marked "from news" and links to its
articles. For bookrunner-grade completeness, drop licensed exports into
`data/manual/` (format in [`data/manual/README.md`](data/manual/README.md)).
Those rows merge with, and take priority over, the free sources.

## Dashboard

- **Filters:** date range (7D/30D/90D/YTD/12M), category, primary vs.
  secondary market, deal type, region, status, a "major deals only" switch
  (ECM ≥ $100M, M&A ≥ $500M, both set in `config.toml`), and free-text search.
- **Headline figures:** M&A value, ECM value with the primary/secondary split,
  deal count, and the largest deal.
- **Charts:** deal value over time, stacked by ECM primary, ECM secondary and
  M&A; value by region; value by deal type. Every chart has hover tooltips and
  a "Show data" table.
- **Deal table:** sortable, paginated, with links to sources, plus CSV download
  of the current filter.
- **US filings pulse:** 30-day EDGAR filing counts by type, with sparklines and
  links to the latest filings.
- **Source status chips:** green when a source succeeded on the last run,
  amber for partial or stale, red when it failed. Hover a chip for details.
- Light and dark mode; works at phone width.

## One-time setup

1. **Merge this branch into the default branch.** GitHub only runs scheduled
   workflows from the default branch.
2. **Enable Pages:** *Settings → Pages → Build and deployment → Source:
   GitHub Actions.* Pages on a private repo needs a paid GitHub plan. Without
   Pages, the data still refreshes and commits daily, and you can open the
   dashboard locally (see below).
3. **Recommended:** *Settings → Secrets and variables → Actions → Variables*,
   add `SEC_USER_AGENT` = `Your Name your@email.com`. SEC asks automated
   clients to identify themselves.
4. **Optional:** add the secret `ANTHROPIC_API_KEY` to turn on Claude
   extraction. The model and effort are set in `config.toml` under `[enrich]`.
   At the default of 400 headlines a day, sent in batches of 40, this costs
   very little.
5. Run it the first time by hand: *Actions → Daily deal refresh → Run
   workflow.* The dashboard is published at
   `https://<owner>.github.io/<repo>/`.

## Running locally

```bash
python -m ibdeals.pipeline                 # full refresh into data/ (Python 3.11+, no deps)
python -m ibdeals.pipeline --only news,edgar
python -m http.server 8000                 # then open http://localhost:8000/site/
pip install pytest && python -m pytest -q  # offline tests against recorded source formats
```

## Configuration

Everything tunable is in [`config.toml`](config.toml): retention, the
"major" thresholds, Nasdaq month window, news queries and regional editions,
the CSV folder, and the Claude model, effort and batch size. To cover a new
market, add a query or an edition (`hl|gl|ceid`, e.g. `"en-HK|HK|HK:en"` or
`"ja|JP|JP:ja"`).

## How the data stays clean

- **De-duplication:** the same deal reported by Reuters, the FT and the
  Nasdaq calendar becomes one row with several sources. Records are matched
  on company names: target + acquirer for M&A, issuer + type for ECM. Name
  matching tolerates suffixes ("Altair" ≈ "Altair Engineering Inc.").
  Headlines with no parties are matched on text similarity instead. Competing
  bidders for one target stay separate.
- **Lifecycle:** a deal keeps its id across days. Status only moves forward
  (Rumored → Announced → Pending → Completed). The record keeps both its
  first-seen date and its latest-milestone date.
- **Priority:** CSV rows beat Nasdaq/EDGAR data, which beats news.
- **Fault isolation:** a source that fails is recorded in `meta.json` and
  shown on the dashboard; the other sources still update. The workflow goes
  red only when every source fails.
- **Size:** unsized or small news deals roll off after 30 days. Everything
  else is kept for 400 days.

## Layout

```
ibdeals/            pipeline package (stdlib only)
  sources/          nasdaq_ipo, edgar, news, manual adapters
  extract.py        rule-based headline → deal extraction
  enrich.py         optional Claude extraction (structured JSON output)
  store.py          merge / de-dup / retention / filings rollup
  pipeline.py       orchestration + CLI
site/               static dashboard (index.html, app.js, styles.css; no build step)
data/               generated history (committed by the workflow)
tests/              offline tests + recorded source fixtures
.github/workflows/  daily refresh + Pages deploy
```
