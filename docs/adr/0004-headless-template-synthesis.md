# ADR-0004 — Headless template synthesis from a donor project

- Status: **proposed** (lead, 2026-10-25) · Decision owner: Chris Nelson · Amends ADR-0001 (Tier B) and its
  addendum 1 (one GUI-authored template per river segment)

## Context
ADR-0001 settled on Tier B: HEC-RAS 2025 geometry is authored in the GUI and the pipeline clones it. Addendum 1
reduced that to one GUI template per river segment, with subdomains derived in code. For a first consumer with
many segments, even one GUI outline per segment is the main manual cost (10 minutes per outline measured), and it
is a human step in an otherwise headless pipeline.

Three probes on real RAS (consumer records in `methow-hydraulics/docs/plans/`) show the remaining GUI steps can be
done headless from any donor project of the same build and projection:
1. **New layers and bindings** (`probe-t03-layers-2026-10-25.md`): copy geometry/BC/plan layers under new
   names, rewrite their fixed-width internal names in place, add plan and geometry associations to the project
   XML (no CLI command exists for this), bind the geometry to a different terrain, regenerate the mesh, solve.
   Result: terrain signature MATCH, solve success.
2. **New outline and BC lines** (`domaingen-benchmark-2026-10-25.md`): replace the 2D-area polygon and move BC
   lines in a donor clone; prepare and solve succeed once the outline is on valid terrain and its edge is smooth.
3. **Automated outline** (same record): lidar footprint -> coarse max-flow run -> envelope within a freeboard of
   the max WSE: 339 s hands-off vs 10 minutes by hand, IoU 0.75 with the manual outline, 161 vs 1,360 vertices.

## Decision (proposed)
- Production models are synthesised from **one donor project** (any GUI-authored project with the pinned build,
  projection, and the needed terrain/n-value layers): `templates.copy_layer`, `templates.set_associations`,
  `split.replace_outline`, then cell sizing and `generate-mesh` through the CLI.
- Outlines come from the domain generator (`domaingen`) and are written as GeoJSON for review; a person may edit
  an outline (few vertices by design) and rerun from that stage. GUI-authored templates per segment remain the
  fallback.
- Rules learned in the probes are enforced in code: outlines lie on valid terrain (full-resolution valid area,
  eroded, holes kept); erode deeper than the simplification tolerance; new layer names no longer than the donor's
  (fixed-width names); associations edited line-by-line, byte-faithful otherwise.
- The capability flags stay honest: `geometry_authoring_headless` remains False (no new 2D-area *authoring* via
  the CLI); synthesis edits donor geometry within the HDF5 rules (recreate datasets, keep fixed-width strings).

## Consequences
- No GUI step per segment; the only manual inputs are the donor project and (optionally) outline edits.
- The pipeline gains a domain-generation stage before S1, with its own stamp and outputs.
- Risk: the project XML is edited outside RAS; a future build could change its schema. The schema guard and the
  pinned build cover this; a new build reruns the three probes.
- Risk: RAS may reject geometry the probes did not cover (multiple 2D areas, breaklines, structures). Out of scope
  until a consumer needs them.
