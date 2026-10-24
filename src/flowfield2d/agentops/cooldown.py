"""Delegate quota pools and their cooldowns.

Models that share a quota form a pool (`[agy] pools` in config; a model not listed is its own pool).
A quota failure puts the model's pool into cooldown until the reset time the delegate reports
("Resets in 165h59m3s"), or for `default_cooldown_min` when it reports none.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from flowfield2d.agentops.config import AgentOpsConfig
from flowfield2d.agentops.ledger import write_json_atomic

RESET_RE = re.compile(r"resets?\s+in\s+((?:\d+\s*[dhms]\s*)+)", re.IGNORECASE)
UNIT_S = {"d": 86400, "h": 3600, "m": 60, "s": 1}


def parse_reset(text: str) -> timedelta | None:
    m = RESET_RE.search(text)
    if not m:
        return None
    secs = sum(int(n) * UNIT_S[u.lower()] for n, u in re.findall(r"(\d+)\s*([dhms])", m.group(1),
                                                                    re.IGNORECASE))
    return timedelta(seconds=secs)


def pool_of(cfg: AgentOpsConfig, model: str) -> str:
    for pool, models in cfg.agy.pools.items():
        if model in models:
            return pool
    return model


def _path(cfg: AgentOpsConfig) -> Path:
    return cfg.state_dir / "agy_cooldowns.json"


def _load_all(cfg: AgentOpsConfig) -> dict[str, datetime]:
    try:
        raw = json.loads(_path(cfg).read_text(encoding="utf-8"))
        return {k: datetime.fromisoformat(v) for k, v in raw.items()}
    except (OSError, ValueError, AttributeError):
        return {}


def active(cfg: AgentOpsConfig, now: datetime | None = None) -> dict[str, datetime]:
    now = now or datetime.now(UTC)
    known = set(cfg.agy.pools) | {pool_of(cfg, m) for m in cfg.agy.models}
    return {k: v for k, v in _load_all(cfg).items() if v > now and k in known}


def set_cooldown(cfg: AgentOpsConfig, pool: str, until: datetime) -> None:
    data = _load_all(cfg)
    if pool not in data or data[pool] < until:
        data[pool] = until
    write_json_atomic(_path(cfg), {k: v.isoformat() for k, v in data.items()})


def choose_model(cfg: AgentOpsConfig, preferred: str | None,
                 now: datetime | None = None) -> str | None:
    """The card's own model if its pool is free, else None; without one, the first free model."""
    cooling = active(cfg, now)
    if preferred:
        return None if pool_of(cfg, preferred) in cooling else preferred
    for m in cfg.agy.models:
        if pool_of(cfg, m) not in cooling:
            return m
    return None


def record_quota(cfg: AgentOpsConfig, model: str, text: str,
                 now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    delta = parse_reset(text) or timedelta(minutes=cfg.agy.default_cooldown_min)
    until = now + delta
    set_cooldown(cfg, pool_of(cfg, model), until)
    return until
