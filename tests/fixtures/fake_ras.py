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
    print("progress 100%")
elif args[:1] == ["sleep"]:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    print(child.pid, flush=True)
    time.sleep(60)
