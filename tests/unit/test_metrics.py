import numpy as np
import pytest

from rasdrive.post.metrics import METRIC_COLUMNS, feature_metrics, shear_stress


def test_shear_stress_hand_calculations() -> None:
    # SI: tau = rho g n^2 V^2 / h^(1/3);  1000*9.81*0.04^2*2^2 / 8^(1/3) = 31.392 Pa
    assert shear_stress(0.04, 2.0, 8.0) == pytest.approx(31.392)
    assert shear_stress(0.035, 1.5, 1.0) == pytest.approx(27.0388125)
    # US: gamma = 62.4 lb/ft^3 and divide by 1.486^2;  62.4*0.035^2*25/(2.208196*3^(1/3))
    assert shear_stress(0.035, 5.0, 3.0, units="US") == pytest.approx(0.60004338, rel=1e-7)
    arr = shear_stress(np.array([0.04, 0.04]), np.array([2.0, 2.0]), np.array([8.0, 0.0]))
    assert arr[0] == pytest.approx(31.392) and np.isnan(arr[1])     # dry cell -> NaN
    with pytest.raises(ValueError):
        shear_stress(0.04, 2.0, 8.0, units="furlongs")


def _grid() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    depth = np.array([[0.0, 0.5, 1.0],
                      [0.2, 1.5, np.nan],
                      [0.0, 0.0, 0.0]])
    vel = np.array([[0.0, 1.0, 2.0],
                    [0.5, 3.0, np.nan],
                    [0.0, 0.0, 0.0]])
    mask = np.array([[True, True, True],
                     [True, True, True],
                     [False, False, False]])
    return depth, vel, mask


def test_feature_metrics_on_a_hand_grid() -> None:
    depth, vel, mask = _grid()
    ref = np.array([[True, True, False], [True, True, False], [True, True, True]])
    void = np.zeros_like(mask)
    void[1, 1] = True
    m = feature_metrics("f1", "s1", depth, vel, mask, cell_area=4.0, length=6.0,
                        min_depth=0.01, reference_extent=ref, void_mask=void,
                        converged=True, percentiles=(50,))
    assert set(m) == set(METRIC_COLUMNS) | {"depth_p50", "velocity_p50", "shear_p50"}
    # wet cells inside mask: depths 0.5, 1.0, 0.2, 1.5  -> 4 cells * 4 m2
    assert m["wetted_area"] == 16.0
    assert m["mean_width"] == pytest.approx(16.0 / 6.0)
    assert m["depth_mean"] == pytest.approx(0.8) and m["depth_max"] == 1.5
    assert m["velocity_mean"] == pytest.approx(1.625) and m["velocity_max"] == 3.0
    assert m["depth_p50"] == pytest.approx(0.75)
    assert m["area_outside_reference"] == 4.0          # the wet cell at [0, 2]
    assert m["void_fraction"] == pytest.approx(0.25)   # 1 of 4 wet cells
    assert m["converged"] is True and m["feature_id"] == "f1" and m["scenario_id"] == "s1"
    assert np.isnan(m["shear_p50"])                    # no n supplied


def test_feature_metrics_with_roughness_and_dry_feature() -> None:
    depth, vel, mask = _grid()
    n = np.full(depth.shape, 0.04)
    m = feature_metrics("f", "s", depth, vel, mask, cell_area=1.0, length=1.0, roughness=n,
                        percentiles=(90,))
    assert m["shear_p90"] > 0
    dry = feature_metrics("f", "s", np.zeros((2, 2)), np.zeros((2, 2)), np.ones((2, 2), bool),
                          cell_area=1.0, length=2.0)
    assert dry["wetted_area"] == 0.0 and np.isnan(dry["depth_mean"])
    assert dry["void_fraction"] == 0.0
    with pytest.raises(ValueError):
        feature_metrics("f", "s", depth, vel[:2], mask, cell_area=1.0, length=1.0)
    with pytest.raises(ValueError):
        feature_metrics("f", "s", depth, vel, mask, cell_area=1.0, length=0.0)
