# futures-mm: Phase 1 research recorder

Records Kalshi and Polymarket order books and trades for one championship futures
market, removes the vig from sportsbook outright odds to get a fair value, and writes a daily report:
fair value vs. market, spreads, depth, volume, how far each market drifts from the
books, and any cross-venue crossed books.

It **places no orders** and needs no trading keys. Kalshi and Polymarket market data is
public. Fair value needs a key from [The Odds API](https://the-odds-api.com).

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp config.example.toml config.toml
export ODDS_API_KEY=your_key
```

Confirm this season's identifiers (they change every year) and edit `config.toml`:

```bash
python -m futures_mm discover "nba champion"
```

## Run

```bash
python -m futures_mm -v once                 # one cycle: check matching and connectivity
python -m futures_mm record                  # leave running (tmux, systemd, a small VPS)
python -m futures_mm report --hours 24       # writes reports/nba-YYYYMMDD-HHMM.{md,csv}
```

On startup, check the log for `no team match` warnings. Add any missing names under
`[team_aliases]` in the config; teams that don't match are not recorded.

## How it works

| Module | Job |
|---|---|
| `kalshi.py` | Lists open markets in the series, gets order books (NO bids are turned into YES asks), and fetches trades incrementally |
| `polymarket.py` | Gets event markets from the Gamma API, books in batches from the CLOB API, and trades from the Data API (NO-token trades converted to YES prices) |
| `odds.py` | Fetches sportsbook outright odds |
| `devig.py` | Three methods for removing the vig (multiplicative, power, Shin), then a weighted average across bookmakers, renormalized to 100% |
| `teams.py` | Maps each venue's team names onto one name per team, and refuses ambiguous ones like "Los Angeles" |
| `recorder.py` | Scheduler: market list hourly, odds every 3h, books every 30s, trades every 60s |
| `report.py` | The daily report |

Everything goes into SQLite (`data/*.sqlite`) with these tables: `markets`, `books` (top of book plus
depth as JSON), `trades`, `odds`, and `fair` (all three methods). Phase 2's simulator will replay these.

## Odds API quota

Each odds call costs one credit per region. With the defaults (`us,eu`, every 3h) that's
about 480 credits a month, just under the free tier. Change `odds_interval_s` or
`odds_regions` to match your plan.

## Known limitations

- **Polymarket US:** this reads the international Polymarket books. If you're in the US, you'd
  trade on Polymarket US, which has separate liquidity. Treat these prices as a reference
  until a Polymarket US client is added.
- **Crossed-book section:** uses top of book only and estimated taker fees. It ignores size,
  and it doesn't check that both venues resolve the market the same way. Read the
  rules before trusting any gap it finds.
- **Fees:** `kalshi_taker_fee_rate` and `poly_taker_fee_rate` are estimates. Check
  the current fee schedules.
- **Polling:** uses polling rather than WebSockets. That's fine for slow futures markets, and
  WebSockets matter more in Phase 3.
