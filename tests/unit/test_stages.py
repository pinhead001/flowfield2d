"""Tests for flowfield2d.stages: content-keyed stage stamps."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from flowfield2d.stages import is_fresh, mark_done, stage_key


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_stage_key_is_hex_sha256_and_order_independent() -> None:
    a = stage_key({"x": 1, "y": {"p": 2.5, "q": "s"}})
    b = stage_key({"y": {"q": "s", "p": 2.5}, "x": 1})
    assert a == b
    assert len(a) == 64
    int(a, 16)


def test_stage_key_changes_with_param() -> None:
    assert stage_key({"x": 1}) != stage_key({"x": 2})
    assert stage_key({"y": {"p": 1}}) != stage_key({"y": {"p": 2}})


def test_stage_key_changes_with_one_file_byte(tmp_path: Path) -> None:
    f = tmp_path / "in.bin"
    f.write_bytes(b"abcdef")
    k1 = stage_key({"x": 1}, files=(f,))
    assert stage_key({"x": 1}, files=(f,)) == k1
    f.write_bytes(b"abcdeg")
    assert stage_key({"x": 1}, files=(f,)) != k1


def test_is_fresh_false_without_stamp(tmp_path: Path) -> None:
    assert is_fresh(tmp_path, stage_key({"x": 1})) is False


def test_mark_done_writes_stamp_and_is_fresh(tmp_path: Path) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    out = sub / "out.txt"
    out.write_bytes(b"hello")
    key = stage_key({"x": 1})
    mark_done(tmp_path, key, [out])
    stamp = json.loads((tmp_path / ".stage.json").read_text())
    assert stamp == {"key": key, "outputs": {"sub/out.txt": _sha(b"hello")}}
    assert is_fresh(tmp_path, key) is True
    assert is_fresh(tmp_path, stage_key({"x": 2})) is False


def test_is_fresh_false_when_output_deleted(tmp_path: Path) -> None:
    out = tmp_path / "out.txt"
    out.write_bytes(b"hello")
    key = stage_key({"x": 1})
    mark_done(tmp_path, key, [out])
    out.unlink()
    assert is_fresh(tmp_path, key) is False


def test_is_fresh_false_when_output_modified(tmp_path: Path) -> None:
    out = tmp_path / "out.txt"
    out.write_bytes(b"hello")
    key = stage_key({"x": 1})
    mark_done(tmp_path, key, [out])
    out.write_bytes(b"hellO")
    assert is_fresh(tmp_path, key) is False


def test_mark_done_rejects_output_outside_stage_dir(tmp_path: Path) -> None:
    stage = tmp_path / "stage"
    stage.mkdir()
    outside = tmp_path / "other.txt"
    outside.write_bytes(b"x")
    with pytest.raises(ValueError):
        mark_done(stage, stage_key({"x": 1}), [outside])
