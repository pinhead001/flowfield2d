"""Unit conversions. Units convert only at data-contract boundaries (REQUIREMENTS 5)."""

M_PER_FT: float = 0.3048


def ft_to_m(x: float) -> float:
    """Convert feet to meters."""
    return x * M_PER_FT


def m_to_ft(x: float) -> float:
    """Convert meters to feet."""
    return x / M_PER_FT


M_PER_US_SURVEY_FT: float = 1200.0 / 3937.0

_LENGTH_UNITS_M: dict[str, float] = {
    "metre": 1.0, "meter": 1.0, "metres": 1.0, "meters": 1.0, "m": 1.0,
    "foot": M_PER_FT, "feet": M_PER_FT, "ft": M_PER_FT, "international foot": M_PER_FT,
    "us survey foot": M_PER_US_SURVEY_FT, "us survey feet": M_PER_US_SURVEY_FT,
    "us foot": M_PER_US_SURVEY_FT, "ftus": M_PER_US_SURVEY_FT,
}


def length_unit_m(name: str) -> float:
    """Metres per unit for a length unit named as CRS WKT or a terrain sidecar spells it (case,
    surrounding spaces and underscores do not matter); ValueError for an unknown name."""
    key = " ".join(name.strip().lower().replace("_", " ").split())
    try:
        return _LENGTH_UNITS_M[key]
    except KeyError:
        raise ValueError(f"unknown length unit {name!r}") from None
