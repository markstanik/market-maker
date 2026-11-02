from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    league: str
    kalshi_series: str
    polymarket_event_slug: str
    odds_sport_key: str
    db_path: str = "data/futures.sqlite"
    book_interval_s: int = 30
    trade_interval_s: int = 60
    odds_interval_s: int = 10800
    market_refresh_s: int = 3600
    book_depth: int = 10
    odds_regions: str = "us,eu"
    devig_method: str = "shin"
    book_weights: dict[str, float] = field(default_factory=dict)
    default_book_weight: float = 1.0
    team_aliases: dict[str, str] = field(default_factory=dict)
    kalshi_taker_fee_rate: float = 0.07
    poly_taker_fee_rate: float = 0.0
    odds_api_key: str | None = None

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        raw = tomllib.loads(Path(path).read_text())
        flat = {**raw.get("league", {}), **raw.get("recorder", {}), **raw.get("fair_value", {}),
                **raw.get("fees", {})}
        flat["book_weights"] = raw.get("fair_value", {}).get("book_weights", {})
        flat["team_aliases"] = raw.get("team_aliases", {})
        cfg = cls(**{k: v for k, v in flat.items() if k in cls.__dataclass_fields__})
        cfg.odds_api_key = os.environ.get("ODDS_API_KEY") or cfg.odds_api_key
        return cfg
