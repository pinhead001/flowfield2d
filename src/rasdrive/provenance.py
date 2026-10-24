"""Run manifests: build, validate, and write provenance records for rasdrive runs."""

import hashlib
import json
import subprocess
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import rasdrive

REQUIRED: tuple[str, ...] = (
    "manifest_version",
    "created",
    "run_id",
    "rasdrive_version",
    "repos",
    "lockfiles",
    "engine",
    "inputs",
    "params",
    "convergence",
)

_BLOCK_SIZE: int = 1024 * 1024  # 1 MiB


class ManifestError(ValueError):
    """Raised when a manifest is missing required keys or has incorrect types."""


def _sha256_file(path: Path) -> str:
    """Compute the SHA256 hex digest of a file, streaming in 1 MiB blocks."""
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_BLOCK_SIZE):
            hasher.update(chunk)
    return hasher.hexdigest()


def git_state(repo: Path) -> dict[str, str | bool]:
    """Return the HEAD commit SHA and dirty flag for a git repository.

    Args:
        repo: Path to the root of a git repository.

    Returns:
        A dict with keys ``commit`` (40-char hex SHA) and ``dirty`` (bool).
    """
    commit_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    commit: str = commit_result.stdout.strip()

    status_result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    dirty: bool = bool(status_result.stdout.strip())

    return {"commit": commit, "dirty": dirty}


def file_hashes(paths: Iterable[Path], root: Path | None = None) -> dict[str, str]:
    """Compute SHA256 hashes for a collection of files.

    Args:
        paths: Files to hash.
        root: When given, keys are POSIX paths relative to this directory.
              When omitted, keys are bare file names.

    Returns:
        A dict mapping path key to hex digest, sorted by key.
    """
    result: dict[str, str] = {}
    for p in paths:
        if root is not None:
            key = p.relative_to(root).as_posix()
        else:
            key = p.name
        result[key] = _sha256_file(p)
    return dict(sorted(result.items()))


def build_manifest(
    *,
    run_id: str,
    repos: dict[str, Path],
    lockfiles: Iterable[Path],
    engine: dict[str, str],
    inputs: Iterable[Path],
    params: dict[str, Any],
    convergence: dict[str, Any],
    extra: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Construct a provenance manifest dictionary.

    Args:
        run_id: Unique identifier for this run.
        repos: Mapping of repository name to local path.
        lockfiles: Dependency lock files to hash (keyed by file name).
        engine: Must contain at least ``build`` and ``binary_sha256``.
        inputs: Input files to hash (keyed by file name).
        params: Run parameters.
        convergence: Convergence diagnostics.
        extra: Additional caller-supplied keys; defaults to ``{}``.
        now: UTC timestamp for ``created``; defaults to ``datetime.now(UTC)``.

    Returns:
        A manifest dict satisfying ``REQUIRED``.

    Raises:
        ManifestError: If ``engine`` is missing ``build`` or ``binary_sha256``.
    """
    missing_engine = [k for k in ("build", "binary_sha256") if k not in engine]
    if missing_engine:
        raise ManifestError(
            f"engine dict is missing required key(s): {', '.join(missing_engine)}"
        )

    if now is None:
        now = datetime.now(UTC)

    created: str = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    manifest: dict[str, Any] = {
        "manifest_version": 1,
        "created": created,
        "run_id": run_id,
        "rasdrive_version": rasdrive.__version__,
        "repos": {name: git_state(path) for name, path in repos.items()},
        "lockfiles": file_hashes(lockfiles),
        "engine": engine,
        "inputs": file_hashes(inputs),
        "params": params,
        "convergence": convergence,
        "extra": extra if extra is not None else {},
    }
    return manifest


def validate_manifest(m: dict[str, Any]) -> None:
    """Validate that a manifest contains all required keys with correct types.

    Args:
        m: Manifest dict to validate.

    Raises:
        ManifestError: Naming every missing required key and every type violation.
    """
    problems: list[str] = []

    for key in REQUIRED:
        if key not in m:
            problems.append(f"missing required key: '{key}'")

    _dict_keys: tuple[str, ...] = (
        "repos",
        "lockfiles",
        "inputs",
        "engine",
        "params",
        "convergence",
    )
    for key in _dict_keys:
        if key in m and not isinstance(m[key], dict):
            problems.append(f"'{key}' must be a dict, got {type(m[key]).__name__}")

    if "manifest_version" in m and not isinstance(m["manifest_version"], int):
        problems.append(
            f"'manifest_version' must be int, got {type(m['manifest_version']).__name__}"
        )

    if problems:
        raise ManifestError("; ".join(problems))


def write_manifest(m: dict[str, Any], path: Path) -> None:
    """Validate and write a manifest to a JSON file.

    Args:
        m: Manifest dict to write.
        path: Destination file path.

    Raises:
        ManifestError: If the manifest is invalid (see :func:`validate_manifest`).
    """
    validate_manifest(m)
    path.write_text(json.dumps(m, sort_keys=True, indent=2), encoding="utf-8")
