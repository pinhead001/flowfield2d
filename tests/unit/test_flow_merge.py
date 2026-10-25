"""Merging near-duplicate flows into one modelled flow each."""

import pytest

from flowfield2d.hydrograph import merge_flows


def test_merge_groups_flows_within_rel_tol_of_the_group_minimum() -> None:
    flows = [520.0, 100.0, 104.0, 500.0, 109.0, 2000.0]
    reps, index = merge_flows(flows, rel_tol=0.05, pick="max")
    # ascending: {100, 104}, then 109 > 100*1.05 starts a new group: {109}, {500, 520}, {2000}
    assert reps == [104.0, 109.0, 520.0, 2000.0]
    assert index == [2, 0, 0, 2, 1, 3]                      # per input flow, in input order
    assert [reps[i] for i in index] == [520.0, 104.0, 104.0, 520.0, 109.0, 2000.0]


def test_merge_pick_mean_and_no_chaining() -> None:
    reps, index = merge_flows([100.0, 104.0, 108.0, 112.0], rel_tol=0.05, pick="mean")
    assert reps == pytest.approx([102.0, 110.0])     # {100, 104}, {108, 112}: anchored, not chained
    assert index == [0, 0, 1, 1]


def test_merge_zero_tolerance_merges_exact_duplicates_only() -> None:
    reps, index = merge_flows([50.0, 50.0, 51.0], rel_tol=0.0, pick="max")
    assert reps == [50.0, 51.0] and index == [0, 0, 1]


@pytest.mark.parametrize(("flows", "rel_tol", "pick"), [
    ([], 0.05, "max"),
    ([100.0, 0.0], 0.05, "max"),
    ([100.0, -5.0], 0.05, "max"),
    ([100.0], -0.01, "max"),
    ([100.0], 0.05, "median"),
])
def test_merge_rejects_bad_input(flows: list[float], rel_tol: float, pick: str) -> None:
    with pytest.raises(ValueError):
        merge_flows(flows, rel_tol=rel_tol, pick=pick)  # type: ignore[arg-type]
