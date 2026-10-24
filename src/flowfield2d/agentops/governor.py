"""Governor: work mode from the Claude meter, and delegate capacity from the ledger.

Modes (thresholds from config, on Claude 5-hour remaining %):
  normal       remaining >= normal_min and weekly pace OK
  conserve     remaining >= conserve_min (or normal_min with weekly pace not OK)
  review-only  remaining > 0
  wait         exhausted; the lead stops, delegates keep working
Weekly pace OK: 7-day used % <= elapsed fraction of the window * 100 + slack.
A window whose `resets_at` has passed counts as reset (0% used).

Delegate quota has no headless readout, so remaining % is the last manual
calibration minus ledger tokens since then divided by `tokens_per_pct`
(unknown when that is 0).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from flowfield2d.agentops import cooldown, ledger
from flowfield2d.agentops.config import AgentOpsConfig

WEEK_S = 7 * 86400


@dataclass
class Status:
    mode: str
    reason: str
    five_hour_used: float | None
    five_hour_resets_at: int | None
    seven_day_used: float | None
    seven_day_resets_at: int | None
    weekly_pace_ok: bool | None
    agy_remaining_pct: float | None
    agy_calibrated_at: str | None
    agy_tokens_since_calibration: int
    agy_errors_recent: int
    agy_concurrency: int
    usage_updated_at: str | None
    agy_cooldowns: dict[str, str]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def _window(usage: dict[str, Any], key: str, now_s: float) -> tuple[float | None, int | None]:
    w = usage.get(key) or {}
    used, reset = _num(w.get("used_percentage")), _num(w.get("resets_at"))
    if reset is not None and reset <= now_s:
        return 0.0, None
    return used, int(reset) if reset is not None else None


def _read_usage(cfg: AgentOpsConfig) -> dict[str, Any]:
    try:
        data = json.loads(cfg.claude_usage_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _last_calibration(cfg: AgentOpsConfig) -> dict[str, Any] | None:
    recs = ledger.read(cfg.calibration_path)
    return recs[-1] if recs else None


def calibrate(cfg: AgentOpsConfig, agy_remaining_pct: float, now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    ledger.append(cfg.calibration_path,
                  {"ts": now.isoformat(), "agy_remaining_pct": float(agy_remaining_pct)})


def status(cfg: AgentOpsConfig, now: datetime | None = None) -> Status:
    now = now or datetime.now(UTC)
    now_s = now.timestamp()
    g = cfg.governor
    usage = _read_usage(cfg)
    five, five_reset = _window(usage, "five_hour", now_s)
    seven, seven_reset = _window(usage, "seven_day", now_s)

    pace_ok: bool | None = None
    if seven is not None:
        if seven_reset is None:
            pace_ok = seven <= g.weekly_pace_slack
        else:
            elapsed = min(1.0, max(0.0, 1 - (seven_reset - now_s) / WEEK_S))
            pace_ok = seven <= elapsed * 100 + g.weekly_pace_slack

    if five is None:
        mode, reason = g.unknown_mode, "no Claude meter data"
    else:
        remaining = 100 - five
        if remaining <= 0:
            mode, reason = "wait", "5-hour limit exhausted"
        elif remaining < g.conserve_min_remaining:
            mode, reason = "review-only", f"5h remaining {remaining:.0f}%"
        elif remaining < g.normal_min_remaining:
            mode, reason = "conserve", f"5h remaining {remaining:.0f}%"
        elif pace_ok is False:
            mode, reason = "conserve", "weekly pace exceeded"
        else:
            mode, reason = "normal", f"5h remaining {remaining:.0f}%"

    calls = [r for r in ledger.read(cfg.ledger_path) if r.get("kind") == "agy"]
    cal = _last_calibration(cfg)
    tokens_since = 0
    agy_remaining: float | None = None
    if cal is not None:
        tokens_since = sum(int(r.get("total_tokens") or 0)
                           for r in ledger.since(calls, datetime.fromisoformat(cal["ts"])))
        agy_remaining = float(cal["agy_remaining_pct"])
        if cfg.agy.tokens_per_pct > 0:
            agy_remaining = max(0.0, agy_remaining - tokens_since / cfg.agy.tokens_per_pct)

    recent = ledger.since(calls, now - timedelta(minutes=cfg.agy.error_window_min))
    errors = sum(1 for r in recent if not r.get("ok", False))
    conc = cfg.agy.concurrency_start >> errors if errors < 32 else 0
    conc = max(1, conc) if cfg.agy.concurrency_start > 0 else 0
    if agy_remaining is not None and agy_remaining < cfg.agy.stop_below_pct:
        conc = 0
    cooling = cooldown.active(cfg, now)
    if cooldown.choose_model(cfg, None, now) is None and (cfg.agy.models or cooling):
        conc = 0

    return Status(mode, reason, five, five_reset, seven, seven_reset, pace_ok, agy_remaining,
                  cal["ts"] if cal else None, tokens_since, errors, conc,
                  usage.get("updated_at"), {k: v.isoformat() for k, v in cooling.items()})


def _fmt_reset(epoch: int | None) -> str:
    if epoch is None:
        return "?"
    return datetime.fromtimestamp(epoch, UTC).astimezone().strftime("%a %H:%M")


def render(s: Status) -> str:
    def pct(v: float | None) -> str:
        return "unknown" if v is None else f"{v:.0f}%"

    pace = {True: "ok", False: "OVER", None: "unknown"}[s.weekly_pace_ok]
    agy = pct(s.agy_remaining_pct)
    if s.agy_calibrated_at:
        agy += f" (calibrated {s.agy_calibrated_at[:16]}, +{s.agy_tokens_since_calibration} tok)"
    return "\n".join([
        f"governor: {s.mode} ({s.reason})",
        f"claude 5h used {pct(s.five_hour_used)} resets {_fmt_reset(s.five_hour_resets_at)}; "
        f"7d used {pct(s.seven_day_used)} resets {_fmt_reset(s.seven_day_resets_at)}; "
        f"weekly pace {pace}",
        f"agy remaining {agy}; recent errors {s.agy_errors_recent}; "
        f"concurrency {s.agy_concurrency}",
        "agy cooldowns: " + (", ".join(f"{k} until {v[:16]}" for k, v in s.agy_cooldowns.items())
                             or "none"),
        f"meter updated {s.usage_updated_at or 'never'}",
    ])
