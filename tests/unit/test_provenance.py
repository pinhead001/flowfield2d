import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

import rasdrive
from rasdrive.provenance import (
    REQUIRED,
    ManifestError,
    build_manifest,
    file_hashes,
    git_state,
    validate_manifest,
    write_manifest,
)


def _repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    for a in (["init", "-q"], ["config", "user.email", "t@example.com"],
              ["config", "user.name", "T"]):
        subprocess.run(["git", *a], cwd=r, check=True)
    (r / "f.txt").write_text("x")
    subprocess.run(["git", "add", "-A"], cwd=r, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "i"], cwd=r, check=True)
    return r


def _build(tmp_path: Path, **kw: object) -> dict[str, object]:
    lock = tmp_path / "uv.lock"
    lock.write_text("lock")
    dem = tmp_path / "dem.tif"
    dem.write_bytes(b"\x00\x01")
    args: dict[str, object] = dict(
        run_id="r1", repos={"lib": _repo(tmp_path)}, lockfiles=[lock],
        engine={"build": "1.0", "binary_sha256": "ab"}, inputs=[dem],
        params={"cfl": 0.8}, convergence={"converged": True},
        now=datetime(2026, 10, 24, 7, 0, tzinfo=UTC))
    args.update(kw)
    return build_manifest(**args)  # type: ignore[arg-type]


def test_git_state_tracks_dirty(tmp_path: Path) -> None:
    r = _repo(tmp_path)
    s = git_state(r)
    assert len(str(s["commit"])) == 40 and s["dirty"] is False
    (r / "f.txt").write_text("y")
    assert git_state(r)["dirty"] is True


def test_file_hashes_relative_and_sorted(tmp_path: Path) -> None:
    (tmp_path / "b").write_bytes(b"2")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a").write_bytes(b"1")
    h = file_hashes([tmp_path / "b", tmp_path / "sub" / "a"], root=tmp_path)
    assert list(h) == ["b", "sub/a"]
    assert h["sub/a"] == hashlib.sha256(b"1").hexdigest()


def test_build_validate_write(tmp_path: Path) -> None:
    m = _build(tmp_path, extra={"flow_source": "x"})
    assert set(REQUIRED) <= set(m)
    assert m["manifest_version"] == 1 and m["created"] == "2026-10-24T07:00:00Z"
    assert m["rasdrive_version"] == rasdrive.__version__
    assert m["lockfiles"] == {"uv.lock": hashlib.sha256(b"lock").hexdigest()}
    assert m["extra"] == {"flow_source": "x"}
    out = tmp_path / "manifest.json"
    write_manifest(m, out)
    assert json.loads(out.read_text())["run_id"] == "r1"


def test_engine_needs_build_and_hash(tmp_path: Path) -> None:
    with pytest.raises(ManifestError):
        _build(tmp_path, engine={"build": "1.0"})


def test_validate_names_every_problem() -> None:
    with pytest.raises(ManifestError) as e:
        validate_manifest({"manifest_version": "1", "run_id": "r", "repos": []})
    msg = str(e.value)
    for key in ("created", "inputs", "convergence", "manifest_version", "repos"):
        assert key in msg


def test_created_is_converted_to_utc(tmp_path: Path) -> None:
    from datetime import timedelta, timezone
    m = _build(tmp_path, now=datetime(2026, 10, 24, 0, 0, tzinfo=timezone(timedelta(hours=-7))))
    assert m["created"] == "2026-10-24T07:00:00Z"
