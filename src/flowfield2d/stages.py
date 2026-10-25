"""Content-keyed stamps so pipeline stages can be skipped when inputs are unchanged."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

__all__ = ["is_fresh", "mark_done", "stage_key"]


def _hash_file(path: Path) -> str:
    """Compute sha256 hex digest of a file in chunks."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _relative_to_stage(stage_dir: Path, path: Path) -> Path:
    """Return path relative to stage_dir, ensuring path is inside stage_dir.

    Relative paths resolve against the working directory, like any other path argument.
    """
    try:
        rel = Path(path).resolve().relative_to(Path(stage_dir).resolve())
    except ValueError as err:
        raise ValueError(f"Output {path} is not inside stage_dir {stage_dir}") from err
    if rel == Path("."):
        raise ValueError(f"Output {path} is not inside stage_dir {stage_dir}")
    return rel


def stage_key(params: Mapping[str, Any], files: Iterable[Path] = ()) -> str:
    """Compute a sha256 hex stamp from parameters and optional file inputs.

    Parameters
    ----------
    params:
        Mapping of parameter names to values. Serialized to canonical JSON
        (sorted keys, compact separators, string default).
    files:
        Optional iterable of file paths whose sha256 digests are included in order.

    Returns
    -------
    str
        64-character sha256 hex string.
    """
    h = hashlib.sha256()
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"), default=str)
    h.update(canonical.encode("utf-8"))
    for f in files:
        h.update(_hash_file(Path(f)).encode("utf-8"))
    return h.hexdigest()


def mark_done(stage_dir: Path, key: str, outputs: Iterable[Path]) -> None:
    """Write stage completion stamp to ``stage_dir / '.stage.json'``.

    Parameters
    ----------
    stage_dir:
        Directory for the stage outputs.
    key:
        Stage key string (from :func:`stage_key`).
    outputs:
        Iterable of output file paths. All outputs must reside inside *stage_dir*.

    Raises
    ------
    ValueError
        If any output path is not inside *stage_dir*.
    """
    stage_dir = Path(stage_dir)
    stage_dir.mkdir(parents=True, exist_ok=True)
    outputs_map: dict[str, str] = {}
    for out in outputs:
        out_path = Path(out)
        rel = _relative_to_stage(stage_dir, out_path)
        actual_path = stage_dir / rel
        outputs_map[rel.as_posix()] = _hash_file(actual_path)

    stamp_path = stage_dir / ".stage.json"
    stamp_data = {
        "key": key,
        "outputs": outputs_map,
    }
    stamp_path.write_text(json.dumps(stamp_data, indent=2), encoding="utf-8")


def is_fresh(stage_dir: Path, key: str) -> bool:
    """Check whether a stage's outputs are up-to-date and match *key*.

    Parameters
    ----------
    stage_dir:
        Directory for the stage outputs.
    key:
        Expected stage key string.

    Returns
    -------
    bool
        True if ``.stage.json`` exists, has matching *key*, and all recorded
        output files exist with matching sha256 digests.
    """
    stage_dir = Path(stage_dir)
    stamp_path = stage_dir / ".stage.json"
    if not stamp_path.is_file():
        return False
    try:
        stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return False
    if not isinstance(stamp, dict):
        return False
    if stamp.get("key") != key:
        return False
    outputs = stamp.get("outputs")
    if not isinstance(outputs, dict):
        return False
    for rel_str, expected_hash in outputs.items():
        if not isinstance(rel_str, str) or not isinstance(expected_hash, str):
            return False
        out_file = stage_dir / rel_str
        if not out_file.is_file():
            return False
        try:
            if _hash_file(out_file) != expected_hash:
                return False
        except OSError:
            return False
    return True
