# Verify that a HEC-RAS 2025 install matches a pinned build (file SHA-256 hashes).
# Usage:  powershell -ExecutionPolicy Bypass -File verify_ras.ps1 -RasDir "C:\Programs\HECRAS_2025\v0.1.0.5048-dev" -Pin ras_pin.json
# ras_pin.json: {"build": "...", "sha256": {"ras.exe": "<hex>", ...}}  (exported from the consumer's pin file)
param(
    [Parameter(Mandatory = $true)][string]$RasDir,
    [Parameter(Mandatory = $true)][string]$Pin
)
$pin = Get-Content $Pin -Raw | ConvertFrom-Json
$bad = 0
foreach ($p in $pin.sha256.PSObject.Properties) {
    $f = Join-Path $RasDir $p.Name
    if (-not (Test-Path $f)) { Write-Host "MISSING  $($p.Name)"; $bad++; continue }
    $h = (Get-FileHash -Algorithm SHA256 $f).Hash.ToLower()
    if ($h -ne $p.Value.ToLower()) { Write-Host "MISMATCH $($p.Name)"; $bad++ }
    else { Write-Host "ok       $($p.Name)" }
}
if ($bad -gt 0) { Write-Host "FAILED: $bad file(s) differ from build $($pin.build)"; exit 1 }
Write-Host "OK: install matches build $($pin.build)"
