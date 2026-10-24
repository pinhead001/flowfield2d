# CLI tree: ras.exe

- exe: `C:\Programs\HECRAS_2025\v0.1.0.5048-dev/ras.exe`
- crawled: 2026-10-24T00:06:06 → 2026-10-24T00:06:11 (66 calls)
- version: `ras 0.1.0.5048-dev`

## Commands

- `ras.exe` — (no description) [help]
  - `ras.exe benchmark` — Command group. Run performance benchmarks on RAS [help]
    - `ras.exe benchmark h5` — Writes an HDF5 file (serial and parallel) to check performance for [help]
    - `ras.exe benchmark hash` — Writes a random binary file to a temp directory, then hashes it [help]
    - `ras.exe benchmark solver` — Creates the synthetic Thacker 2D dataset and solves it across [help]
  - `ras.exe clone` — Clones a RAS file. [help]
  - `ras.exe geometry` — Command group. Inspect and interact with RAS geometry [help]
    - `ras.exe geometry generate-mesh` — Generates the computational mesh from an existing RAS [help]
    - `ras.exe geometry info` — Prints information about an existing RAS geometry file [help]
    - `ras.exe geometry modify` — Modifies topology fields of a RAS geometry file (*.h5) in [help]
  - `ras.exe h5` — Command group. Inspect, diff, and patch HDF5 files. [help]
    - `ras.exe h5 create-patch` — Decomposes an HDF5 file into a shared base hash-store and a [help]
    - `ras.exe h5 diff` — Prints the differences between two HDF5 files. [help]
    - `ras.exe h5 explore` — Interactive HDF5 file explorer with tree navigation and data [help]
    - `ras.exe h5 restore-patch` — Restores an original HDF5 file from a base hash-store and a [help]
    - `ras.exe h5 squeeze` — Squeezes an HDF5 file in-place to make it as small as [help]
  - `ras.exe healthcheck` — Initializes and tests various RAS dependencies. [help]
  - `ras.exe helpers` — Command group. General-purpose file utilities (zip, [help]
    - `ras.exe helpers extract` — Extracts a .zip archive into a target directory. [help]
    - `ras.exe helpers hash` — Hashes the given file with various hashing algorithms. [help]
    - `ras.exe helpers zip` — Compresses a directory into a .zip archive. [help]
  - `ras.exe info` — Opens a file, detects its type, and prints info by [help]
  - `ras.exe mesh` — Deprecated. Use 'ras geometry generate-mesh' instead. [help]
  - `ras.exe plan` — Command group. Inspect RAS plan files and the plans [help]
    - `ras.exe plan info` — Prints information about an existing RAS plan file (*.h5). [help]
    - `ras.exe plan modify` — Opens a RAS plan file (*.h5), changes one or more settings, and [help]
    - `ras.exe plan prepare` — Prepare a single plan (*.h5) for compute, producing a ready-to-run [help]
    - `ras.exe plan solve` — Run the RAS solver on a single plan (*.h5) or ready-to-run result [help]
  - `ras.exe prepare` — Prepare a project or plan for compute. Ingests all [help]
  - `ras.exe project` — Command group. Create, inspect, and modify RAS [help]
    - `ras.exe project add` — Adds an existing layer file (*.h5) to a [help]
    - `ras.exe project add-new` — Creates a brand-new layer file inside the [help]
    - `ras.exe project cleanup` — Cleans up old backup and result files based [help]
    - `ras.exe project create` — Create a new empty RAS project (*.ras). [help]
    - `ras.exe project explore` — Interactive RAS project explorer with tree [help]
    - `ras.exe project info` — Prints information about an existing RAS [help]
    - `ras.exe project prepare` — Prepare every plan in a project for [help]
    - `ras.exe project solve` — Run the RAS solver on every plan in a [help]
  - `ras.exe raster` — Command group. Translate and compute on raster files. [help]
    - `ras.exe raster calc` — Combines raster files using a mathematical expression. Input [help]
    - `ras.exe raster explore` — Interactive raster explorer: browse sub-datasets, metadata, [help]
    - `ras.exe raster info` — Prints information about a raster file (size, bands, projection, [help]
    - `ras.exe raster render` — Renders a raster on disk into a georeferenced color image (RGB or [help]
    - `ras.exe raster translate` — Creates a RAS-compliant .tif file from integer or float data [help]
  - `ras.exe result` — Command group. Inspect and generate maps from RAS [help]
    - `ras.exe result info` — Prints information about an existing RAS 2025+ result file [help]
    - `ras.exe result map` — Generates a map from a RAS 2025+ result. [help]
    - `ras.exe result postprocess` — Post-process a result (*.h5), generating its transposed [help]
  - `ras.exe s3` — Command group. Raw S3 operations against a bucket: [help]
    - `ras.exe s3 list-bucket` — Lists keys within an S3 bucket. Attempts anonymous access if [help]
    - `ras.exe s3 list-buckets` — Lists buckets visible on the S3 server. Attempts anonymous [help]
    - `ras.exe s3 presign` — Presigns an S3 key, returning a URL usable with the requested [help]
    - `ras.exe s3 pull` — Pulls a single object from S3 to a local file. Attempts [help]
    - `ras.exe s3 push` — Pushes a local file to S3 under the given key. Requires [help]
  - `ras.exe sample` — Command group. Browse, download, and publish RAS [help]
    - `ras.exe sample info` — Prints details about a single sample project (manifest, files, [help]
    - `ras.exe sample list` — Lists all sample projects available in the global example-project [help]
    - `ras.exe sample pull` — Downloads a sample project from S3 into the specified directory. [help]
    - `ras.exe sample push` — Uploads a project directory as a sample project, building its [help]
  - `ras.exe solve` — Run the RAS solver on a project, plan, or [help]
  - `ras.exe terrain` — Command group. Create, edit, and interact with your [help]
    - `ras.exe terrain add` — Adds one or more input rasters to an existing RAS terrain. [help]
    - `ras.exe terrain create` — Create a new empty RAS terrain (*.h5). Use 'terrain add' to add [help]
    - `ras.exe terrain export` — Exports a terrain to a new location. Optionally clips to an extent [help]
    - `ras.exe terrain info` — Prints information about an existing RAS terrain. [help]

## Skipped

- `ras.exe help` — help/version verb
- `ras.exe version` — help/version verb
- `ras.exe benchmark help` — help/version verb
- `ras.exe benchmark version` — help/version verb
- `ras.exe geometry help` — help/version verb
- `ras.exe geometry version` — help/version verb
- `ras.exe h5 help` — help/version verb
- `ras.exe h5 version` — help/version verb
- `ras.exe helpers help` — help/version verb
- `ras.exe helpers version` — help/version verb
- `ras.exe plan help` — help/version verb
- `ras.exe plan version` — help/version verb
- `ras.exe project remove` — risky name (use --allow)
- `ras.exe project help` — help/version verb
- `ras.exe project version` — help/version verb
- `ras.exe raster help` — help/version verb
- `ras.exe raster version` — help/version verb
- `ras.exe result help` — help/version verb
- `ras.exe result version` — help/version verb
- `ras.exe s3 help` — help/version verb
- `ras.exe s3 version` — help/version verb
- `ras.exe sample help` — help/version verb
- `ras.exe sample version` — help/version verb
- `ras.exe terrain remove` — risky name (use --allow)
- `ras.exe terrain help` — help/version verb
- `ras.exe terrain version` — help/version verb

## Options by command

### `ras.exe benchmark h5`
- `--preserve` Preserves the written H5 file. Defaults to false.
- `--help` Display this help screen.
- `--version` Display version information.

### `ras.exe benchmark hash`
- `--file-size` Set the file size to use. Units must be one of {B, KB, MB, GB, TB, KiB, MiB, GiB, TiB}.Ex: '1MB', '1.2 GiB', etc. Defaults to 1GB.
- `--file` Compute hashes on this specific file, instead a randomly generated file.
- `--rash-block` Set the RASH block-size to this value (see 'file-size' for acceptable argument formatting). Defaults to 1MiB. Other block sizes will produce different RASH values.
- `--help` Display this help screen.
- `--version` Display version information.

### `ras.exe benchmark solver`
- `--end-time` Simulation end-time in seconds. Lower this to shorten each solve. Defaults to 20000 (~20 timesteps).
- `--cores` Comma-separated list of core counts to benchmark, in order. Defaults to '1,4,16'.
- `--help` Display this help screen.
- `--version` Display version information.

### `ras.exe clone`
- `-s, --source` Required. Source filename to clone. Expected to be one of our core file types, Geometry/Plan/BC/Result/Terrain/NV.
- `-o, --output` Required. Destination filename. Should not exist. E.G. "./TerrainOut.h5"
- `-f, --force` If set, destination file will be deleted if necessary. Defaults to false.
- `--geometry-only` Saves only the geometry portion of a result file. Only valid if source file is a result. Defaults to false.
- `--regenerate-mesh` Force regenerate the mesh from inputs. Only valid if the output is a geometry file. Defaults to false.
- `--clean-mesh` Removes the computed mesh (and property tables) from the file. Only valid if the output is a geometry file. Defaults to false.
- `--help` Display this help screen.
- `--version` Display version information.

### `ras.exe geometry generate-mesh`
- `--squeeze` If set, will squeeze the file after successfully generating a mesh.
- `--help` Display this help screen.
- `--version` Display version information.
- `geometry (pos. 0)` required — Required. Geometry file (*.h5).

### `ras.exe geometry info`
- `--format` Output format: Text (default), Json, Markdown, or Properties (grep-friendly key=value).
- `--get` Print only the value(s) at a flattened key path (e.g. 'name' or 'layers[0].count'). Ignores --format.
- `--verify-table-signatures` Locate the owning project and verify each mesh's stored property-table terrain signature against the associated terrain. Prints SUCCESS or FAILURE instead of the info dump. Also works on a geometry embedded in a result file.
- `--help` Display this help screen.
- `--version` Display version information.
- `geometry (pos. 0)` required — Required. Geometry file (*.h5).

### `ras.exe geometry modify`
Usage: `List the default set of fields you can target/set (no file needed): ras geometry modify --grammar List what's settable in a specific geometry (real element counts): ras geometry modify --grammar Geometry.h5 Coarsen every region 1.5x (preview first with --dry-run): ras geometry modify --dry-run Geometry.h5 topology.region.cellsize.scale(1.5) Refine just the quad channel regions to half their cell size: ras geometry modify Geometry.h5 "topology.region[type = quad].cellsize.scale(0.5)" Refine only the large quad regions (compound filter on a derived field): ras geometry modify Geometry.h5 "topology.region[type = quad AND area > 500000].cellsize.scale(0.75)" Enforce a minimum cell size of 5 (select the too-small ones, then set): ras geometry modify Geometry.h5 "topology.region[cellsize < 5].cellsize.set(5)" Nudge quad orientation by 15 degrees (add onto the current value): ras geometry modify Geometry.h5 "topology.region[type = quad].RotationDegrees.add(15)" Switch tiny regions to a Cartesian patch (enum field - assignment, not an operation): ras geometry modify Geometry.h5 "topology.region[area < 10000].type = cartesian" Denser point spacing along long breakline arcs: ras geometry modify Geometry.h5 "topology.arc[length > 1000].cellsize.scale(0.5)" Coarsen specific arcs by index: ras geometry modify Geometry.h5 "topology.arc[index IN (0, 1, 2)].cellsize.scale(1.5)" Pin an explicit point count on arcs that have no constant size set: ras geometry modify Geometry.h5 "topology.arc[cellsize IS NULL].count.set(40)" Make the longer breaklines follow the terrain exactly (bool field - assignment): ras geometry modify Geometry.h5 "topology.arc[length > 500].FollowExactly = true" Refine the channel and coarsen the overbanks in one save (several selectors): ras geometry modify Geometry.h5 "topology.region[type = quad].cellsize.scale(0.5)" "topology.region[type = cartesian].cellsize.scale(2)"`
- `--grammar` List every path and field you can target in this geometry (no changes made), then exit.
- `--case-sensitive` Make string comparisons in the inline filter case-sensitive.
- `--dry-run` Report what would change without writing the file.
- `--format` Output format for the change report: Text (default), Json, or Properties (grep-friendly key=value). Errors always go to stderr as text, so stdout stays parseable.
- `--help` Display this help screen.
- `--version` Display version information.
- `geometry (pos. 0)` — Geometry file (*.h5). Optional with --grammar (omit it to print the default schema).
- `set (pos. 1)` — One or more selectors: a path to a collection (region/arc) with an optional [predicate], ending in either an assignment (= value) or a numeric operation (.scale(x)/.add(x)/.set(x)). The [predicate] picks which elements change. E.g. "topology.region[type = quad AND cellsize < 10].cellsize.scale(0.5)" (operation) or "topology.region[area < 10000].type = cartesian" (assignment). Operations are numeric-only; use = value for enum/bool/string fields. Pass several to change several things in one save. See the examples above. Not required with --grammar.

### `ras.exe h5 create-patch`
- `-s, --source` Required. Source HDF5 file to decompose (must exist).
- `-b, --base` Required. Base hash-store file (created if absent, appended if exists).
- `-p, --patch` Required. Output patch file path.
- `--min-size` (Default: 65536) Minimum compressed bytes for a dataset to be extracted to base.
- `--allowed-paths` Pipe-delimited path prefixes to include, e.g. /Results|/Geometry
- `--dry-run` Validate inputs and print plan without writing any files.
- `--verbose` Print each extracted dataset (path, hash, size).
- `--help` Display this help screen.
- `--version` Display version information.

### `ras.exe h5 diff`
- `--filter` Filter options. String is pipe-delimited. Entries use '!' to disinclude and '+' to include in the output.E.G. '-/Results' to disinclude the /Results group, or '+/Geometry' to ONLY search the /Geometry group.
- `--help` Display this help screen.
- `--version` Display version information.

### `ras.exe h5 explore`
- `--help` Display this help screen.
- `--version` Display version information.

### `ras.exe h5 restore-patch`
- `-b, --base` Required. Base hash-store file (must exist).
- `-p, --patch` Required. Patch file (must exist).
- `-o, --output` Required. Output restored HDF5 file path.
- `--dry-run` Read patch instructions and print plan without writing any files.
- `--verbose` Print detailed restore info.
- `--help` Display this help screen.
- `--version` Display version information.

### `ras.exe h5 squeeze`
- `-s, --source` Required. HDF5 file to squeeze OR a directory. Expected extension (*.hdf, *.h5).
- `--recurse` If source is a directory, this option will recurse through subdirectories for the
- `--help` Display this help screen.
- `--version` Display version information.

### `ras.exe healthcheck`
- `--help` Display this help screen.
- `--version` Display version information.

### `ras.exe helpers extract`
- `-f, --force` Overwrite existing files in the output directory. Defaults to false.
- `--help` Display this help screen.
- `--version` Display version information.
- `source (pos. 0)` required — Required. Source .zip archive to extract.
- `output (pos. 1)` required — Required. Output directory. Created if missing. If non-empty, must be combined with --force argument.

### `ras.exe helpers hash`
- `-s, --source` Required. File to compute hashes on.
- `-a, --algorithm` Algorithm to compute. If blank, will compute and print all, separated by newlines. Expected one of {RashXX3, SHA256, MD5}.
- `--help` Display this help screen.
- `--version` Display version information.

### `ras.exe helpers zip`
- `-f, --force` Force overwrite existing target file. Defaults to false.
- `-l, --level` Compression level: Optimal (default), Fastest, NoCompression, or SmallestSize.
- `--help` Display this help screen.
- `--version` Display version information.
- `source (pos. 0)` required — Required. Source directory to compress.
- `output (pos. 1)` required — Required. Output .zip filename. If file already exists, must be combined with --force argument.

### `ras.exe info`
- `--format` Output format: Text (default), Json, Markdown, or Properties (grep-friendly key=value).
- `--get` Print only the value(s) at a flattened key path (e.g. 'name'). Ignores --format.
- `--help` Display this help screen.
- `--version` Display version information.
- `source (pos. 0)` required — Required. Input file.

### `ras.exe mesh`
- `-s, --source` Required. Input RAS Geometry file (*.h5).
- `--squeeze` If set, will squeeze the file after successfully generating a mesh.
- `--help` Display this help screen.
- `--version` Display version information.

### `ras.exe plan info`
- `--format` Output format: Text (default), Json, Markdown, or Properties (grep-friendly key=value).
- `--get` Print only the value(s) at a flattened key path (e.g. 'name'). Ignores --format.
- `--help` Display this help screen.
- `--version` Display version information.
- `plan (pos. 0)` required — Required. Plan file (*.h5).

### `ras.exe plan modify`
Usage: `List the fields you can target/set (no file needed): ras plan modify --grammar List the fields and their current values in a specific plan: ras plan modify --grammar Plan.p01.hdf Switch the plan to the GPU solver (preview first with --dry-run): ras plan modify --dry-run Plan.p01.hdf "solvertype = GPU" Set the compute core count: ras plan modify Plan.p01.hdf "corecount = 8" Change several settings in one save: ras plan modify Plan.p01.hdf "solvertype = CPU" "corecount = 12" "usefbf = true" Switch to the diffusion-wave equation set, solved implicitly: ras plan modify Plan.p01.hdf "equationset = DWE" "timestepping = Implicit" Set the plan's own time window (quote dates; durations carry a unit): ras plan modify Plan.p01.hdf "timewindowmode = Plan" "starttime = '2024-03-01 06:00'" "computetimestep = 30s" "baseoutputinterval = 1h" Report the changes as JSON (for scripting): ras plan modify --format Json Plan.p01.hdf "corecount = 8"`
- `--grammar` List every field you can target in this plan (no changes made), then exit.
- `--case-sensitive` Make string comparisons in assignment values case-sensitive.
- `--dry-run` Report what would change without writing the file.
- `--format` Output format for the change report: Text (default), Json, or Properties (grep-friendly key=value). Errors always go to stderr as text, so stdout stays parseable.
- `--help` Display this help screen.
- `--version` Display version information.
- `plan (pos. 0)` — Plan file (*.h5). Optional with --grammar (omit it to print the default schema).
- `set (pos. 1)` — One or more assignments, each "<field> = value" (e.g. "corecount = 8"). The field names come from the plan's settings - run --grammar to list them. Enum and bool values are case-insensitive ("solvertype = gpu", "usefbf = true"). Not required with --grammar.

### `ras.exe plan prepare`
- `--if-exists` What to do when the output file already exists: 'force': delete the existing file and overwrite it. 'append': write to a numbered copy instead (e.g. 'output (3).h5') (Windows convention) 'error': report a message and refuse to overwrite. 'default' (default): error when you name the output explicitly, append when it's auto-derived.
- `--core-count` Overwrite core-count saved on the plan. 0 := Use plan value, -1 := Use all-available.
- `--processor` Override the plan's hardware target: 'CPU' or 'GPU'. GPU implies SWE + Explicit time-stepping; combining 'gpu' with '--equation dwe' or '--time-stepping implicit' is rejected currently.
- `--equation` Override the plan's equation set: 'SWE' (Shallow Water Equations) or 'DWE' (Diffusion Wave Equation). DWE only supports implicit time-stepping and CPU currently.
- `--time-stepping` Override the plan's time-stepping scheme: 'Explicit' or 'Implicit'. Only valid for the CPU SWE processor.
- `--name` Set the plan name embedded in the output result. If not provided, the source plan's name is kept.
- `--help` Display this help screen.
- `--version` Display version information.
- `source (pos. 0)` required — Required. Plan file (*.h5) to prepare.
- `output (pos. 1)` — Destination ready-to-run (*.r2r.h5) file. If not provided, writes to the plan's default ready-to-run location within the project.

### `ras.exe plan solve`
- `--print-graph` Print the solve dependency graph instead of running it.
- `--if-exists` What to do when the output file already exists: 'force': delete the existing file and overwrite it. 'append': write to a numbered copy instead (e.g. 'output (3).h5') (Windows convention) 'error': report a message and refuse to overwrite. 'default' (default): error when you name the output explicitly, append when it's auto-derived.
- `--core-count` Overwrite core-count saved on the plan. 0 := Use plan value, -1 := Use all-available.
- `--processor` Override the plan's hardware target: 'CPU' or 'GPU'. GPU implies SWE + Explicit time-stepping; combining 'gpu' with '--equation dwe' or '--time-stepping implicit' is rejected currently.
- `--equation` Override the plan's equation set: 'SWE' (Shallow Water Equations) or 'DWE' (Diffusion Wave Equation). DWE only supports implicit time-stepping and CPU currently.
- `--time-stepping` Override the plan's time-stepping scheme: 'Explicit' or 'Implicit'. Only valid for the CPU SWE processor.
- `--name` Set the plan name embedded in the output result. If not provided, the source plan's name is kept.
- `--help` Display this help screen.
- `--version` Display version information.
- `source (pos. 0)` required — Required. Plan file (*.h5) or ready-to-run result (*.r2r.h5) to solve. For a plan file, the parent project MUST exist with the expected directory structure, and is opened automatically for projection and associations. For a ready-to-run (*.r2r.h5) file, the project does not have to exist.
- `output (pos. 1)` — Destination result (*.h5) file. If not provided, output filename will be assumed based on the file type. For a plan file, the output filename will go to ../Results/[PlanName].h5, with an automatic count appended for file duplicates (e.g. '../Results/Plan (4).h5'). For a ready-to-run file, the output filename will be in the same directory, changing the 'r2r' for 'res' (e.g. './[BaseName].res.h5').

### `ras.exe prepare`
- `--if-exists` What to do when an output file already exists. See 'ras plan prepare' / 'ras project prepare' for the per-strategy details. 'force': delete the existing file and overwrite it. 'append': write to a numbered copy instead (e.g. 'output (3).r2r.h5'), Windows convention. 'error': report a message and refuse to overwrite. 'default' (default): error when you name the output explicitly, append when it's auto-derived.
- `--help` Display this help screen.
- `--version` Display version information.
- `source (pos. 0)` required — Required. Source to prepare. This goes through a multi-step resolution process. If the given source is a directory or project file (*.ras), forwards to 'ras project prepare' with default options. If the given source is a plan file (*.h5), forwards to 'ras plan prepare' with default options.
- `output (pos. 1)` — Output file or directory to write the prepared result. If unspecified, ready-to-run file(s) will be written to the locations specified in 'ras plan prepare' or 'ras project prepare'.

### `ras.exe project add`
- `-p, --project` Path to the target project (*.ras) or directory containing one. When omitted, the current working directory is searched.
- `-f, --file` Required. Source layer file (*.h5) to add. Layer type (Terrain/Geometry/Plan/Result/BoundaryCondition) is detected from the file contents.
- `--help` Display this help screen.
- `--version` Display version information.

### `ras.exe project add-new`
- `-p, --project` Path to the target project (*.ras) or directory containing one. When omitted, the current working directory is searched.
- `-t, --type` Required. Layer type to create. One of: terrain, geometry, plan, boundarycondition (alias 'bc'). Results are not user-creatable.
- `-n, --name` Required. Layer name. Becomes the filename basename (e.g. 'MyTerrain' -> '<project>/Terrains/MyTerrain.h5').
- `--help` Display this help screen.
- `--version` Display version information.

### `ras.exe project cleanup`
- `-f, --force` Skip per-file prompts, delete all candidates.
- `--dry-run` Show what would be deleted without actually deleting.
- `--set-policy` Save the policy to the project file without executing cleanup. Combine with --keep-all-days, --hourly-days, etc.
- `--keep-all-days` (Default: -1) Days to keep all backups (default: 7).
- `--hourly-days` (Default: -1) Days for hourly retention window (default: 30).
- `--daily-days` (Default: -1) Days for daily retention window (default: 365).
- `--verbose` Show detailed evaluation of every file explaining why it would or would not be cleaned.
- `--skip-auxiliary` Don't clean result auxiliary files (export directories).
- `--help` Display this help screen.
- `--version` Display version information.
- `project (pos. 0)` required — Required. Path to the project file (*.ras) or a directory containing one.

### `ras.exe project create`
Usage: `Create a project with an EPSG projection: ras project create --projection EPSG:900913 --output ./MyProject.ras Create a project from an ESRI .prj file: ras project create --projection ./projection.prj --output ./MyProject.ras`
- `-o, --output` Required. Destination project filename, e.g. './MyProject.ras'. The project name is the filename basename. Parent directory must exist.
- `-j, --projection` Required. Project projection. ESRI .prj filename, EPSG code ('EPSG:900913'), or PROJ string ('PROJ:+proj=aea ...').
- `--help` Display this help screen.
- `--version` Display version information.

### `ras.exe project explore`
- `--help` Display this help screen.
- `--version` Display version information.

### `ras.exe project info`
- `-p, --project` Path to a project (*.ras) or directory containing one. When omitted, the current working directory is searched.
- `--format` Output format: Text (default), Json, Markdown, or Properties (grep-friendly key=value).
- `--get` Print only the value(s) at a flattened key path (e.g. 'name' or 'plans[0].name'). Ignores --format.
- `--help` Display this help screen.
- `--version` Display version information.

### `ras.exe project prepare`
- `--if-exists` What to do when a plan's ready-to-run file already exists: 'force': delete the existing file and overwrite it. 'append': write to a numbered copy instead (e.g. 'Plan (1).r2r.h5'), Windows convention. 'error': report a message and skip that plan. 'default' (default): append a numbered copy (ready-to-run filenames are always auto-derived here).
- `--help` Display this help screen.
- `--version` Display version information.
- `source (pos. 0)` required — Required. Project file (*.ras) or directory containing one. Every plan in the project will be prepared.
- `output (pos. 1)` — Destination directory for the ready-to-run files. If unspecified, writes to each plan's default location in the project.

### `ras.exe project solve`
- `--if-exists` What to do when a plan's result file already exists: 'force': delete the existing file and overwrite it. 'append': write to a numbered copy instead (e.g. 'Plan (1).h5'), Windows convention. 'error': report a message and skip that plan. 'default' (default): append a numbered copy (plan result filenames are always auto-derived here).
- `--max-cores` Total CPU core budget the scheduler is allowed to use across all in-flight plans. Default (0) uses all logical processors.
- `--gpu-slots` Number of GPU plans allowed to run concurrently. Defaults to 1.
- `--print-graph` Print the solve dependency graph instead of running it.
- `--help` Display this help screen.
- `--version` Display version information.
- `source (pos. 0)` required — Required. Project file (*.ras) or directory containing one. Every plan in the project will be solved.
- `output (pos. 1)` — Destination directory for the solved result files. If unspecified, writes to the default location in the project.

### `ras.exe raster calc`
Usage: `Subtract Depth (with NoData checks): ras calc --equation "if(r1 == ndv and r2 == ndv, ndv, if(r1 == ndv, 0, r1) - if(r2 == ndv, 0, r2))" --input C:\Path\input1.tif C:\Path\input2.tif --output C:\Path\output.tif`
- `-i, --input` Required. Input raster file(s). Can be specified multiple times. Referenced as r1, r2, r3, etc. in the equation.
- `-o, --output` Required. Output filename. If file already exists, must be combined with --force argument.
- `-e, --equation` Required. Mathematical expression combining the rasters. Uses r1, r2, r3, etc. for inputs. Supports: +, -, *, /, ^, sqrt, abs, min, max, sin, cos, tan, log, pow, lerp, etc. Examples: '(r1 + r2) / 2' (average), 'max(r1, r2)', 'r1 - r2' (difference).
- `-f, --force` Force overwrite existing target file. Defaults to false.
- `--ndv-behavior` (Default: Allow) How to handle NoData values in the output. Allow: NoData propagates through calculations. WriteNDV: Write NoData as the output when any input is NoData. WriteZero: Write zero as the output when any input is NoData.
- `--help` Display this help screen.
- `--version` Display version information.

### `ras.exe raster explore`
- `-d, --driver` (Default: Default) Reading/editing stack: 'native' (our TiffBinaryReader, GeoTIFF only), 'gdal' (any GDAL format), or 'default' (native for a plain TIFF we parse, otherwise gdal).
- `--help` Display this help screen.
- `--version` Display version information.

### `ras.exe raster info`
- `-d, --driver` (Default: Default) Reading stack: 'native' (our TiffBinaryReader, GeoTIFF only), 'gdal' (any GDAL format), or 'default' (native for a plain TIFF we parse, otherwise gdal).
- `--format` Output format: Text (default), Json, Markdown, or Properties (grep-friendly key=value).
- `--get` Print only the value(s) at a flattened key path (e.g. 'width' or 'pyramidLevels[0].cellSize'). Ignores --format.
- `--help` Display this help screen.
- `--version` Display version information.

### `ras.exe raster render`
Usage: `Palette auto-ranged across the raster's own value distribution: ras raster render --palette Rainbow depth.tif Palette spread linearly over a fixed range: ras raster render --max 30 --min 0 --palette Rainbow depth.tif Palette with one explicit stop value per color (must match the palette's color count): ras raster render --palette Hazard --values 0,1,2,3,4,5,6,7,8,9,10 hazard.tif Discrete (classified) bands instead of a smooth gradient: ras raster render --discrete --palette NLCD landcover.tif Inline colors by name, spread over a range: ras raster render --colors blue|cyan|yellow|red --max 30 --min 0 depth.tif Inline colors as RGB and hex, placed at explicit values ('|' separates colors, ',' the channels): ras raster render --colors 0,0,255|#FFFFFF|255,0,0 --values 0,15,30 depth.tif Fully explicit value=color ramp: ras raster render --ramp 0=0,0,255|2.5=0,255,0|10=255,0,0 velocity.tif Ready-made named surface fill (carries its own colors and values): ras raster render --surface-fill Courant courant.tif Standalone hillshade (grayscale shaded relief from an elevation raster): ras raster render --hillshade terrain.tif Hypsometric tint: a color ramp with hillshade blended on top, custom light angle: ras raster render --altitude 30 --azimuth 315 --hillshade --max 1000 --min 0 --palette Terrain terrain.tif Transparent NoData with partial opacity (4-band RGBA): ras raster render --alpha 180 --max 10 --min 0 --palette Rainbow --rgba depth.tif depth.rgba.tif Resample to a coarser cell size, overwriting any existing output: ras raster render --cell-size 50 --force --palette Rainbow depth.tif preview.tif Preview the resolved ramp, range and projection without rendering: ras raster render --dry-run --max 50 --min 0 --palette Terrain depth.tif Browse the built-in palette names (no raster needed): ras raster render --list-palettes`
- `--if-exists` What to do when the output file already exists. 'force': delete the existing file and overwrite it. 'append': write to a numbered copy instead (e.g. 'output (3).tif'), Windows convention. 'error': report a message and refuse to overwrite. 'default' (default): error when you name the output explicitly, append when it's auto-derived.
- `-f, --force` Alias for '--if-exists force': overwrite the output file if it already exists.
- `--ramp` Explicit color ramp as 'V=R,G,B[,A]|V=R,G,B[,A]|...', e.g. '0=255,0,0|2.5=40,255,40|15=40,80,255' where 'V' is the value and R/G/B(/A) are 0-255 color channel components. Requires at least two entries.
- `--palette` Named color palette (e.g. 'Terrain', 'WaterSurface', 'Rainbow'). Combine with --values, with --min/--max, or with neither (auto-ranges from the raster histogram). See --list-palettes.
- `--colors` Inline color list, '|'-separated, used like a --palette (combine with --values, --min/--max, or neither). Each color is a System.Drawing name (e.g. 'SteelBlue'), an 'R,G,B' or 'R,G,B,A' triple (0-255), or a '#RRGGBB' hex. Sample: 'Red|0,128,0|0,0,255'. Mutually exclusive with --palette.
- `--surface-fill` Named, ready-made surface fill that carries both colors and values (e.g. 'Courant', 'Hazard', 'Precip Inches'). See --list-fills.
- `--values` Comma-separated stop values to pair with --palette, e.g. '0,1,2,5,10'. Provide exactly one value per palette color (see --list-palettes); use --min/--max to spread the palette linearly instead.
- `--min` Low value of a linear range spread across --palette. Use together with --max.
- `--max` High value of a linear range spread across --palette. Use together with --min.
- `--discrete` Render a stepped/classified ramp (flat color per band) instead of interpolating between stops.
- `--hillshade` Overlay shaded relief computed from the elevation surface. Works on its own (grayscale relief) or blended over a color ramp. Requires a floating-point (elevation) raster.
- `--azimuth` Hillshade light direction in degrees (0=N, 90=E, clockwise), default 315. Only with --hillshade.
- `--altitude` Hillshade light angle above the horizon in degrees (0-90), default 45. Only with --hillshade.
- `--z-factor` Hillshade vertical exaggeration, default 3. Higher values deepen the relief. Only with --hillshade.
- `--alpha` (Default: 255) Global opacity 0-255 applied to the ramp. Values below 255 imply --rgba.
- `--rgba` Write a 4-band RGBA image so NoData pixels stay transparent. Default is 3-band RGB (NoData collapses to black).
- `--interp` (Default: Nearest) Resampling interpolation: Nearest (default), Linear, etc. Only matters when --cell-size differs from the source resolution.
- `--cell-size` Output cell size (native units). Defaults to the source raster's resolution.
- `--use-gdal` Force the GDAL driver stack for reading the source raster.
- `--list-palettes` Print the available named palettes and exit.
- `--list-fills` Print the available named surface fills and exit.
- `--dry-run` Print the resolved settings (ramp, range, projection, output) without rendering.
- `--help` Display this help screen.
- `--version` Display version information.
- `source (pos. 0)` — Input raster file (e.g. a GeoTIFF). Any format our GDAL build reads. Not required when only listing palettes/fills.
- `output (pos. 1)` — Output image filename. The format is inferred from its extension: '.tif' (tiled GeoTIFF, the default) or '.png' (Windows-friendly, georeferenced via a sidecar world file). If not provided, defaults to a '.image.tif' file next to the source.

### `ras.exe raster translate`
- `-s, --source` Required. Input raster file.
- `-o, --output` Required. Output .tif filename. If file already exists, must be combined with --force argument.
- `-f, --force` Force overwrite existing target file. Defaults to false.
- `--use-gdal` Force use the GDAL driver stack for reading the raster file.
- `--help` Display this help screen.
- `--version` Display version information.

### `ras.exe result info`
- `--format` Output format: Text (default), Json, Markdown, or Properties (grep-friendly key=value).
- `--get` Print only the value(s) at a flattened key path (e.g. 'name' or 'outputBlocks[0].name'). Ignores --format.
- `--help` Display this help screen.
- `--version` Display version information.
- `result (pos. 0)` required — Required. Result file (*.h5).

### `ras.exe result map`
- `--type` Required. Type of map to create, e.g. 'depth', 'velocity', 'watersurface'
- `-p, --profile` Map profile to export. Required for single-profile map types (e.g. depth, velocity). Can be an integer index (0 to #Profiles-1, counted from the start) or a string name ('01JAN1900'). Also accepts 'max'/'min' (envelope), 'last' or '^N' (N-th from the end, so last := '^1' := 'last').
- `-f, --force` If set, automatically overwrite the OutputFilename. Defaults to false.
- `--no-infer` Do not open the result's parent project for projection or associations. When set, the terrain and output file must be provided explicitly (cell-size is still derived from the terrain).
- `--dry-run` Print the resolved inputs (terrain, output file, cell-size, projection, etc.) without generating the map.
- `--terrain` Terrain file to provide elevations. May be a HEC-RAS terrain (.h5) or a single .tif file. If not provided, inferred from the result's parent project. Required when there is no parent project or '--no-infer' is set.
- `--cell-size` Output file resolution (cell size). Value is in native (pre-projected) units. If not provided, defaults to the finest resolution found across the terrain's input files.
- `--projection` Output projection. Can be a filename (interpreted as an ESRI .prj), an EPSG code provided as a string, e.g. 'EPSG:900913', or a 'PROJ:' proj4 string.
- `--calculation` If set, will calculate a map over time for the given parameter at the mapping output timestepvalid calculations are "max," "duration-over," and "arrival-time."
- `--context` Context value for the calculation. For example, the threshold depth a duration calculation, or the threshold of depth at which arrival time should be calculated
- `--help` Display this help screen.
- `--version` Display version information.
- `result (pos. 0)` required — Required. RAS 2025 Result file (*.h5).
- `output (pos. 1)` — Destination filename. Should not exist. E.G. "./out.tif". If not provided, defaults to a name derived from the map type beneath the result's export folder.

### `ras.exe result postprocess`
- `--force` Delete any existing post-process file and recompute it from scratch. Without this, an existing post-process file that matches the result is left untouched.
- `--help` Display this help screen.
- `--version` Display version information.
- `result (pos. 0)` required — Required. Result file (*.h5) to post-process.

### `ras.exe s3 list-bucket`
- `-s, --server` S3 server. Defaults to https://s3.hecdev.net
- `--prefix` If set, only keys with this prefix are listed.
- `-u, --user` Username for S3 authentication. Optional - list attempts anonymous access if omitted.
- `-p, --password` Password for S3 authentication. Optional - list attempts anonymous access if omitted.
- `--format` Output format: Text (default, one entry per line), Json, or Markdown.
- `--delimiter` Delimiter between entries when --format is Text. Defaults to newline. Accepts escape sequences \n, \r, \t, \0.
- `--detailed` If set, emits per-key metadata (size, last-modified, etag, storage class) instead of just key names.
- `--help` Display this help screen.
- `--version` Display version information.
- `bucket (pos. 0)` required — Required. S3 bucket to list keys from.

### `ras.exe s3 list-buckets`
- `-s, --server` S3 server. Defaults to https://s3.hecdev.net
- `-u, --user` Username for S3 authentication. Optional - list attempts anonymous access if omitted.
- `-p, --password` Password for S3 authentication. Optional - list attempts anonymous access if omitted.
- `--help` Display this help screen.
- `--version` Display version information.

### `ras.exe s3 presign`
Usage: `Presign a GET URL for download: ras s3 presign --password secret --user alice s3://my-bucket/folder/file.h5 Presign a PUT URL for upload: ras s3 presign --password secret --user alice --verb put s3://my-bucket/uploads/new.h5`
- `-s, --server` (Default: https://s3.hecdev.net) S3 server. Defaults to https://s3.hecdev.net
- `-u, --user` Required. Username for S3 authentication.
- `-p, --password` Required. Password for S3 authentication.
- `--verb` (Default: get) HTTP verb for the presigned URL: get or put. (post is not supported by the AWS SDK's GetPreSignedURL API.)
- `--help` Display this help screen.
- `--version` Display version information.
- `s3-uri (pos. 0)` required — Required. Object in s3://bucket/key form, e.g. s3://my-bucket/folder/file.h5.

### `ras.exe s3 pull`
Usage: `Pull a public object: ras s3 pull s3://ras-public-examples/Muncie/manifest.json ./manifest.json Pull with credentials, overwriting any existing local file: ras s3 pull --force --password secret --user alice s3://private-bucket/data.h5 ./data.h5`
- `-s, --server` (Default: https://s3.hecdev.net) S3 server. Defaults to https://s3.hecdev.net
- `-u, --user` Username for S3 authentication. Optional - pull attempts anonymous access if omitted.
- `-p, --password` Password for S3 authentication. Optional - pull attempts anonymous access if omitted.
- `-f, --force` If set, overwrite the local file if it already exists.
- `--help` Display this help screen.
- `--version` Display version information.
- `source (pos. 0)` required — Required. Source object in s3://bucket/key form, e.g. s3://my-bucket/folder/file.h5.
- `destination (pos. 1)` required — Required. Local file path to write the downloaded object to.

### `ras.exe s3 push`
Usage: `Push a local file to a bucket: ras s3 push --password secret --user alice ./report.json s3://my-bucket/reports/today.json Push against a custom S3 server: ras s3 push --password secret --server https://s3.example.com --user alice ./data.h5 s3://my-bucket/data/data.h5`
- `-s, --server` (Default: https://s3.hecdev.net) S3 server. Defaults to https://s3.hecdev.net
- `-u, --user` Required. Username for S3 authentication.
- `-p, --password` Required. Password for S3 authentication.
- `--help` Display this help screen.
- `--version` Display version information.
- `source (pos. 0)` required — Required. Local file path to upload.
- `destination (pos. 1)` required — Required. Destination object in s3://bucket/key form, e.g. s3://my-bucket/reports/today.json.

### `ras.exe sample info`
- `--format` Output format: Text (default), Json, Markdown, or Properties (grep-friendly key=value).
- `--get` Print only the value(s) at a flattened key path (e.g. 'details.title' or 'files[0].filename'). Ignores --format.
- `--help` Display this help screen.
- `--version` Display version information.
- `title (pos. 0)` required — Required. Title of the sample project, as shown by 'ras sample list'. Matched case-insensitively. If multiple entries share the title, the most recently published is used.

### `ras.exe sample list`
- `-t, --tag` If set, only lists samples that include this tag (case-insensitive). May be specified multiple times; a sample matches if any tag matches.
- `--filter` Substring filter (case-insensitive) matched against the sample title and description. Combines with --tag.
- `--format` Output format: Text (default), Json, or Markdown.
- `--help` Display this help screen.
- `--version` Display version information.

### `ras.exe sample pull`
- `-m, --manifest` S3 manifest key to pull directly. Mutually exclusive with the positional title. Use this to pull a sample that isn't listed in the global manifest.
- `-s, --server` S3 server. Defaults to the sample's manifest entry (or https://s3.hecdev.net when used with --manifest).
- `-b, --bucket` S3 bucket. Defaults to the sample's manifest entry (or ras-public-examples when used with --manifest).
- `-u, --user` Username for S3 authentication. Public buckets do not require this.
- `-p, --password` Password for S3 authentication. Public buckets do not require this.
- `-c, --cache` Cache directory for downloaded blobs. Defaults to the standard RAS example-project cache.
- `-f, --force` If set, the destination directory will be wiped before pulling.
- `--dry-run` Walks through the pull without writing any files.
- `--help` Display this help screen.
- `--version` Display version information.
- `title (pos. 0)` — Title of the sample project to pull, as shown by 'ras sample list'. Mutually exclusive with --manifest.
- `directory (pos. 1)` — Destination directory. Must be empty (or pass --force to overwrite). When omitted, defaults to the 'DefaultProjectFolder' AppData override (if set) or '{MyDocuments}/RAS Projects', with a per-sample subfolder appended.

### `ras.exe sample push`
- `-d, --directory` Required. Project directory to scan and upload.
- `-s, --server` S3 server. Defaults to https://s3.hecdev.net
- `-b, --bucket` S3 bucket. Defaults to ras-public-examples
- `-u, --user` Required. Username for S3 authentication.
- `-p, --password` Required. Password for S3 authentication.
- `-g, --global` Global JSON manifest key to update. Defaults to 'globalmanifest.json'.
- `--skip-global` If set, files are uploaded but the global manifest is not updated. Useful for staging.
- `--minver` Minimum compatible software version. Expect SemVer 2.0, e.g. '2.0.0.412-beta2'.
- `--maxver` Maximum compatible software version. Expect SemVer 2.0, e.g. '2.0.0.412-beta2'.
- `--date` Publish date. Defaults to the current date/time.
- `--write-to` If set, also writes the generated manifest JSON to this local path. Works with --dry-run.
- `-f, --force` If set, any pre-existing remote manifest with the same key will be overwritten.
- `--dry-run` Builds the manifest and walks through the upload without writing any remote files.
- `--help` Display this help screen.
- `--version` Display version information.

### `ras.exe solve`
- `--if-exists` What to do when an output file already exists. See 'ras plan solve' / 'ras project solve' for the per-strategy details. 'force': delete the existing file and overwrite it. 'append': write to a numbered copy instead (e.g. 'output (3).h5'), Windows convention. 'error': report a message and refuse to overwrite. 'default' (default): error when you name the output explicitly, append when it's auto-derived.
- `--help` Display this help screen.
- `--version` Display version information.
- `source (pos. 0)` required — Required. Source to solve. This goes through a multi-step resolution process. If the given source is a directory or project file (*.ras), forwards to 'ras project solve' with default options. If the given source is a plan file (*.h5) or ready-to-run (*.r2r.h5) file, forwards to 'ras plan solve' with default options.
- `output (pos. 1)` — Output file or directory to write the solved result. If unspecified, solved result file(s) will be written to the locations specified in 'ras plan solve' or 'ras project solve'.

### `ras.exe terrain add`
- `--files` Required. Input raster files to add, ordered from high to low priority.
- `-r, --rounding` Desired rounding, as an integer base-2 value. 0 := no rounding, default.
- `--help` Display this help screen.
- `--version` Display version information.
- `terrain (pos. 0)` required — Required. Existing terrain file (*.h5) to add rasters to.

### `ras.exe terrain create`
Usage: `Valid - project mode, project discovered in current directory: ras terrain create --name MyTerrain Valid - project mode, explicit project path: ras terrain create --name MyTerrain --project ./Muncie.ras Valid - explicit mode, full path and projection: ras terrain create --projection EPSG:900913 --output ./MyTerrain.h5 Invalid - cannot combine --name with --output (name is derived from filename): ras terrain create --name MyTerrain --output ./MyTerrain.h5 Invalid - cannot combine --projection with --name or --project (project owns the projection): ras terrain create --projection EPSG:900913 --name MyTerrain --project ./Muncie.ras Invalid - --output requires --projection (no project context to inherit from): ras terrain create --output ./MyTerrain.h5`
- `-n, --name` Terrain name. Implies project mode: the new terrain is placed in the project's Terrains directory and inherits its projection.
- `-o, --output` Exact destination terrain filename (*.h5). Requires --projection.
- `-p, --project` Path to a project (*.ras) or a directory containing one. When omitted alongside --name, the current working directory is searched.
- `-j, --projection` Terrain projection. ESRI .prj filename, EPSG code ('EPSG:900913'), or PROJ string ('PROJ:+proj=aea +lat_0=23 +lat_1=29.5 +lat_2=42.5 +lon_0=-96'). Only valid alongside --output.
- `--help` Display this help screen.
- `--version` Display version information.

### `ras.exe terrain export`
- `--clip` Optional clip extent as 'minX,maxX,minY,maxY'. If omitted, exports a full copy.
- `--cellsize` Optional resample cell size when clipping. Ignored without --clip.
- `--help` Display this help screen.
- `--version` Display version information.
- `terrain (pos. 0)` required — Required. Source terrain file (*.h5).
- `output (pos. 1)` required — Required. Destination terrain filename (*.h5). Must not already exist.

### `ras.exe terrain info`
- `--format` Output format: Text (default), Json, Markdown, or Properties (grep-friendly key=value).
- `--get` Print only the value(s) at a flattened key path (e.g. 'projection' or 'layers[0].cellSize'). Ignores --format.
- `--verify-signature` Recompute the terrain signature (input file sizes and hashes) and verify it against the stored signature. Prints SUCCESS or FAILURE instead of the info dump.
- `--help` Display this help screen.
- `--version` Display version information.
- `terrain (pos. 0)` required — Required. Terrain file (*.h5) to inspect.

