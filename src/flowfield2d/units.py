"""Unit conversions. Units convert only at data-contract boundaries (REQUIREMENTS 5)."""

M_PER_FT: float = 0.3048


def ft_to_m(x: float) -> float:
    """Convert feet to meters."""
    return x * M_PER_FT


def m_to_ft(x: float) -> float:
    """Convert meters to feet."""
    return x / M_PER_FT
