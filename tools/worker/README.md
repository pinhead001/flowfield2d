# Remote RAS workers (ready-to-run jobs over a shared folder)

Any Windows machine with the pinned HEC-RAS 2025 build can solve jobs prepared elsewhere: the pipeline host
runs `ras plan prepare` into a standalone `*.r2r.h5` (it carries mesh, property tables, BCs and plan settings), a
worker runs `ras plan solve` on it and returns the result file. No project, terrain or Python on the worker.

1. Install the pinned RAS build. Export the pin as JSON and verify:
   `powershell -ExecutionPolicy Bypass -File verify_ras.ps1 -RasDir <ras dir> -Pin ras_pin.json`
2. Mount the queue share (for example `\\HOST\share\ras_queue`).
3. Start the worker (one per machine): `worker.ps1 -Queue <share> -RasDir <ras dir> -Slots 3 -Processor CPU
   -CoresPerJob 8`, or `-Processor GPU -Slots 1` to use the GPU solver.
4. The host picks results up from `done\` (and `failed\`); determinism against a host solve is checked once per
   new machine.

Queue protocol: the host writes `pending\<job>.r2r.h5` then an empty `<job>.r2r.h5.ready` marker; a worker claims
a job by moving it into `running\<host>\<job>\` (an atomic move on one share, so two workers never take the same
job), and moves the folder to `done\` or `failed\` with `result.h5`, `solve.log` and `status.json`.
