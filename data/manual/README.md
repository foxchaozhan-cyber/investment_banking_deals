# Manual / licensed data drop-in

Put CSV exports from Dealogic, LSEG Workspace, Bloomberg, PitchBook or
Mergermarket here (any `*.csv`). The daily run loads every file, merges its rows
with the free sources, and de-duplicates them. Rows from these files take
priority over news-derived values.

Column names are case-insensitive. Only `date` and `deal_type` are required.

| column       | example                    | notes                                                        |
|--------------|----------------------------|--------------------------------------------------------------|
| `date`       | `2026-10-08`               | announcement / pricing date (ISO)                            |
| `deal_type`  | `IPO`                      | IPO, Follow-on, Rights issue, Secondary, Block trade, ABB, Convertible, M&A, Acquisition, Merger, Tender offer, LBO, Take-private |
| `status`     | `Priced`                   | Rumored, Filed, Expected, Announced, Pending, Priced, Completed, Withdrawn, Terminated |
| `issuer`     | `Nova Robotics`            | ECM issuer (or use `target` for M&A)                         |
| `target`     | `Altair Engineering`       | M&A target                                                   |
| `acquirer`   | `Siemens`                  | M&A buyer                                                    |
| `value`      | `10600000000`              | deal size in `currency`, full units                          |
| `currency`   | `USD`                      | ISO code; converted to US$ with ECB rates                    |
| `value_usd`  |                            | optional, overrides the conversion                           |
| `country`    | `Germany`                  | region is derived if `region` is blank                       |
| `region`     | `EMEA`                     | Americas, EMEA or APAC                                       |
| `exchange`, `ticker`, `sector` | | optional                                              |
| `source`, `url`, `title` | `LSEG`, link, headline | shown in the dashboard's Sources column              |

Check that your data licence allows republishing before you commit exports
to a repository or host the dashboard publicly.
