"""Daily research report: fair value vs. market, spreads, volume and where gaps open up."""
from __future__ import annotations

import bisect
import csv
import statistics
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .store import Store

VENUES = ("kalshi", "polymarket")


def taker_fee(rate: float, p: float) -> float:
    """Per-contract fee of the Kalshi form rate * P * (1 - P). Ignores Kalshi's round-up to the cent."""
    return rate * p * (1 - p)


def _c(x: float | None, signed: bool = False) -> str:
    if x is None:
        return "–"
    return f"{x * 100:+.1f}" if signed else f"{x * 100:.1f}"


def build(db_path: str, hours: float = 24, method: str = "shin",
          kalshi_fee: float = 0.07, poly_fee: float = 0.0, wide: float = 0.03) -> dict:
    db = Store(db_path).db
    since = time.time() - hours * 3600

    # fair value history (for gap-over-time) and latest value per team
    fair_hist: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for ts, team, p in db.execute(
            "SELECT ts, team, prob FROM fair WHERE method=? ORDER BY ts", (method,)):
        fair_hist[team].append((ts, p))
    latest_fair = {t: h[-1][1] for t, h in fair_hist.items()}

    def fair_at(team: str, ts: float) -> float | None:
        h = fair_hist.get(team)
        if not h:
            return None
        i = bisect.bisect_right([x[0] for x in h], ts) - 1
        return h[i][1] if i >= 0 else None

    # per team / venue stats from book snapshots in the window
    snaps = db.execute(
        "SELECT ts, venue, team, best_bid, best_ask, bid_size, ask_size, mid FROM books "
        "WHERE ts >= ? AND team IS NOT NULL ORDER BY ts", (since,)).fetchall()
    stats: dict[tuple[str, str], dict] = defaultdict(lambda: {"spreads": [], "gaps": [], "sizes": []})
    latest: dict[tuple[str, str], tuple] = {}
    by_cycle: dict[tuple[float, str], dict[str, tuple]] = defaultdict(dict)
    for ts, venue, team, bid, ask, bsz, asz, mid in snaps:
        s = stats[(team, venue)]
        if bid is not None and ask is not None:
            s["spreads"].append(ask - bid)
            s["sizes"].append(((bsz or 0) + (asz or 0)) / 2)
            f = fair_at(team, ts)
            if f is not None and mid is not None:
                s["gaps"].append(mid - f)
        latest[(team, venue)] = (bid, ask, mid)
        by_cycle[(ts, team)][venue] = (bid, ask)

    vol: dict[tuple[str, str], tuple[float, float, int]] = {}
    for team, venue, contracts, notional, n in db.execute(
            "SELECT team, venue, SUM(size), SUM(size*price), COUNT(*) FROM trades "
            "WHERE ts >= ? AND team IS NOT NULL GROUP BY team, venue", (since,)):
        vol[(team, venue)] = (contracts or 0, notional or 0, n)

    teams = sorted({t for t, _ in latest} | set(latest_fair),
                   key=lambda t: -(latest_fair.get(t) or 0))
    rows = []
    for t in teams:
        r = {"team": t, "fair": latest_fair.get(t)}
        for v in VENUES:
            bid, ask, mid = latest.get((t, v), (None, None, None))
            s = stats.get((t, v), {"spreads": [], "gaps": [], "sizes": []})
            contracts, notional, n = vol.get((t, v), (0, 0, 0))
            r.update({
                f"{v}_bid": bid, f"{v}_ask": ask, f"{v}_mid": mid,
                f"{v}_edge": (mid - r["fair"]) if mid is not None and r["fair"] is not None else None,
                f"{v}_avg_spread": statistics.fmean(s["spreads"]) if s["spreads"] else None,
                f"{v}_pct_wide": (sum(x >= wide for x in s["spreads"]) / len(s["spreads"]))
                if s["spreads"] else None,
                f"{v}_avg_top_size": statistics.fmean(s["sizes"]) if s["sizes"] else None,
                f"{v}_mean_abs_gap": statistics.fmean(abs(g) for g in s["gaps"]) if s["gaps"] else None,
                f"{v}_volume_contracts": contracts, f"{v}_volume_usd": notional, f"{v}_trades": n,
            })
        rows.append(r)

    # cross-venue crossed books: buy YES on one venue at its ask, sell YES on the other at its bid
    crosses = []
    for (ts, team), vb in by_cycle.items():
        if len(vb) < 2:
            continue
        (kb, ka), (pb, pa) = vb["kalshi"], vb["polymarket"]
        for buy_v, ask, sell_v, bid in (("polymarket", pa, "kalshi", kb), ("kalshi", ka, "polymarket", pb)):
            if ask is None or bid is None or bid <= ask:
                continue
            fee_buy = taker_fee(kalshi_fee if buy_v == "kalshi" else poly_fee, ask)
            fee_sell = taker_fee(kalshi_fee if sell_v == "kalshi" else poly_fee, bid)
            crosses.append({"ts": ts, "team": team, "buy": buy_v, "ask": ask, "sell": sell_v,
                            "bid": bid, "gross": bid - ask, "net": bid - ask - fee_buy - fee_sell})
    crosses.sort(key=lambda c: -c["net"])

    # whole-market consistency per venue (latest snapshot): YES prices should sum to ~1
    totals = {}
    for v in VENUES:
        vals = [latest[(t, v)] for t in teams if (t, v) in latest]
        asks = [a for _, a, _ in vals if a is not None]
        bids = [b for b, _, _ in vals if b is not None]
        mids = [m for _, _, m in vals if m is not None]
        totals[v] = {"teams": len(vals), "sum_bids": sum(bids), "sum_asks": sum(asks),
                     "sum_mids": sum(mids), "complete": len(asks) == len(vals) == len(teams)}

    return {"generated": time.time(), "hours": hours, "method": method, "rows": rows,
            "crosses": crosses, "totals": totals, "n_snapshots": len(snaps),
            "fair_updated": max((h[-1][0] for h in fair_hist.values()), default=None)}


def to_markdown(rep: dict, league: str) -> str:
    fmt_ts = lambda ts: datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if ts else "never"
    out = [f"# {league.upper()} futures report — last {rep['hours']:g}h",
           f"Generated {fmt_ts(rep['generated'])} · fair value method: **{rep['method']}** · "
           f"fair value last updated {fmt_ts(rep['fair_updated'])} · {rep['n_snapshots']} book snapshots",
           "", "All prices in cents. Edge = market mid − fair (positive = market richer than books).", "",
           "## Fair value vs. market",
           "| Team | Fair | K bid/ask | K edge | P bid/ask | P edge |",
           "|---|---:|---:|---:|---:|---:|"]
    for r in rep["rows"]:
        out.append(f"| {r['team']} | {_c(r['fair'])} | {_c(r['kalshi_bid'])}/{_c(r['kalshi_ask'])} | "
                   f"{_c(r['kalshi_edge'], True)} | {_c(r['polymarket_bid'])}/{_c(r['polymarket_ask'])} | "
                   f"{_c(r['polymarket_edge'], True)} |")
    out += ["", "## Spreads, depth and volume (window)",
            "| Team | K avg spread | K % wide | K top size | K vol $ | K trades | P avg spread | P % wide | P top size | P vol $ | P trades |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    pct = lambda x: "–" if x is None else f"{x:.0%}"
    num = lambda x: "–" if x is None else f"{x:,.0f}"
    for r in sorted(rep["rows"], key=lambda r: -(r["kalshi_volume_usd"] + r["polymarket_volume_usd"])):
        out.append(f"| {r['team']} | {_c(r['kalshi_avg_spread'])} | {pct(r['kalshi_pct_wide'])} | "
                   f"{num(r['kalshi_avg_top_size'])} | {num(r['kalshi_volume_usd'])} | {r['kalshi_trades']} | "
                   f"{_c(r['polymarket_avg_spread'])} | {pct(r['polymarket_pct_wide'])} | "
                   f"{num(r['polymarket_avg_top_size'])} | {num(r['polymarket_volume_usd'])} | {r['polymarket_trades']} |")
    out += ["", "## Mean |mid − fair| over the window (how far markets drift from the books)",
            "| Team | Kalshi | Polymarket |", "|---|---:|---:|"]
    for r in rep["rows"]:
        if r["kalshi_mean_abs_gap"] is not None or r["polymarket_mean_abs_gap"] is not None:
            out.append(f"| {r['team']} | {_c(r['kalshi_mean_abs_gap'])} | {_c(r['polymarket_mean_abs_gap'])} |")
    out += ["", "## Whole-market sums (latest snapshot)",
            "Sum of asks < 100 or sum of bids > 100 on a venue that lists every team would be an "
            "intra-venue arb. Partial listings make these sums meaningless.", "",
            "| Venue | Teams | Σ bids | Σ mids | Σ asks | Complete? |", "|---|---:|---:|---:|---:|---|"]
    for v, t in rep["totals"].items():
        out.append(f"| {v} | {t['teams']} | {_c(t['sum_bids'])} | {_c(t['sum_mids'])} | "
                   f"{_c(t['sum_asks'])} | {'yes' if t['complete'] else 'no'} |")
    cr = rep["crosses"]
    out += ["", f"## Cross-venue crossed books ({len(cr)} snapshot-pairs)",
            "Top-of-book only, est. taker fees, ignores size, Polymarket US vs. international liquidity, "
            "and differences in resolution rules. Treat as leads to investigate, not trades."]
    if cr:
        out += ["", "| Time | Team | Buy YES @ | Sell YES @ | Gross | Net est. |", "|---|---|---|---|---:|---:|"]
        for c in cr[:20]:
            out.append(f"| {fmt_ts(c['ts'])} | {c['team']} | {c['buy']} {_c(c['ask'])} | "
                       f"{c['sell']} {_c(c['bid'])} | {_c(c['gross'])} | {_c(c['net'], True)} |")
    return "\n".join(out) + "\n"


def write(rep: dict, league: str, out_dir: str) -> tuple[Path, Path]:
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromtimestamp(rep["generated"], timezone.utc).strftime("%Y%m%d-%H%M")
    md = d / f"{league}-{stamp}.md"
    md.write_text(to_markdown(rep, league))
    csv_path = d / f"{league}-{stamp}.csv"
    if rep["rows"]:
        with csv_path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rep["rows"][0]))
            w.writeheader()
            w.writerows(rep["rows"])
    return md, csv_path
