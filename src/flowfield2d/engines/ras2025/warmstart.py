"""A ready-to-run file (`ras plan prepare`) stores the prepared initial state
under /Results/Initial Conditions/2D Flow Areas/<area>/ (`Cell Depth` per cell,
`Face Velocity` per face); overwriting it before `ras plan solve` starts
the run warm on the same mesh (probe 2026-10-25: depth plus face velocity
continues a run to about 0.001 ft mean; depth alone recovers within about an hour).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import h5py
import numpy as np
from numpy.typing import NDArray

from flowfield2d.engines.ras2025.h5edit import recreate_dataset


@dataclass(frozen=True)
class MeshState:
    """State of a 2D mesh: cell depth and optional face velocity."""

    cell_depth: NDArray[np.float64]
    face_velocity: NDArray[np.float64] | None = None


def read_state(result: Path, area: str, index: int) -> MeshState:
    """Read a mesh state at the given output index from a result HDF5 file."""
    group_path = f"/Results/Output Blocks/Base Output/2D Flow Areas/{area}"
    with h5py.File(result, "r", locking=False) as f:
        if group_path not in f:
            raise KeyError(
                f"Area {area!r} not found under "
                f"/Results/Output Blocks/Base Output/2D Flow Areas/"
            )
        grp = f[group_path]
        if "Cell Depth" not in grp or "Face Velocity" not in grp:
            raise KeyError(f"Datasets missing for area {area!r} in {result}")

        depth_ds: h5py.Dataset = grp["Cell Depth"]
        vel_ds: h5py.Dataset = grp["Face Velocity"]

        n_t = depth_ds.shape[0]
        if index < -n_t or index >= n_t:
            raise IndexError(f"Index {index} out of range for output with {n_t} time steps")

        resolved_index = n_t + index if index < 0 else index
        cell_depth = np.asarray(depth_ds[resolved_index], dtype=np.float64)
        face_velocity = np.asarray(vel_ds[resolved_index], dtype=np.float64)

    return MeshState(cell_depth=cell_depth, face_velocity=face_velocity)


def write_initial_state(r2r: Path, area: str, state: MeshState) -> None:
    """Write initial conditions into a ready-to-run RAS HDF5 file."""
    group_path = f"/Results/Initial Conditions/2D Flow Areas/{area}"
    with h5py.File(r2r, "r+", locking=False) as f:
        if group_path not in f:
            raise KeyError(f"Initial conditions group for area {area!r} not found in {r2r}")
        grp = f[group_path]
        if "Cell Depth" not in grp or "Face Velocity" not in grp:
            raise KeyError(f"Initial condition datasets missing in {group_path}")

        existing_depth: h5py.Dataset = grp["Cell Depth"]
        existing_velocity: h5py.Dataset = grp["Face Velocity"]

        n_cells = existing_depth.shape[0]
        if state.cell_depth.ndim != 1 or state.cell_depth.shape[0] != n_cells:
            raise ValueError(
                f"Cell depth length ({state.cell_depth.shape}) "
                f"differs from existing Cell Depth ({n_cells}) cells"
            )

        n_faces = existing_velocity.shape[0]
        if state.face_velocity is not None:
            if state.face_velocity.ndim != 1 or state.face_velocity.shape[0] != n_faces:
                raise ValueError(
                    f"Face velocity length ({state.face_velocity.shape}) "
                    f"differs from existing Face Velocity ({n_faces}) faces"
                )

        if not np.all(np.isfinite(state.cell_depth)) or np.any(state.cell_depth < 0.0):
            raise ValueError("Cell depth contains negative or non-finite depth values")

        recreate_dataset(grp, "Cell Depth", state.cell_depth)
        if state.face_velocity is not None:
            recreate_dataset(grp, "Face Velocity", state.face_velocity)
        else:
            recreate_dataset(
                grp, "Face Velocity", np.zeros(n_faces, dtype=existing_velocity.dtype)
            )
