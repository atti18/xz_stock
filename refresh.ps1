# 강의 전 데이터 갱신 — KOSPI/KOSDAQ 전 종목 일봉을 다시 받아 지표·점수 계산 후
# docs/data 를 커밋·푸시한다. GitHub Pages 가 자동으로 다시 빌드된다.
#   수동 실행:  powershell -NoProfile -ExecutionPolicy Bypass -File .\refresh.ps1
#   (실행 기록은 last_refresh.log 에 남는다.)
Set-Location $PSScriptRoot
Start-Transcript -Path (Join-Path $PSScriptRoot 'last_refresh.log') -Force | Out-Null
try {
    Write-Host "=== 데이터 갱신 시작: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ==="

    Write-Host "[1/2] 데이터 빌드 (전 종목, 수 분 소요)…"
    python tools\build_data.py
    if ($LASTEXITCODE -ne 0) { throw "build_data.py 실패 (exit $LASTEXITCODE) — 푸시하지 않고 중단." }

    $today = Get-Date -Format 'yyyy-MM-dd'
    Write-Host "[2/2] git 커밋·푸시…"
    git add -A docs/data
    git commit -m "data $today"
    git push
    if ($LASTEXITCODE -ne 0) { throw "git push 실패 (exit $LASTEXITCODE)." }

    Write-Host "=== 완료: $(Get-Date -Format 'HH:mm:ss') — 약 1~2분 뒤 https://atti18.github.io/xz_stock/ 반영 ==="
}
catch {
    Write-Host "!!! 실패: $_"
    Stop-Transcript | Out-Null
    exit 1
}
Stop-Transcript | Out-Null
