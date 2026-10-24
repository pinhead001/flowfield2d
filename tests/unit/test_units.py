import math

from flowfield2d.units import M_PER_FT, ft_to_m, m_to_ft


def test_exact_foot() -> None:
    assert M_PER_FT == 0.3048
    assert ft_to_m(1.0) == 0.3048


def test_round_trip() -> None:
    for x in (0.0, 1.0, 12.5, 1e6):
        assert math.isclose(m_to_ft(ft_to_m(x)), x, rel_tol=1e-12)
