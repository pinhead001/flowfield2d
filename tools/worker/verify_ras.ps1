# Verify that a HEC-RAS 2025 install matches a pinned build (file SHA-256 hashes).
# Usage:  powershell -ExecutionPolicy Bypass -File verify_ras.ps1 -RasDir "C:\Programs\HECRAS_2025\v0.1.0.5048-dev" -Pin ras_pin.json
# ras_pin.json: {"build": "...", "sha256": {"ras.exe": "<hex>", ...}}  (exported from the consumer's pin file)
param(
    [Parameter(Mandatory = $true)][string]$RasDir,
    [Parameter(Mandatory = $true)][string]$Pin
)
# Not $pin: PowerShell names are case-insensitive, so that would be the [string] parameter $Pin and
# the parsed object would silently become an empty string (no files checked, false OK).
$pinData = Get-Content $Pin -Raw | ConvertFrom-Json
$entries = @($pinData.sha256.PSObject.Properties)
if (-not $pinData.build -or $entries.Count -eq 0) { Write-Host "FAILED: no build or hashes in $Pin"; exit 1 }
$bad = 0
foreach ($p in $entries) {
    $f = Join-Path $RasDir $p.Name
    if (-not (Test-Path $f)) { Write-Host "MISSING  $($p.Name)"; $bad++; continue }
    $h = (Get-FileHash -Algorithm SHA256 $f).Hash.ToLower()
    if ($h -ne $p.Value.ToLower()) { Write-Host "MISMATCH $($p.Name)"; $bad++ }
    else { Write-Host "ok       $($p.Name)" }
}
if ($bad -gt 0) { Write-Host "FAILED: $bad file(s) differ from build $($pinData.build)"; exit 1 }
Write-Host "OK: install matches build $($pinData.build) ($($entries.Count) files)"
