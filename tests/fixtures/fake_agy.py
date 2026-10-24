"""Stand-in for the delegate CLI in runner tests (synthetic; no network).

Prompt lines of the form `WRITE <path>=<text>` create files in cwd.
FAKE_AGY_MODE=quota exits 1 with a quota-style error; =error exits 1 plainly.
Every invocation's prompt is appended to $FAKE_AGY_LOG when set.
"""

import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
prompt = args[args.index("-p") + 1]
log = os.environ.get("FAKE_AGY_LOG")
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps({"argv": args, "prompt": prompt}) + "\n")
mode = os.environ.get("FAKE_AGY_MODE", "")
if mode in ("quota", "error"):
    if mode == "quota":
        sys.stderr.write("Error 429: RESOURCE_EXHAUSTED quota exceeded\n")
    print(json.dumps({"status": "ERROR", "response": "", "usage": {"total_tokens": 0},
                      "duration_seconds": 0.1}))
    sys.exit(1)
for line in prompt.splitlines():
    if line.startswith("WRITE "):
        name, _, text = line[6:].partition("=")
        Path(name).write_text(text, encoding="utf-8")
print(json.dumps({"status": "SUCCESS", "response": "done", "usage": {"total_tokens": 42},
                  "duration_seconds": 1.5}))
