import io
import json
from datetime import UTC, datetime

from rasdrive.agentops import governor, ledger, statusline
from rasdrive.agentops.config import AgentOpsConfig

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
T = int(NOW.timestamp())


def test_config_resolves_relative_paths(cfg: AgentOpsConfig) -> None:
    assert cfg.state_dir.is_absolute() and cfg.state_dir.name == "state"
    assert cfg.repos["lib"].is_absolute()
    assert cfg.agy.model == "m1"


def test_statusline_writes_usage(cfg: AgentOpsConfig) -> None:
    payload = {"rate_limits": {"five_hour": {"used_percentage": 23.5, "resets_at": T + 3600},
                               "seven_day": {"used_percentage": 41.2}}}
    out = io.StringIO()
    statusline.run(cfg, io.StringIO(json.dumps(payload)), out, now=NOW)
    data = json.loads(cfg.claude_usage_path.read_text())
    assert data["five_hour"] == {"used_percentage": 23.5, "resets_at": T + 3600}
    assert data["seven_day"] == {"used_percentage": 41.2, "resets_at": "unknown"}
    assert "5h 24%" in out.getvalue()


def test_statusline_survives_garbage(cfg: AgentOpsConfig) -> None:
    out = io.StringIO()
    statusline.run(cfg, io.StringIO("not json"), out, now=NOW)
    data = json.loads(cfg.claude_usage_path.read_text())
    assert data["five_hour"]["used_percentage"] == "unknown"


def _usage(cfg: AgentOpsConfig, five: float | str, seven: float | str,
           seven_reset: int | str = T + 3 * 86400) -> None:
    cfg.claude_usage_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.claude_usage_path.write_text(json.dumps({
        "five_hour": {"used_percentage": five, "resets_at": T + 3600},
        "seven_day": {"used_percentage": seven, "resets_at": seven_reset}}))


def test_mode_thresholds(cfg: AgentOpsConfig) -> None:
    # 3 days left of 7 -> elapsed 4/7 = 57%; pace limit 67%
    for five, mode in [(10, "normal"), (40.1, "conserve"), (74, "conserve"),
                       (80, "review-only"), (100, "wait")]:
        _usage(cfg, five, 30)
        assert governor.status(cfg, now=NOW).mode == mode, five


def test_weekly_pace_demotes_normal(cfg: AgentOpsConfig) -> None:
    _usage(cfg, 10, 70)
    s = governor.status(cfg, now=NOW)
    assert s.mode == "conserve" and not s.weekly_pace_ok


def test_unknown_usage_uses_unknown_mode(cfg: AgentOpsConfig) -> None:
    assert governor.status(cfg, now=NOW).mode == "conserve"
    _usage(cfg, "unknown", "unknown")
    assert governor.status(cfg, now=NOW).mode == "conserve"


def test_expired_window_counts_as_reset(cfg: AgentOpsConfig) -> None:
    cfg.claude_usage_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.claude_usage_path.write_text(json.dumps({
        "five_hour": {"used_percentage": 100, "resets_at": T - 10},
        "seven_day": {"used_percentage": 30, "resets_at": T + 3 * 86400}}))
    assert governor.status(cfg, now=NOW).mode == "normal"


def test_agy_concurrency_halves_on_errors_and_stops_low(cfg: AgentOpsConfig) -> None:
    _usage(cfg, 10, 30)
    assert governor.status(cfg, now=NOW).agy_concurrency == 2
    ledger.append(cfg.ledger_path, {"ts": NOW.isoformat(), "kind": "agy", "ok": False,
                                    "total_tokens": 5})
    assert governor.status(cfg, now=NOW).agy_concurrency == 1
    governor.calibrate(cfg, agy_remaining_pct=5, now=NOW)
    s = governor.status(cfg, now=NOW)
    assert s.agy_concurrency == 0 and s.agy_remaining_pct == 5


def test_agy_estimate_uses_tokens_since_calibration(cfg: AgentOpsConfig) -> None:
    governor.calibrate(cfg, agy_remaining_pct=50, now=NOW)
    later = NOW.replace(hour=13)
    ledger.append(cfg.ledger_path, {"ts": later.isoformat(), "kind": "agy", "ok": True,
                                    "total_tokens": 3000})
    cfg.agy.tokens_per_pct = 100
    assert governor.status(cfg, now=later).agy_remaining_pct == 20
