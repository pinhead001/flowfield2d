"""Stand-in for the RAS 2025 CLI in engine tests (synthetic; no RAS needed).

Records argv to $FAKE_RAS_LOG (one JSON line per call). Behaviour by verb:
  info <path> --format Json      -> prints {"type": "plan", "path": <path>}
  plan modify ... --format Json  -> prints {"changes": [...assignments...]}
  plan solve <plan> [...]        -> exit 0 with progress; FAKE_RAS_FAIL=1 -> exit 3 + stderr
  sleep                           -> spawns a child and sleeps (for timeout / tree-kill tests)
  anything else                   -> exit 0
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

args = sys.argv[1:]
log = os.environ.get("FAKE_RAS_LOG")
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps(args) + "\n")

if args[:1] == ["info"]:
    print(json.dumps({"type": "plan", "path": args[1]}))
elif args[:2] == ["plan", "modify"]:
    sets = [a for a in args[3:] if "=" in a]
    print(json.dumps({"changes": sets}))
elif args[:2] == ["plan", "solve"]:
    if os.environ.get("FAKE_RAS_FAIL"):
        sys.stderr.write("Error: boundary condition 'Outflow' normal depth slope must be > 0\n")
        sys.exit(3)
    plan = Path(args[2])
    if plan.parent.name == "Plans":  # like RAS 2025: <project>/Results/<plan> (Result).h5
        import h5py
        import numpy as np

        out = plan.parent.parent / "Results" / f"{plan.stem} (Result).h5"
        out.parent.mkdir(exist_ok=True)
        with h5py.File(out, "w") as f:
            cs = f.create_group("/Results/Compute Summary")
            cs.attrs["Success"] = np.uint8(int(os.environ.get("FAKE_RAS_SUCCESS", "1")))
            cs.attrs["Solver"] = np.bytes_("CPU_Explicit")
            cs.attrs["Compute Log"] = np.bytes_("fake log")
    print("progress 100%")
elif args[:2] == ["plan", "prepare"]:          # plan prepare <plan> <out.r2r.h5> [...]
    if os.environ.get("FAKE_RAS_FAIL_PREPARE"):
        sys.stderr.write("Error: prepare failed\n")
        sys.exit(5)
    Path(args[3]).write_bytes(b"r2r for " + args[2].encode())
    print("OK: prepared")
elif args[:2] == ["result", "map"]:            # result map <result> <out.tif> --type T -p P
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    out = Path(args[3])
    kind = args[args.index("--type") + 1]
    value = {"depth": 1.5, "velocity": 2.0, "watersurface": 101.5}.get(kind, 0.0)
    profile = args[args.index("-p") + 1] if "-p" in args else "max"
    with rasterio.open(out, "w", driver="GTiff", width=4, height=3, count=1, dtype="float32",
                       transform=from_origin(0.0, 3.0, 1.0, 1.0), nodata=-9999.0) as ds:
        ds.write(np.full((3, 4), value, dtype="float32"), 1)
        ds.update_tags(profile=profile, kind=kind)
elif args[:1] == ["sleep"]:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    print(child.pid, flush=True)
    time.sleep(60)
