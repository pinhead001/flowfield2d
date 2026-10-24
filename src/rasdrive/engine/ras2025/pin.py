"""Build pin: build ID plus SHA256 of ras.exe and key DLLs; refuse to run on mismatch."""

import hashlib
import tomllib
from dataclasses import dataclass
from pathlib import Path

_BLOCK_SIZE: int = 1024 * 1024  # 1 MiB


class PinMismatch(RuntimeError):
    """Raised when the HEC-RAS installation does not match the pinned build."""


@dataclass(frozen=True)
class Pin:
    """Pinned build specification."""

    build: str
    dir: Path
    sha256: dict[str, str]

    def __post_init__(self) -> None:
        if not isinstance(self.dir, Path):
            object.__setattr__(self, "dir", Path(self.dir))
        normalized = {
            str(k).replace("\\", "/"): str(v).lower()
            for k, v in self.sha256.items()
        }
        object.__setattr__(self, "sha256", normalized)


def sha256_file(path: Path) -> str:
    """Compute the SHA256 hex digest of a file, streaming in 1 MiB blocks."""
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_BLOCK_SIZE):
            hasher.update(chunk)
    return hasher.hexdigest().lower()


def load_pin(path: Path) -> Pin:
    """Load a Pin definition from a TOML file."""
    with path.open("rb") as f:
        data = tomllib.load(f)

    build = str(data["build"])
    dir_path = Path(str(data["dir"]))
    raw_sha = data.get("sha256", {})
    sha256: dict[str, str] = {}
    if isinstance(raw_sha, dict):
        sha256 = {
            str(k).replace("\\", "/"): str(v).lower()
            for k, v in raw_sha.items()
        }
    return Pin(build=build, dir=dir_path, sha256=sha256)


def verify(pin: Pin, ras_dir: Path | None = None) -> None:
    """Verify that every listed file matches the pinned SHA256 hash."""
    if not pin.sha256:
        raise PinMismatch(f"Build {pin.build}: pin contains no hashes")

    base_dir = Path(ras_dir) if ras_dir is not None else pin.dir
    bad_files: list[str] = []

    for rel_path, expected_hash in pin.sha256.items():
        target = base_dir / rel_path
        if not target.exists():
            bad_files.append(f"{rel_path} (missing)")
        elif not target.is_file():
            bad_files.append(f"{rel_path} (not a regular file)")
        else:
            actual = sha256_file(target)
            if actual.lower() != expected_hash.lower():
                bad_files.append(
                    f"{rel_path} (hash mismatch: expected {expected_hash.lower()}, "
                    f"got {actual.lower()})"
                )

    if bad_files:
        details = ", ".join(bad_files)
        raise PinMismatch(f"Build {pin.build} verification failed: {details}")
