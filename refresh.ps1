# Pre-lecture data refresh: re-download all KOSPI/KOSDAQ daily bars, recompute
# indicators/scores, then commit & push docs/data. GitHub Pages rebuilds automatically.
#   Manual run:  powershell -NoProfile -ExecutionPolicy Bypass -File .\refresh.ps1
#   A run log is written to last_refresh.log next to this script.
# NOTE: keep this file ASCII-only -- Windows PowerShell 5.1 mis-decodes non-ASCII
#       .ps1 files saved without a BOM, which breaks parsing.
$ErrorActionPreference = 'Continue'
Set-Location $PSScriptRoot
Start-Transcript -Path (Join-Path $PSScriptRoot 'last_refresh.log') -Force | Out-Null
$ok = $false
try {
    Write-Host "=== data refresh started: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ==="

    Write-Host "[1/2] building data (all stocks, takes a few minutes)..."
    python tools\build_data.py
    if ($LASTEXITCODE -ne 0) { throw "build_data.py failed (exit $LASTEXITCODE) - not pushing." }

    $today = Get-Date -Format 'yyyy-MM-dd'
    Write-Host "[2/2] git commit and push..."
    git add -A docs/data
    git commit -m "data $today"
    git push
    if ($LASTEXITCODE -ne 0) { throw "git push failed (exit $LASTEXITCODE)." }

    Write-Host "=== done: $(Get-Date -Format 'HH:mm:ss') - live at https://atti18.github.io/xz_stock/ in ~1-2 min ==="
    $ok = $true
}
catch {
    Write-Host "!!! FAILED: $_"
}
finally {
    Stop-Transcript | Out-Null
}
if (-not $ok) { exit 1 }
