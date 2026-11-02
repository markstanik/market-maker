"""Sportsbook outright odds via The Odds API (https://the-odds-api.com).

Each call costs (#markets x #regions) credits from your monthly quota, so the
recorder polls odds far less often than order books.
"""
from __future__ import annotations

from .http import Http
from .teams import TeamMatcher

BASE = "https://api.the-odds-api.com/v4"


def parse_outrights(events: list[dict], matcher: TeamMatcher) -> tuple[dict[str, dict[str, float]], list[str]]:
    """-> ({bookmaker: {team: decimal_odds}}, unmatched_names)."""
    books: dict[str, dict[str, float]] = {}
    unmatched: list[str] = []
    for ev in events:
        for bm in ev.get("bookmakers", []):
            for mk in bm.get("markets", []):
                if mk.get("key") != "outrights":
                    continue
                for o in mk.get("outcomes", []):
                    team = matcher.match(o["name"])
                    if team is None:
                        unmatched.append(o["name"])
                        continue
                    books.setdefault(bm["key"], {})[team] = float(o["price"])
    return books, sorted(set(unmatched))


class OddsApi:
    def __init__(self, api_key: str, matcher: TeamMatcher):
        self.http = Http(BASE, min_gap_s=1.0)
        self.key = api_key
        self.matcher = matcher
        self.remaining: str | None = None

    def outrights(self, sport_key: str, regions: str):
        r = self.http.get_raw(f"/sports/{sport_key}/odds", apiKey=self.key, regions=regions,
                              markets="outrights", oddsFormat="decimal")
        self.remaining = r.headers.get("x-requests-remaining")
        return parse_outrights(r.json(), self.matcher)

    def sports(self) -> list[dict]:
        return self.http.get("/sports", apiKey=self.key, all="true")
