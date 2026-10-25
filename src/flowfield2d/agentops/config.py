"""Agent-ops configuration, read from the consuming project's TOML file.

Relative paths resolve against the config file's directory. Nothing here has a
project default: every path and threshold comes from the file.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ENV_VAR = "AGENTOPS_CONFIG"


@dataclass
class GovernorConfig:
    normal_min_remaining: float
    conserve_min_remaining: float
    weekly_pace_slack: float
    unknown_mode: str
    profile: str = ""                                    # active set in [governor.profiles], if any
    profiles: list[str] = field(default_factory=list)


@dataclass
class AgyConfig:
    command: list[str]
    models: list[str]
    pools: dict[str, list[str]]
    default_cooldown_min: float
    print_timeout: str
    extra_args: list[str]
    pre_acceptance: list[str]
    max_retries: int
    concurrency_start: int
    error_window_min: float
    stop_below_pct: float
    tokens_per_pct: float

    @property
    def model(self) -> str:
        """Default model: first in preference order ("" = the delegate's own default)."""
        return self.models[0] if self.models else ""


@dataclass
class HooksConfig:
    deny_bash: list[str]
    deny_substrings: list[str]
    teammate_tools: list[str]
    task_acceptance: str


@dataclass
class AgentOpsConfig:
    source: Path
    state_dir: Path
    worktree_root: Path
    worktree_prefix: str
    repos: dict[str, Path]
    governor: GovernorConfig
    agy: AgyConfig
    hooks: HooksConfig
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def claude_usage_path(self) -> Path:
        return self.state_dir / "claude_usage.json"

    @property
    def ledger_path(self) -> Path:
        return self.state_dir / "ledger.jsonl"

    @property
    def calibration_path(self) -> Path:
        return self.state_dir / "agy_calibration.jsonl"

    @property
    def queue_dir(self) -> Path:
        return self.state_dir / "queue"

    @property
    def results_dir(self) -> Path:
        return self.state_dir / "results"

    @property
    def quota_events_dir(self) -> Path:
        return self.state_dir / "quota_events"


def _path(base: Path, value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else (base / p).resolve()


def _governor(g: dict[str, Any]) -> GovernorConfig:
    """Thresholds from [governor], or from the set named by `profile` in [governor.profiles]."""
    profiles: dict[str, Any] = g.get("profiles", {})
    name = str(g.get("profile", ""))
    t = g
    if profiles:
        if name not in profiles:
            raise KeyError(f"governor profile {name!r} not in [governor.profiles] "
                           f"({', '.join(profiles)})")
        t = profiles[name]
    return GovernorConfig(
        normal_min_remaining=float(t["normal_min_remaining"]),
        conserve_min_remaining=float(t["conserve_min_remaining"]),
        weekly_pace_slack=float(t["weekly_pace_slack"]),
        unknown_mode=str(t["unknown_mode"]),
        profile=name if profiles else "",
        profiles=list(profiles),
    )


_PROFILE_LINE = re.compile(r'^(profile\s*=\s*")[^"]*(")', re.MULTILINE)


def set_governor_profile(path: Path | str, name: str) -> None:
    """Select a governor profile by rewriting the `profile = "..."` line (comments kept)."""
    src = Path(path)
    text = src.read_text(encoding="utf-8")
    profiles = tomllib.loads(text).get("governor", {}).get("profiles", {})
    if not profiles:
        raise ValueError(f"{src}: no [governor.profiles] defined")
    if name not in profiles:
        raise KeyError(f"unknown governor profile {name!r} ({', '.join(profiles)})")
    new, n = _PROFILE_LINE.subn(lambda m: f"{m.group(1)}{name}{m.group(2)}", text, count=1)
    if n != 1:
        raise ValueError(f"{src}: no profile = \"...\" line under [governor]")
    src.write_text(new, encoding="utf-8")


def load_config(path: Path | str | None = None) -> AgentOpsConfig:
    if path is None:
        env = os.environ.get(ENV_VAR)
        if not env:
            raise FileNotFoundError(f"no config given and {ENV_VAR} is not set")
        path = env
    src = Path(path).resolve()
    raw = tomllib.loads(src.read_text(encoding="utf-8"))
    base = src.parent
    p, g, a, h = raw["paths"], raw["governor"], raw["agy"], raw["hooks"]
    exe = a["exe"]
    return AgentOpsConfig(
        source=src,
        state_dir=_path(base, p["state_dir"]),
        worktree_root=_path(base, p["worktree_root"]),
        worktree_prefix=p.get("worktree_prefix", ""),
        repos={k: _path(base, v) for k, v in raw.get("repos", {}).items()},
        governor=_governor(g),
        agy=AgyConfig(
            command=list(exe) if isinstance(exe, list) else [str(exe)],
            models=([str(m) for m in a.get("models", [])]
                    or ([str(a["model"])] if a.get("model") else [])),
            pools={str(k): [str(m) for m in v] for k, v in a.get("pools", {}).items()},
            default_cooldown_min=float(a.get("default_cooldown_min", 60)),
            print_timeout=str(a["print_timeout"]),
            extra_args=[str(x) for x in a.get("extra_args", [])],
            pre_acceptance=[str(x) for x in a.get("pre_acceptance", [])],
            max_retries=int(a["max_retries"]),
            concurrency_start=int(a["concurrency_start"]),
            error_window_min=float(a["error_window_min"]),
            stop_below_pct=float(a["stop_below_pct"]),
            tokens_per_pct=float(a.get("tokens_per_pct", 0)),
        ),
        hooks=HooksConfig(
            deny_bash=[str(x) for x in h.get("deny_bash", [])],
            deny_substrings=[str(x) for x in h.get("deny_substrings", [])],
            teammate_tools=[str(x) for x in h.get("teammate_tools", [])],
            task_acceptance=str(h.get("task_acceptance", "")),
        ),
        extra={k: v for k, v in raw.items()
               if k not in {"paths", "repos", "governor", "agy", "hooks"}},
    )
