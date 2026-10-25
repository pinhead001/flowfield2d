# Remote RAS worker: solves ready-to-run (*.r2r.h5) jobs from a shared queue folder. No Python needed.
#
# Queue layout (on a share every machine can reach):
#   <Queue>\pending\<job>.r2r.h5        jobs waiting (written by the pipeline host; a <job>.r2r.h5.ready
#                                        marker file appears when the copy is complete)
#   <Queue>\running\<host>\<job>\        claimed by a worker (atomic move of the job file)
#   <Queue>\done\<job>\                  result.h5, solve.log, status.json  (ok/failed, host, times)
#   <Queue>\failed\<job>\                same, for failed solves
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File worker.ps1 -Queue \\HOST\share\ras_queue `
#       -RasDir "C:\Programs\HECRAS_2025\v0.1.0.5048-dev" -Slots 3 -Processor CPU -CoresPerJob 8
# Stop with Ctrl+C; running solves finish on their own and are picked up as done on the next start.
param(
    [Parameter(Mandatory = $true)][string]$Queue,
    [Parameter(Mandatory = $true)][string]$RasDir,
    [int]$Slots = 2,
    [ValidateSet("CPU", "GPU")][string]$Processor = "CPU",
    [int]$CoresPerJob = 0,
    [int]$PollSeconds = 15
)
$ErrorActionPreference = "Stop"
$hostName = $env:COMPUTERNAME
$ras = Join-Path $RasDir "ras.exe"
foreach ($d in "pending", "running\$hostName", "done", "failed") {
    New-Item -ItemType Directory -Force -Path (Join-Path $Queue $d) | Out-Null
}
$jobs = @{}   # job name -> @{ proc; started (UTC); own = started by this worker (exit code known) }

# A solve counts as ok only with a result file and RAS's completion line (exit codes are not
# available for solves adopted after a worker restart).
function Solve-Ok([string]$dir, $exitCode) {
    $log = Join-Path $dir "solve.log"
    $completed = (Test-Path $log) -and (Select-String -Path $log -Pattern "Computations completed" -Quiet)
    $exitOk = ($null -eq $exitCode) -or ($exitCode -eq 0)
    return $exitOk -and $completed -and (Test-Path (Join-Path $dir "result.h5"))
}

function Finish-Job([string]$name, $job) {
    $dir = Join-Path $Queue "running\$hostName\$name"
    $exitCode = $null
    if ($job.own) { $exitCode = $job.proc.ExitCode }
    $ok = Solve-Ok $dir $exitCode
    $status = @{ job = $name; host = $hostName; processor = $Processor; exit = $exitCode;
                 ok = $ok; started = $job.started.ToString("o");
                 finished = (Get-Date).ToUniversalTime().ToString("o") }
    $status | ConvertTo-Json | Set-Content (Join-Path $dir "status.json")
    $target = Join-Path $Queue ($(if ($ok) { "done" } else { "failed" }))
    Move-Item $dir (Join-Path $target $name) -Force
    Write-Host "$(Get-Date -Format s) $name -> $(if ($ok) {'done'} else {'FAILED'})"
}

# Restart: jobs this host left in running\ are adopted if their ras.exe still runs, else finished.
foreach ($d in Get-ChildItem (Join-Path $Queue "running\$hostName") -Directory) {
    $proc = $null
    $pidFile = Join-Path $d.FullName "pid.txt"
    if (Test-Path $pidFile) {
        $proc = Get-Process -Id ([int](Get-Content $pidFile)) -ErrorAction SilentlyContinue |
                Where-Object { $_.ProcessName -eq "ras" }
    }
    $job = @{ proc = $proc; started = $d.CreationTimeUtc; own = $false }
    if ($proc) { $jobs[$d.Name] = $job; Write-Host "$(Get-Date -Format s) $($d.Name) adopted (pid $($proc.Id))" }
    else { Finish-Job $d.Name $job }
}

Write-Host "worker ${hostName}: $Slots slot(s), $Processor, queue $Queue"
while ($true) {
    foreach ($name in @($jobs.Keys)) {
        if ($jobs[$name].proc.HasExited) { Finish-Job $name $jobs[$name]; $jobs.Remove($name) }
    }
    while ($jobs.Count -lt $Slots) {
        $next = Get-ChildItem (Join-Path $Queue "pending") -Filter "*.r2r.h5" |
                Where-Object { Test-Path ($_.FullName + ".ready") } | Sort-Object Name | Select-Object -First 1
        if (-not $next) { break }
        $name = $next.Name -replace "\.r2r\.h5$", ""
        $dir = Join-Path $Queue "running\$hostName\$name"
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        try { Move-Item $next.FullName (Join-Path $dir "job.r2r.h5") -ErrorAction Stop }
        catch { Remove-Item $dir -Recurse -Force; continue }        # another worker claimed it first
        Remove-Item ($next.FullName + ".ready") -ErrorAction SilentlyContinue
        $solveArgs = @("plan", "solve", (Join-Path $dir "job.r2r.h5"), (Join-Path $dir "result.h5"),
                  "--processor", $Processor, "--if-exists", "force")
        if ($CoresPerJob -gt 0) { $solveArgs += @("--core-count", "$CoresPerJob") }
        $p = Start-Process -FilePath $ras -ArgumentList $solveArgs -PassThru -NoNewWindow `
             -RedirectStandardOutput (Join-Path $dir "solve.log") -RedirectStandardError (Join-Path $dir "solve.err")
        $null = $p.Handle   # cache the handle, or ExitCode reads as null after exit
        Set-Content (Join-Path $dir "pid.txt") $p.Id
        $jobs[$name] = @{ proc = $p; started = (Get-Date).ToUniversalTime(); own = $true }
        Write-Host "$(Get-Date -Format s) $name started (pid $($p.Id))"
    }
    Start-Sleep -Seconds $PollSeconds
}
