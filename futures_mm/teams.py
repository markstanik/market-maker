"""Map the team names each venue uses onto one canonical name per team.

Kalshi tends to use city names or short codes ("Oklahoma City", "Los Angeles L",
ticker suffix "OKC"), Polymarket and sportsbooks use full names. Anything that
cannot be matched is logged by the recorder so you can add an alias.
"""
from __future__ import annotations

import difflib
import re

# canonical full name -> (abbreviations / extra aliases). City and nickname are
# added automatically unless the city is shared by two teams in the league.
NBA = {
    "Atlanta Hawks": ["ATL"],
    "Boston Celtics": ["BOS"],
    "Brooklyn Nets": ["BKN", "BRK", "BRO"],
    "Charlotte Hornets": ["CHA", "CHO"],
    "Chicago Bulls": ["CHI"],
    "Cleveland Cavaliers": ["CLE", "Cavs"],
    "Dallas Mavericks": ["DAL", "Mavs"],
    "Denver Nuggets": ["DEN"],
    "Detroit Pistons": ["DET"],
    "Golden State Warriors": ["GSW", "GS", "Golden State"],
    "Houston Rockets": ["HOU"],
    "Indiana Pacers": ["IND"],
    "Los Angeles Clippers": ["LAC", "LA Clippers", "Los Angeles C"],
    "Los Angeles Lakers": ["LAL", "LA Lakers", "Los Angeles L"],
    "Memphis Grizzlies": ["MEM"],
    "Miami Heat": ["MIA"],
    "Milwaukee Bucks": ["MIL"],
    "Minnesota Timberwolves": ["MIN", "Wolves"],
    "New Orleans Pelicans": ["NOP", "NO", "NOR"],
    "New York Knicks": ["NYK", "NY"],
    "Oklahoma City Thunder": ["OKC"],
    "Orlando Magic": ["ORL"],
    "Philadelphia 76ers": ["PHI", "Sixers", "76ers"],
    "Phoenix Suns": ["PHX", "PHO"],
    "Portland Trail Blazers": ["POR", "Blazers", "Trail Blazers"],
    "Sacramento Kings": ["SAC"],
    "San Antonio Spurs": ["SAS", "SA"],
    "Toronto Raptors": ["TOR"],
    "Utah Jazz": ["UTA", "UTAH"],
    "Washington Wizards": ["WAS", "WSH"],
}

NFL = {
    "Arizona Cardinals": ["ARI"],
    "Atlanta Falcons": ["ATL"],
    "Baltimore Ravens": ["BAL"],
    "Buffalo Bills": ["BUF"],
    "Carolina Panthers": ["CAR"],
    "Chicago Bears": ["CHI"],
    "Cincinnati Bengals": ["CIN"],
    "Cleveland Browns": ["CLE"],
    "Dallas Cowboys": ["DAL"],
    "Denver Broncos": ["DEN"],
    "Detroit Lions": ["DET"],
    "Green Bay Packers": ["GB", "GNB"],
    "Houston Texans": ["HOU"],
    "Indianapolis Colts": ["IND"],
    "Jacksonville Jaguars": ["JAX", "JAC"],
    "Kansas City Chiefs": ["KC", "KAN"],
    "Las Vegas Raiders": ["LV", "LVR"],
    "Los Angeles Chargers": ["LAC", "LA Chargers", "Los Angeles C"],
    "Los Angeles Rams": ["LAR", "LA Rams", "Los Angeles R"],
    "Miami Dolphins": ["MIA"],
    "Minnesota Vikings": ["MIN"],
    "New England Patriots": ["NE", "NWE"],
    "New Orleans Saints": ["NO", "NOR"],
    "New York Giants": ["NYG", "New York G"],
    "New York Jets": ["NYJ", "New York J"],
    "Philadelphia Eagles": ["PHI"],
    "Pittsburgh Steelers": ["PIT"],
    "San Francisco 49ers": ["SF", "SFO", "49ers", "Niners"],
    "Seattle Seahawks": ["SEA"],
    "Tampa Bay Buccaneers": ["TB", "TAM", "Bucs"],
    "Tennessee Titans": ["TEN"],
    "Washington Commanders": ["WAS", "WSH"],
}

LEAGUES = {"nba": NBA, "nfl": NFL}


def norm(s: str) -> str:
    s = s.lower().replace("&", "and")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


class TeamMatcher:
    def __init__(self, league: str, extra_aliases: dict[str, str] | None = None):
        teams = LEAGUES[league.lower()]
        self.canonical = list(teams)
        cities: dict[str, list[str]] = {}
        for full in teams:
            words = full.split()
            nick_len = 2 if full.endswith("Trail Blazers") else 1
            cities.setdefault(" ".join(words[:-nick_len]), []).append(full)
        self.alias: dict[str, str] = {}
        for full, extra in teams.items():
            words = full.split()
            nick_len = 2 if full.endswith("Trail Blazers") else 1
            city, nick = " ".join(words[:-nick_len]), " ".join(words[-nick_len:])
            names = [full, nick, *extra]
            if len(cities[city]) == 1:
                names.append(city)
            for n in names:
                self.alias[norm(n)] = full
        for alias, full in (extra_aliases or {}).items():
            self.alias[norm(alias)] = full

    def match(self, *candidates: str | None) -> str | None:
        """Try each candidate string in order; return the canonical team or None."""
        for c in candidates:
            if not c:
                continue
            n = norm(c)
            if n in self.alias:
                return self.alias[n]
            # "Will the Boston Celtics win the 2027 NBA Finals?" -> look for a full name inside
            hits = {full for a, full in self.alias.items() if len(a) > 3 and f" {a} " in f" {n} "}
            if len(hits) == 1:
                return hits.pop()
        for c in candidates:
            if not c:
                continue
            close = difflib.get_close_matches(norm(c), list(self.alias), n=5, cutoff=0.88)
            teams = {self.alias[a] for a in close}
            if len(teams) == 1:  # refuse to guess when e.g. "Los Angeles" is near two teams
                return teams.pop()
        return None
