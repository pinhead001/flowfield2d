import hashlib
from pathlib import Path

import pytest

from rasdrive.engine.ras2025.pin import PinMismatch, load_pin, sha256_file, verify


def _h(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _setup(tmp_path: Path) -> tuple[Path, Path]:
    d = tmp_path / "build"
    (d / "sub").mkdir(parents=True)
    (d / "app.exe").write_bytes(b"x")
    (d / "sub" / "e.dll").write_bytes(b"y")
    pin = tmp_path / "pin.toml"
    pin.write_text(
        f'build = "1.2.3"\ndir = "{d.as_posix()}"\n[sha256]\n'
        f'"app.exe" = "{_h(b"x").upper()}"\n"sub/e.dll" = "{_h(b"y")}"\n',
        encoding="utf-8",
    )
    return d, pin


def test_sha256_file(tmp_path: Path) -> None:
    f = tmp_path / "a.bin"
    f.write_bytes(b"abc" * 1_000_000)
    assert sha256_file(f) == _h(b"abc" * 1_000_000)


def test_load_and_verify_ok(tmp_path: Path) -> None:
    d, pin_path = _setup(tmp_path)
    pin = load_pin(pin_path)
    assert pin.build == "1.2.3" and pin.dir == d
    assert set(pin.sha256) == {"app.exe", "sub/e.dll"}
    verify(pin)


def test_mismatch_and_missing_are_named(tmp_path: Path) -> None:
    d, pin_path = _setup(tmp_path)
    (d / "sub" / "e.dll").write_bytes(b"changed")
    (d / "app.exe").unlink()
    with pytest.raises(PinMismatch) as e:
        verify(load_pin(pin_path))
    assert "sub/e.dll" in str(e.value) and "app.exe" in str(e.value) and "1.2.3" in str(e.value)


def test_empty_pin_refuses(tmp_path: Path) -> None:
    p = tmp_path / "pin.toml"
    p.write_text(f'build = "b"\ndir = "{tmp_path.as_posix()}"\n[sha256]\n', encoding="utf-8")
    with pytest.raises(PinMismatch, match="no hashes"):
        verify(load_pin(p))


def test_ras_dir_override(tmp_path: Path) -> None:
    d, pin_path = _setup(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(PinMismatch):
        verify(load_pin(pin_path), ras_dir=other)
