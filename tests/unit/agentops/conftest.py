import json
import subprocess
import sys
from pathlib import Path

import pytest

from flowfield2d.agentops.config import AgentOpsConfig, load_config
from flowfield2d.agentops.queue import Card, Queue

FAKE_AGY = Path(__file__).resolve().parents[2] / "fixtures" / "fake_agy.py"
ACCEPT = (
    'python -c "import pathlib,sys; '
    "sys.exit(0 if pathlib.Path('hello.txt').read_text()=='hi' else 1)\""
)

CONFIG = """
[paths]
state_dir = "state"
worktree_root = "wt"
worktree_prefix = "wt-"

[repos]
lib = "repos/lib"

[governor]
normal_min_remaining = 60
conserve_min_remaining = 25
weekly_pace_slack = 10
unknown_mode = "conserve"

[agy]
exe = "agy"
models = ["m1", "m2"]
pools = { a = ["m1"], b = ["m2"] }
default_cooldown_min = 60
print_timeout = "1m"
extra_args = []
max_retries = 1
concurrency_start = 2
error_window_min = 60
stop_below_pct = 10
tokens_per_pct = 0

[hooks]
deny_bash = ['\\bgit\\s+push\\b', '\\bnetsh\\b']
deny_substrings = ["_secret"]
teammate_tools = ["TeamCreate"]
task_acceptance = "python -c \\"import sys; sys.exit(0)\\""
"""


@pytest.fixture
def cfg(tmp_path: Path) -> AgentOpsConfig:
    p = tmp_path / "agents.toml"
    p.write_text(CONFIG, encoding="utf-8")
    return load_config(p)


def git(cwd: Path, *a: str) -> str:
    return subprocess.run(
        ["git", *a], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo_cfg(
    cfg: AgentOpsConfig, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> AgentOpsConfig:
    """`cfg` plus a real git checkout for repo `lib` and the fake delegate as `agy`."""
    repo = cfg.repos["lib"]
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "T")
    (repo / "README").write_text("x")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")
    cfg.agy.command = [sys.executable, str(FAKE_AGY)]
    monkeypatch.setenv("FAKE_AGY_LOG", str(tmp_path / "agy_calls.jsonl"))
    monkeypatch.delenv("FAKE_AGY_MODE", raising=False)
    return cfg


def make_card(cfg: AgentOpsConfig, prompt: str = "WRITE hello.txt=hi", **kw: object) -> Card:
    """Write a card TOML into the state dir and queue it."""
    fields = {
        "id": "c1",
        "repo": "lib",
        "title": "hello",
        "prompt": prompt,
        "acceptance": ACCEPT,
        **kw,
    }
    body = "\n".join(f"{k} = {json.dumps(v)}" for k, v in fields.items())
    p = cfg.state_dir / "incoming.toml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return Queue(cfg).add(p)
