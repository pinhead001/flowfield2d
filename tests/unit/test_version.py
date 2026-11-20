"""The package version string must match pyproject.toml (it is written into every manifest)."""

import tomllib
from pathlib import Path

import flowfield2d


def test_version_matches_pyproject() -> None:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    declared = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
    assert flowfield2d.__version__ == declared
