from pathlib import Path

from rasdrive.boundary import load_terms, scan


def _write(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_load_terms_skips_comments_and_blanks(tmp_path: Path) -> None:
    f = _write(tmp_path / "terms.txt", "# comment\n\nAlpha\n  Beta  \nre:EPSG:?99\\d\\d\n")
    terms = load_terms([f])
    assert [t.label for t in terms] == ["Alpha", "Beta", "re:EPSG:?99\\d\\d"]


def test_scan_matches_case_insensitive_whole_token(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "a.py", "x = 'alpha_river'\n")  # '_' counts as a boundary
    _write(tmp_path / "src" / "b.py", "alphabet = 1\n")  # inside a word: no hit
    _write(tmp_path / "docs" / "c.md", "Uses ALPHA here.\n")
    terms = load_terms([_write(tmp_path / "t.txt", "Alpha\n")])
    hits = scan(tmp_path, terms, subdirs=("src", "docs"))
    assert sorted((h.path.name, h.line) for h in hits) == [("a.py", 1), ("c.md", 1)]


def test_scan_regex_term(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "a.py", "crs = 'EPSG:9912'\n")
    terms = load_terms([_write(tmp_path / "t.txt", "re:EPSG:?99\\d\\d\n")])
    assert len(scan(tmp_path, terms, subdirs=("src",))) == 1


def test_scan_ignores_binary_caches_and_missing_dirs(tmp_path: Path) -> None:
    (tmp_path / "src" / "__pycache__").mkdir(parents=True)
    (tmp_path / "src" / "__pycache__" / "m.pyc").write_bytes(b"\x00alpha")
    (tmp_path / "src" / "img.png").write_bytes(b"\x89PNG\x00alpha")
    terms = load_terms([_write(tmp_path / "t.txt", "Alpha\n")])
    assert scan(tmp_path, terms, subdirs=("src", "nope")) == []
