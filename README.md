# 시흥XZ청년단 · 거래량 퀀트 투자 강의 페이지

소모임 주식강의용 모바일 웹페이지. "주변 얘기·거시 뉴스" 대신 **거래량으로 세력 매집 흔적을 잡는 퀀트 방식**을 소개하고,
각자 폰으로 직접 만져볼 수 있는 **전 종목(KOSPI/KOSDAQ) 스크리너**를 제공한다.

- 강의 현장에 PC가 없어 모바일 우선으로 만들었다.
- GitHub Pages(정적 호스팅)에 올린다 → 서버가 없으므로 **시세·지표·점수는 미리 빌드해 JSON으로 번들**한다.
- 사용 지표: OBV(누적거래량), Chaikin Oscillator, Slow Stochastic, "거래량 급증 + 주가 횡보" 패턴, 소형주 가중(유통주식비율 자리).

> ⚠️ 교육용입니다. 특정 종목 매수·매도 권유가 아니며, 과거 거래량 패턴이 미래 수익을 보장하지 않습니다.

## 구조
```
docs/                        ← GitHub Pages 배포 폴더 (/docs)
  index.html  style.css  app.js  .nojekyll
  lib/lightweight-charts...    차트 라이브러리(벤더링)
  data/
    meta.json                  데이터 기준일·종목 수·지표 파라미터·가중치
    screener.json              전 종목: 종목명/코드/시장/현재가/점수/지표 서브점수/신호 배지
    stocks/<코드>.json          종목별 일봉 OHLCV + OBV/Chaikin/Stochastic 시계열 (상세 차트용, 탭하면 로드)
tools/
  build_data.py                시세 다운로드 → 지표·점수 계산 → docs/data/*.json 생성
  requirements.txt
```

## 강의 전에 데이터 갱신하기
```bash
pip install -r tools/requirements.txt
python tools/build_data.py            # 전 종목, 약 1년치 일봉. 네트워크 상태에 따라 수 분 소요
git add docs/data && git commit -m "data 2026-05-12" && git push
```
또는 위 세 줄을 한 번에 하는 스크립트:
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\refresh.ps1
```
빠른 확인용(일부 종목만):
```bash
python tools/build_data.py --limit 40 --days 150
```
옵션: `--limit N`(처리 종목 수 제한) · `--days N`(받을 과거 일수, 기본 400) · `--workers N`(동시 다운로드 스레드, 기본 10).

데이터 출처는 FinanceDataReader(네이버 일봉)다. 원래 계획은 pykrx였으나 KRX 전종목 스냅샷 엔드포인트가 불안정해 바꿨다.
**유통주식비율**은 아직 데이터 소스를 연결하지 않았고, 그 자리를 "시가총액 하위 종목 가산(`smallcap`)"으로 임시 대체한다.
연결하려면 `tools/build_data.py`의 `shares_map`/소형주 점수 계산 부분을 유통주식수 기반으로 바꾸면 된다.

> 매 갱신마다 `docs/data/`(특히 `stocks/*.json` 수천 개)가 다시 커밋되어 저장소가 커진다. 신경 쓰이면 데이터 커밋 히스토리를 가끔 squash 하면 된다.

## 로컬에서 미리보기
```bash
cd docs
python -m http.server 8000
# 브라우저에서 http://localhost:8000  (개발자도구 모바일 뷰 또는 실제 폰으로 확인)
```

## GitHub Pages 배포
1. 이 폴더를 git 저장소로 만들고 GitHub에 푸시한다.
   ```bash
   git init && git add . && git commit -m "init"
   git remote add origin <당신의-repo-URL>
   git push -u origin main
   ```
2. GitHub 저장소 → **Settings → Pages** → Source를 **"Deploy from a branch"**, Branch `main`, 폴더 `/docs` 로 지정하고 저장.
3. 수 분 뒤 `https://<아이디>.github.io/<repo>/` 에서 열린다.
4. 강의 때는 이 주소를 단축 링크/QR로 만들어 청년단에 공유 → 각자 폰에서 접속.

(나중에 더 빠른 한국 엣지가 필요하면 같은 `docs/` 폴더 그대로 Cloudflare Pages에도 올릴 수 있다 — 빌드 명령 없음, 출력 폴더 `docs`.)

## 스크리너 점수 규칙 요약
종목마다 위 다섯 신호로 0~100점씩 매기고(대부분 전 종목 중 백분위 순위), `meta.json`의 가중치로 평균낸 게 **세력 유입 점수**다.
규칙·가중치·파라미터는 페이지의 "점수 규칙" 섹션에 그대로 노출된다. 점수가 높다는 건 "오늘 거래량 신호가 상대적으로 강하다"는 뜻일 뿐 수익 보장이 아니다.
