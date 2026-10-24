import pytest
from shapely.geometry import LineString

from rasdrive.domains import (
    Domain,
    bc_line,
    downstream_extension,
    overlaps,
    plan_domains,
    upstream_lead_in,
)


def test_extension_rules() -> None:
    # max(L_min, k * D_bf / S)
    assert downstream_extension(d_bf=1.0, slope=0.004) == pytest.approx(1000.0)     # 500 < 1 km
    assert downstream_extension(d_bf=2.0, slope=0.001) == pytest.approx(4000.0)
    assert downstream_extension(2.0, 0.001, l_min=500.0, k=1.0) == pytest.approx(2000.0)
    assert upstream_lead_in(w_bf=20.0) == 100.0
    assert upstream_lead_in(20.0, n_widths=3) == 60.0
    with pytest.raises(ValueError):
        downstream_extension(1.0, 0.0)


def test_plan_domains_two_segments_with_clipping_flags() -> None:
    # 10 km line, chainage 0 at the upstream end; one flow-change point at 4 km.
    ds = plan_domains(10_000.0, [4_000.0], w_bf=[20.0, 30.0], d_bf=[1.0, 2.0],
                      slope=[0.004, 0.001])
    assert [d.id for d in ds] == ["D01", "D02"]
    a, b = ds
    assert (a.analysis_start_m, a.analysis_end_m) == (0.0, 4_000.0)
    assert a.start_m == 0.0 and a.upstream_clipped                     # no room for 100 m lead-in
    assert a.end_m == pytest.approx(5_000.0) and not a.downstream_clipped
    assert b.start_m == pytest.approx(3_850.0)                          # 5 * 30 m lead-in
    assert b.end_m == 10_000.0 and b.downstream_clipped                 # wanted +4 km
    assert overlaps(ds) == [("D01", "D02", pytest.approx(1_150.0))]


def test_plan_domains_rejects_bad_points_and_lengths() -> None:
    with pytest.raises(ValueError):
        plan_domains(1000.0, [1500.0], w_bf=10.0, d_bf=1.0, slope=0.01)
    with pytest.raises(ValueError):
        plan_domains(1000.0, [600.0, 300.0], w_bf=10.0, d_bf=1.0, slope=0.01)
    with pytest.raises(ValueError):
        plan_domains(1000.0, [500.0], w_bf=[10.0], d_bf=1.0, slope=0.01)   # needs 2 values


def test_scalar_parameters_broadcast() -> None:
    ds = plan_domains(3000.0, [], w_bf=10.0, d_bf=1.0, slope=0.01, id_prefix="X")
    assert ds == [Domain("X01", 0.0, 3000.0, 0.0, 3000.0, True, True)]


def test_bc_line_is_perpendicular_and_centred() -> None:
    line = LineString([(0, 0), (100, 0), (100, 100)])
    bc = bc_line(line, chainage_m=50.0, half_width_m=10.0)
    assert sorted(bc.coords) == [(50.0, -10.0), (50.0, 10.0)]
    bc2 = bc_line(line, chainage_m=150.0, half_width_m=5.0)              # on the second leg
    assert sorted(bc2.coords) == [(95.0, 50.0), (105.0, 50.0)]
    with pytest.raises(ValueError):
        bc_line(line, chainage_m=250.0, half_width_m=5.0)
