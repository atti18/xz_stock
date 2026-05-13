# 강의 전 데이터 갱신 — KOSPI/KOSDAQ 전 종목 일봉 다시 받아 지표·점수 계산 후
# docs/data 를 커밋·푸시한다. GitHub Pages 가 자동으로 다시 빌드된다.
#   사용:  powershell -NoProfile -ExecutionPolicy Bypass -File .\refresh.ps1
$ErrorActionPreference = 'Continue'
Set-Location $PSScriptRoot

Write-Host "[1/2] 데이터 빌드 (전 종목, 수 분 소요)…"
python tools\build_data.py
if ($LASTEXITCODE -ne 0) { Write-Error "build_data.py 실패 (exit $LASTEXITCODE). 푸시하지 않고 중단."; exit 1 }

$today = Get-Date -Format 'yyyy-MM-dd'
Write-Host "[2/2] git 커밋·푸시…"
git add -A docs/data
git commit -m "data $today"
git push
if ($LASTEXITCODE -ne 0) { Write-Error "git push 실패 (exit $LASTEXITCODE)."; exit 1 }

Write-Host "완료 — 약 1~2분 뒤 https://atti18.github.io/xz_stock/ 에 반영됩니다."
