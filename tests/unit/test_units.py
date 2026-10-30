import math

import pytest

from flowfield2d.units import M_PER_FT, ft_to_m, length_unit_m, m_to_ft


def test_exact_foot() -> None:
    assert M_PER_FT == 0.3048
    assert ft_to_m(1.0) == 0.3048


def test_round_trip() -> None:
    for x in (0.0, 1.0, 12.5, 1e6):
        assert math.isclose(m_to_ft(ft_to_m(x)), x, rel_tol=1e-12)


def test_length_unit_m_names() -> None:
    """Unit names as CRS WKT and sidecars spell them (case, spaces, underscores do not matter)."""
    for name in ("metre", "meter", "m", "Metres", "meters"):
        assert length_unit_m(name) == 1.0
    for name in ("foot", "ft", "feet", "international foot", "FOOT"):
        assert length_unit_m(name) == 0.3048
    for name in ("US survey foot", "us_survey_foot", "ftUS", "US_Foot", "us foot"):
        assert math.isclose(length_unit_m(name), 1200.0 / 3937.0, rel_tol=1e-15)
    assert length_unit_m("  foot ") == 0.3048


def test_length_unit_m_rejects_unknown_names() -> None:
    for name in ("", "  ", "degree", "furlong", "f"):
        with pytest.raises(ValueError, match="unit"):
            length_unit_m(name)
