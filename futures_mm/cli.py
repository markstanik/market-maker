from __future__ import annotations

import argparse
import logging
import os

from .config import Config


def main():
    ap = argparse.ArgumentParser(prog="futures_mm", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("discover", help="find the Kalshi series, Polymarket event and Odds API key for a league")
    d.add_argument("query", help='e.g. "nba champion" or "super bowl"')

    for name, help_ in (("record", "run the recorder forever"), ("once", "run one cycle of every job")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("--config", default="config.toml")

    r = sub.add_parser("report", help="write the daily report")
    r.add_argument("--config", default="config.toml")
    r.add_argument("--hours", type=float, default=24)
    r.add_argument("--method", choices=("multiplicative", "power", "shin"))
    r.add_argument("--out", default="reports")

    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.cmd == "discover":
        return discover(args.query)
    cfg = Config.load(args.config)
    if args.cmd in ("record", "once"):
        from .recorder import Recorder
        rec = Recorder(cfg)
        rec.run_forever() if args.cmd == "record" else rec.run_once()
    elif args.cmd == "report":
        from . import report
        rep = report.build(cfg.db_path, args.hours, args.method or cfg.devig_method,
                           cfg.kalshi_taker_fee_rate, cfg.poly_taker_fee_rate)
        md, csv_path = report.write(rep, cfg.league, args.out)
        print(md.read_text())
        print(f"Wrote {md} and {csv_path}")


def discover(query: str):
    from .kalshi import Kalshi
    from .polymarket import Polymarket
    from .teams import TeamMatcher

    m = TeamMatcher("nba")
    words = query.lower().split()
    print("== Kalshi series (use as kalshi_series)")
    try:
        for s in Kalshi(m).search_series(words[0]):
            print(f"  {s.get('ticker'):<24} {s.get('title')}")
    except Exception as e:
        print(f"  failed: {e}")
    print("== Polymarket events (use slug as polymarket_event_slug)")
    try:
        for e in Polymarket(m).search_events(query):
            print(f"  {e.get('slug'):<40} {e.get('title')}")
    except Exception as e:
        print(f"  failed: {e}")
    key = os.environ.get("ODDS_API_KEY")
    print("== Odds API outright sports (use key as odds_sport_key)")
    if not key:
        print("  set ODDS_API_KEY to list these")
        return
    from .odds import OddsApi
    try:
        for s in OddsApi(key, m).sports():
            if s.get("has_outrights"):
                print(f"  {s['key']:<45} {s.get('title')}")
    except Exception as e:
        print(f"  failed: {e}")
