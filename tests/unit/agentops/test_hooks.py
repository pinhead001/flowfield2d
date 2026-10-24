import io
import json
from datetime import UTC, datetime

from flowfield2d.agentops import hooks
from flowfield2d.agentops.config import AgentOpsConfig

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)


def _pre(cfg: AgentOpsConfig, tool: str, tool_input: dict[str, object]) -> str | None:
    out = io.StringIO()
    stdin = io.StringIO(json.dumps({"hook_event_name": "PreToolUse", "tool_name": tool,
                                    "tool_input": tool_input}))
    hooks.pre_tool_use(cfg, stdin, out, now=NOW)
    if not out.getvalue():
        return None
    d = json.loads(out.getvalue())["hookSpecificOutput"]
    assert d["hookEventName"] == "PreToolUse"
    return str(d["permissionDecision"])


def test_denies_push_and_firewall(cfg: AgentOpsConfig) -> None:
    assert _pre(cfg, "Bash", {"command": "git push origin main"}) == "deny"
    assert _pre(cfg, "Bash", {"command": "netsh advfirewall set allprofiles state off"}) == "deny"
    assert _pre(cfg, "Bash", {"command": "git status"}) is None


def test_denies_restricted_in_any_tool(cfg: AgentOpsConfig) -> None:
    assert _pre(cfg, "Read", {"file_path": "D:/x/_secret/a.csv"}) == "deny"
    assert _pre(cfg, "Grep", {"pattern": "a", "path": "D:/x/_SECRET"}) == "deny"


def test_teammate_spawn_only_in_normal(cfg: AgentOpsConfig) -> None:
    # no usage data -> unknown_mode (conserve) -> denied
    assert _pre(cfg, "TeamCreate", {"name": "t"}) == "deny"
    cfg.claude_usage_path.parent.mkdir(parents=True, exist_ok=True)
    t = int(NOW.timestamp())
    cfg.claude_usage_path.write_text(json.dumps({
        "five_hour": {"used_percentage": 5, "resets_at": t + 3600},
        "seven_day": {"used_percentage": 5, "resets_at": t + 6 * 86400}}))
    assert _pre(cfg, "TeamCreate", {"name": "t"}) is None


def test_malformed_input_fails_open_without_crash(cfg: AgentOpsConfig) -> None:
    out = io.StringIO()
    hooks.pre_tool_use(cfg, io.StringIO("{"), out, now=NOW)
    assert out.getvalue() == ""


def test_session_start_emits_context(cfg: AgentOpsConfig) -> None:
    out = io.StringIO()
    hooks.session_start(cfg, io.StringIO("{}"), out, now=NOW)
    d = json.loads(out.getvalue())["hookSpecificOutput"]
    assert d["hookEventName"] == "SessionStart" and "governor" in d["additionalContext"]


def test_task_completed_runs_acceptance(cfg: AgentOpsConfig, tmp_path) -> None:  # type: ignore[no-untyped-def]
    err = io.StringIO()
    assert hooks.task_completed(cfg, io.StringIO(json.dumps({"cwd": str(tmp_path)})), err) == 0
    cfg.hooks.task_acceptance = 'python -c "import sys; print(\'boom\'); sys.exit(3)"'
    assert hooks.task_completed(cfg, io.StringIO(json.dumps({"cwd": str(tmp_path)})), err) == 2
    assert "boom" in err.getvalue()
