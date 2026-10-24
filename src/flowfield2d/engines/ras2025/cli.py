"""Wrapper around the RAS 2025 command line (surface from the Phase 0 probe, ADR-0001).

Verbs and options follow `docs/probe/<build>/cli/cli_tree.md`. Every call that can overwrite
passes `--if-exists` explicitly. A timeout kills the whole process tree. Exit-code meanings beyond
zero/non-zero are not yet known (probe step E); any non-zero exit raises `RasCliError`.
"""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psutil

IF_EXISTS = ("default", "force", "append", "error")
PROCESSORS = ("CPU", "GPU")
EQUATIONS = ("SWE", "DWE")
TIME_STEPPING = ("Explicit", "Implicit")
LAYER_TYPES = ("terrain", "geometry", "plan", "boundarycondition", "bc")


@dataclass(frozen=True)
class CliResult:
    argv: list[str]
    exit_code: int | None
    stdout: str
    stderr: str
    duration_s: float
    timed_out: bool


class RasCliError(RuntimeError):
    def __init__(self, result: CliResult) -> None:
        why = "timed out" if result.timed_out else f"exit {result.exit_code}"
        super().__init__(f"ras {' '.join(result.argv)}: {why}\n{result.stderr[-2000:]}")
        self.result = result


def _choice(value: str, allowed: Sequence[str], name: str) -> str:
    if value not in allowed:
        raise ValueError(f"{name} must be one of {allowed}, not {value!r}")
    return value


def _kill_tree(pid: int) -> None:
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    procs = [*parent.children(recursive=True), parent]
    for p in procs:
        try:
            p.kill()
        except psutil.NoSuchProcess:
            pass
    psutil.wait_procs(procs, timeout=10)


class RasCli:
    def __init__(self, command: Sequence[str] | Path, timeout_s: float = 3600.0,
                 cwd: Path | None = None) -> None:
        self.command = [str(command)] if isinstance(command, Path) else [str(c) for c in command]
        self.timeout_s = timeout_s
        self.cwd = cwd

    def run(self, args: Sequence[str], timeout_s: float | None = None,
            check: bool = True) -> CliResult:
        argv = [str(a) for a in args]
        t0 = time.monotonic()
        proc = subprocess.Popen([*self.command, *argv], cwd=self.cwd, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True,
                                encoding="utf-8", errors="replace")
        timed_out = False
        try:
            out, err = proc.communicate(timeout=timeout_s or self.timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_tree(proc.pid)
            out, err = proc.communicate()
        res = CliResult(argv, None if timed_out else proc.returncode, out, err,
                        round(time.monotonic() - t0, 3), timed_out)
        if check and (timed_out or res.exit_code != 0):
            raise RasCliError(res)
        return res

    # --- inspection -----------------------------------------------------------------------
    def info_json(self, path: Path) -> Any:
        return json.loads(self.run(["info", str(path), "--format", "Json"]).stdout)

    # --- plans and compute ----------------------------------------------------------------
    def _compute_opts(self, if_exists: str, processor: str | None, core_count: int | None,
                      equation: str | None, time_stepping: str | None) -> list[str]:
        opts = ["--if-exists", _choice(if_exists, IF_EXISTS, "if_exists")]
        if processor is not None:
            opts += ["--processor", _choice(processor, PROCESSORS, "processor")]
        if core_count is not None:
            opts += ["--core-count", str(int(core_count))]
        if equation is not None:
            opts += ["--equation", _choice(equation, EQUATIONS, "equation")]
        if time_stepping is not None:
            opts += ["--time-stepping", _choice(time_stepping, TIME_STEPPING, "time_stepping")]
        return opts

    def plan_solve(self, plan: Path, output: Path | None = None, *, if_exists: str = "error",
                   processor: str | None = None, core_count: int | None = None,
                   equation: str | None = None, time_stepping: str | None = None,
                   timeout_s: float | None = None) -> CliResult:
        opts = self._compute_opts(if_exists, processor, core_count, equation, time_stepping)
        args = ["plan", "solve", str(plan), *([str(output)] if output else []), *opts]
        return self.run(args, timeout_s=timeout_s)

    def plan_prepare(self, plan: Path, output: Path | None = None, *, if_exists: str = "error",
                     processor: str | None = None, core_count: int | None = None,
                     equation: str | None = None, time_stepping: str | None = None) -> CliResult:
        opts = self._compute_opts(if_exists, processor, core_count, equation, time_stepping)
        return self.run(["plan", "prepare", str(plan), *([str(output)] if output else []), *opts])

    def plan_modify(self, plan: Path, assignments: Mapping[str, str],
                    dry_run: bool = False) -> Any:
        sets = [f"{k} = {v}" for k, v in assignments.items()]
        args = ["plan", "modify", str(plan), *sets, *(["--dry-run"] if dry_run else []),
                "--format", "Json"]
        return json.loads(self.run(args).stdout)

    # --- model assembly -------------------------------------------------------------------
    def generate_mesh(self, geometry: Path) -> CliResult:
        return self.run(["geometry", "generate-mesh", str(geometry)])

    def terrain_create(self, project: Path, name: str) -> CliResult:
        return self.run(["terrain", "create", "-n", name, "-p", str(project)])

    def terrain_add(self, terrain: Path, files: Sequence[Path]) -> CliResult:
        return self.run(["terrain", "add", str(terrain), "--files", *map(str, files)])

    def project_add_new(self, project: Path, layer_type: str, name: str) -> CliResult:
        t = _choice(layer_type, LAYER_TYPES, "layer_type")
        return self.run(["project", "add-new", "-p", str(project), "-t", t, "-n", name])

    def clone(self, source: Path, output: Path, force: bool = False) -> CliResult:
        return self.run(["clone", "-s", str(source), "-o", str(output),
                         *(["-f"] if force else [])])

    # --- results --------------------------------------------------------------------------
    def result_map(self, result: Path, output: Path, *, map_type: str,
                   profile: str | None = None, calculation: str | None = None,
                   cell_size: float | None = None, terrain: Path | None = None,
                   force: bool = False) -> CliResult:
        args = ["result", "map", str(result), str(output), "--type", map_type]
        if profile is not None:
            args += ["-p", profile]
        if calculation is not None:
            args += ["--calculation", calculation]
        if cell_size is not None:
            args += ["--cell-size", repr(float(cell_size))]
        if terrain is not None:
            args += ["--terrain", str(terrain)]
        if force:
            args += ["-f"]
        return self.run(args)

    def result_postprocess(self, result: Path, force: bool = False) -> CliResult:
        return self.run(["result", "postprocess", str(result), *(["--force"] if force else [])])
