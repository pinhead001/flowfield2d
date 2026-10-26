"""RAS 2025 land-cover n. A classification layer (`/Classification`) can hold a raster classifier
and a polygon classifier (`/Classification/Classification Polygons`: `Attributes` compound
with field `Classification` (fixed-width bytes), `Polygon` (n, 2) float64 holding every
polygon's exterior ring stacked without the closing vertex, attributes `Count` and `Start`
(int32, one entry per polygon)); polygons override the raster (probe 2026-10-25). An n layer
(`/NValues`) maps class names to n in `Table` (`Class` fixed-width bytes, `N Value` float32)
and names its classification layer in the attribute `Classification Layer Name`.
"""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import h5py
import h5py.h5a
import numpy as np
from shapely.geometry import Polygon

from flowfield2d.engines.ras2025.h5edit import recreate_dataset, write_fixed_string_attr

_POLYS_PATH: str = "/Classification/Classification Polygons"


def add_class_polygons(
    class_layer: Path,
    polygons: Sequence[Polygon],
    class_name: str,
) -> None:
    """Add classification polygons to a classification layer's polygon classifier."""
    if not polygons:
        raise ValueError("polygons sequence cannot be empty")
    if not class_name:
        raise ValueError("class_name cannot be empty")
    for poly in polygons:
        if poly is None or poly.is_empty or not poly.is_valid:
            raise ValueError(f"Invalid or empty polygon: {poly!r}")

    coords_list: list[np.ndarray[Any, np.dtype[np.float64]]] = []
    added_counts: list[int] = []
    for poly in polygons:
        pts = np.asarray(poly.exterior.coords[:-1], dtype=np.float64)
        coords_list.append(pts)
        added_counts.append(len(pts))

    class_bytes = class_name.encode("ascii")

    with h5py.File(class_layer, "r+", locking=False) as f:
        p: h5py.Group = f.require_group(_POLYS_PATH)

        # 1. Update or create Polygon dataset
        if "Polygon" in p:
            old_ds: h5py.Dataset = p["Polygon"]
            old_xy: np.ndarray[Any, np.dtype[np.float64]] = old_ds[()]
            old_counts: list[int] = [int(c) for c in old_ds.attrs["Count"]]
            old_starts: list[int] = [int(s) for s in old_ds.attrs["Start"]]

            start_offset = len(old_xy)
            new_starts = list(old_starts)
            new_counts = list(old_counts)
            for c in added_counts:
                new_starts.append(start_offset)
                new_counts.append(c)
                start_offset += c

            new_xy = np.vstack([old_xy, *coords_list])
            ds_poly: h5py.Dataset = recreate_dataset(p, "Polygon", new_xy)
        else:
            start_offset = 0
            new_starts = []
            new_counts = []
            for c in added_counts:
                new_starts.append(start_offset)
                new_counts.append(c)
                start_offset += c

            new_xy = np.vstack(coords_list)
            ds_poly = p.create_dataset("Polygon", data=new_xy)

        if "Count" in ds_poly.attrs:
            del ds_poly.attrs["Count"]
        ds_poly.attrs.create(
            "Count",
            data=np.asarray(new_counts, dtype=np.int32),
            dtype=np.int32,
        )
        if "Start" in ds_poly.attrs:
            del ds_poly.attrs["Start"]
        ds_poly.attrs.create(
            "Start",
            data=np.asarray(new_starts, dtype=np.int32),
            dtype=np.int32,
        )

        # 2. Update or create Attributes dataset
        if "Attributes" in p:
            old_att_ds: h5py.Dataset = p["Attributes"]
            existing_records: np.ndarray[Any, np.dtype[Any]] = old_att_ds[()]
            existing_width = int(old_att_ds.dtype["Classification"].itemsize)
            new_width = max(existing_width, len(class_bytes))

            new_descr: list[tuple[str, Any]] = []
            assert old_att_ds.dtype.names is not None
            for name in old_att_ds.dtype.names:
                if name == "Classification":
                    new_descr.append((name, f"S{new_width}"))
                else:
                    new_descr.append((name, old_att_ds.dtype[name]))
            new_dtype = np.dtype(new_descr)

            n_old = len(existing_records)
            n_new = len(polygons)
            new_records = np.empty(n_old + n_new, dtype=new_dtype)
            for name in old_att_ds.dtype.names:
                if name == "Classification":
                    new_records[name][:n_old] = existing_records[name]
                    new_records[name][n_old:] = class_bytes
                else:
                    new_records[name][:n_old] = existing_records[name]

            if new_width > existing_width:
                att_attrs = dict(old_att_ds.attrs)
                del p["Attributes"]
                new_att_ds: h5py.Dataset = p.create_dataset("Attributes", data=new_records)
                for k, v in att_attrs.items():
                    new_att_ds.attrs[k] = v
            else:
                recreate_dataset(p, "Attributes", new_records)
        else:
            width = len(class_bytes)
            dtype = np.dtype([("Classification", f"S{width}")])
            records = np.empty(len(polygons), dtype=dtype)
            records["Classification"][:] = class_bytes
            p.create_dataset("Attributes", data=records)


def set_n_value(n_layer: Path, class_name: str, n: float) -> None:
    """Add or update a land-cover class roughness n-value in an n layer."""
    if n <= 0.0:
        raise ValueError(f"n must be positive, got {n}")
    if not class_name:
        raise ValueError("class_name cannot be empty")

    class_bytes = class_name.encode("ascii")

    with h5py.File(n_layer, "r+", locking=False) as f:
        g: h5py.Group = f.require_group("/NValues")

        if "Table" not in g:
            width = len(class_bytes)
            dtype = np.dtype([("Class", f"S{width}"), ("N Value", "<f4")])
            row = np.array([(class_bytes, np.float32(n))], dtype=dtype)
            g.create_dataset("Table", data=row)
            return

        old_ds: h5py.Dataset = g["Table"]
        table: np.ndarray[Any, np.dtype[Any]] = old_ds[()]
        existing_width = int(old_ds.dtype["Class"].itemsize)

        match_idx: int | None = None
        for idx in range(len(table)):
            row_class = bytes(table["Class"][idx]).rstrip(b"\x00")
            if row_class == class_bytes:
                match_idx = idx
                break

        if match_idx is not None:
            table["N Value"][match_idx] = np.float32(n)
            recreate_dataset(g, "Table", table)
            return

        new_width = max(existing_width, len(class_bytes))
        new_descr: list[tuple[str, Any]] = []
        assert old_ds.dtype.names is not None
        for fname in old_ds.dtype.names:
            if fname == "Class":
                new_descr.append((fname, f"S{new_width}"))
            else:
                new_descr.append((fname, old_ds.dtype[fname]))
        new_dtype = np.dtype(new_descr)

        new_table = np.empty(len(table) + 1, dtype=new_dtype)
        for fname in old_ds.dtype.names:
            if fname == "Class":
                new_table[fname][:len(table)] = table[fname]
                new_table[fname][-1] = class_bytes
            elif fname == "N Value":
                new_table[fname][:len(table)] = table[fname]
                new_table[fname][-1] = np.float32(n)
            else:
                new_table[fname][:len(table)] = table[fname]

        if new_width > existing_width:
            table_attrs = dict(old_ds.attrs)
            del g["Table"]
            new_ds: h5py.Dataset = g.create_dataset("Table", data=new_table)
            for k, v in table_attrs.items():
                new_ds.attrs[k] = v
        else:
            recreate_dataset(g, "Table", new_table)


def link_classification(n_layer: Path, class_layer_name: str) -> None:
    """Link an n layer to a classification layer by name."""
    with h5py.File(n_layer, "r+", locking=False) as f:
        g: h5py.Group = f.require_group("/NValues")
        attr_name = "Classification Layer Name"
        if attr_name in g.attrs:
            aid = h5py.h5a.open(g.id, attr_name.encode("utf-8"))
            try:
                stored_size = int(aid.get_type().get_size())
            finally:
                aid.close()

            if len(class_layer_name) > stored_size:
                del g.attrs[attr_name]
                write_fixed_string_attr(
                    g,
                    attr_name,
                    class_layer_name,
                    size=len(class_layer_name),
                )
            else:
                write_fixed_string_attr(g, attr_name, class_layer_name)
        else:
            write_fixed_string_attr(
                g,
                attr_name,
                class_layer_name,
                size=len(class_layer_name),
            )
