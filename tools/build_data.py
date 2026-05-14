#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
시흥XZ청년단 주식강의 — 거래량 기반 '세력 유입' 스크리너 데이터 빌더.

KOSPI/KOSDAQ 전 종목의 최근 약 1년 일봉(FinanceDataReader → 네이버)을 받아
OBV / Chaikin Oscillator / Slow Stochastic / 거래량 급증·주가 횡보 지표를 계산하고
'세력 유입 점수'를 매겨 docs/data/*.json 으로 저장한다.

GitHub Pages는 정적이라 강의 전에 이 스크립트를 한 번 돌려 결과 JSON을 커밋하면 된다.

    pip install -r tools/requirements.txt
    python tools/build_data.py                        # 전 종목 (수 분 소요)
    python tools/build_data.py --limit 40 --days 150  # 빠른 테스트
    git add docs/data && git commit -m "data YYYY-MM-DD" && git push

원래 계획은 pykrx였으나 KRX 전종목 스냅샷 엔드포인트가 불안정해 FinanceDataReader(네이버)로 받는다.
유통주식비율 데이터는 아직 연결하지 않았고, 그 자리는 '소형주(시가총액 하위) 가산'으로 대체한다.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
import FinanceDataReader as fdr

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "docs" / "data"
STOCKS_DIR = DATA_DIR / "stocks"

# ── 강의용 기본 파라미터 (meta.json 으로도 내보내 화면 '스코어링 규칙'에 노출) ──
PARAMS = {
    # 단기 점수(우리 "오르기 직전 타이밍"용)
    "obv_slope_window": 20,           # OBV 추세를 잴 최근 거래일 수
    "chaikin_fast": 3,
    "chaikin_slow": 10,
    "stoch_period": 14,
    "stoch_smooth": 3,                # Slow %K, %D 평활 일수
    "vol_recent": 5,                  # '최근 평균 거래량' 구간
    "vol_base": 60,                   # '기준 평균 거래량' 구간
    "flat_window": 20,                # '주가 횡보' 판단 구간
    # 장기 매집 점수(1년짜리 누적 매집 추세)
    "chaikin_long_slow": 220,         # 장기 Chaikin Oscillator 의 긴 EMA 기간(약 1년)
    "obv_slope_long_window": 220,     # 장기 OBV 기울기 측정 구간
    "min_long_days": 280,             # 장기 점수 산정에 필요한 최소 거래일 수
    # 공통
    "detail_days": 180,               # 종목 상세 차트에 담을 거래일 수
    "min_days": 40,                   # 데이터가 이보다 적은 종목은 제외
    "illiquid_amount": 200_000_000,   # 최근 20거래일 중앙 거래대금이 이 미만이면 저유동성
    "weights": {"obv": 25, "chaikin": 20, "volsurge": 30, "stoch": 15, "smallcap": 10},
    "long_weights": {"chaikin_long": 50, "obv_long": 50},   # 장기 점수 = 두 항목 평균
}

BADGE_LABELS = {
    "obv_up": "OBV 상승추세",
    "chaikin_pos": "CO 양(+)",
    "chaikin_turn": "CO 양전환",
    "vol_surge": "거래량 급증",
    "quiet_accum": "거래량↑·주가 횡보",
    "stoch_turn": "스토캐스틱 저점반등",
    "smallcap": "소형주",
}

MARKETS = {"KOSPI", "KOSDAQ", "KOSDAQ GLOBAL"}


# ─────────────────────────── 지표 계산 ───────────────────────────
def _ema(arr: np.ndarray, span: int) -> np.ndarray:
    return pd.Series(arr).ewm(span=span, adjust=False).mean().to_numpy()


def compute_indicators(h, l, c, v):
    """OBV, Chaikin Oscillator(단기), Chaikin Oscillator(장기), Slow %K, Slow %D 시계열을 반환."""
    # OBV: 종가가 오른 날 +거래량, 내린 날 -거래량 누적
    dirn = np.sign(np.diff(c, prepend=c[0]))
    obv = np.cumsum(dirn * v)

    # ADL(누적/분산선) → Chaikin Oscillator = EMA_fast(ADL) - EMA_slow(ADL)
    rng = h - l
    with np.errstate(invalid="ignore", divide="ignore"):
        clv = np.where(rng > 0, ((c - l) - (h - c)) / rng, 0.0)
    adl = np.cumsum(clv * v)
    fast_ema = _ema(adl, PARAMS["chaikin_fast"])
    chaikin = fast_ema - _ema(adl, PARAMS["chaikin_slow"])              # 단기(3,10)
    chaikin_long = fast_ema - _ema(adl, PARAMS["chaikin_long_slow"])    # 장기(3,220) — 1년짜리 매집 추세

    # Slow Stochastic
    p, s = PARAMS["stoch_period"], PARAMS["stoch_smooth"]
    ll = pd.Series(l).rolling(p).min().to_numpy()
    hh = pd.Series(h).rolling(p).max().to_numpy()
    denom = hh - ll
    with np.errstate(invalid="ignore", divide="ignore"):
        fast_k = np.where(denom > 0, 100.0 * (c - ll) / denom, np.nan)
    slow_k = pd.Series(fast_k).rolling(s).mean().to_numpy()
    slow_d = pd.Series(slow_k).rolling(s).mean().to_numpy()
    return obv, chaikin, chaikin_long, slow_k, slow_d


def extract_signals(c, v, obv, chaikin, chaikin_long, slow_k, slow_d):
    """종목별 '원시 신호'와 배지 플래그. 정규화(백분위)는 전 종목 모아 나중에 수행."""
    n = len(c)

    # OBV 추세(단기): 최근 구간 OBV의 일당 기울기를 평균 거래량으로 나눈 무차원 값
    w = min(PARAMS["obv_slope_window"], n)
    slope = float(np.polyfit(np.arange(w), obv[-w:], 1)[0]) if w >= 2 else 0.0
    avgvol = max(float(v[-w:].mean()), 1.0)
    obv_signal = slope / avgvol

    # Chaikin Oscillator(단기 3,10): 최신값을 평균 거래량으로 정규화 + 양전환 여부
    chk_last = chaikin[-1]
    chk_signal = (chk_last / avgvol) if math.isfinite(chk_last) else 0.0
    chaikin_pos = bool(math.isfinite(chk_last) and chk_last > 0)
    prev_window = chaikin[-6:-1]
    chaikin_turn = bool(chaikin_pos and len(prev_window) and np.nanmin(prev_window) <= 0)

    # 장기 매집 신호: Chaikin(3,220) 최신값 + OBV 220일 기울기. 데이터가 충분한 종목만.
    long_w = PARAMS["obv_slope_long_window"]
    long_avail = bool(n >= PARAMS["min_long_days"])
    if long_avail:
        avgvol_long = max(float(v[-long_w:].mean()), 1.0)
        chk_long_last = chaikin_long[-1]
        chk_long_signal = (chk_long_last / avgvol_long) if math.isfinite(chk_long_last) else 0.0
        long_slope = float(np.polyfit(np.arange(long_w), obv[-long_w:], 1)[0])
        obv_long_signal = long_slope / avgvol_long
    else:
        chk_long_signal = 0.0
        obv_long_signal = 0.0

    # 거래량 급증 + 주가 횡보: 최근 평균거래량 / 기준 평균거래량, 단 가격이 이미 크게 움직였으면 감점
    r = min(PARAMS["vol_recent"], n)
    b = min(PARAMS["vol_base"], max(n - r, 1))
    recent_vol = float(v[-r:].mean())
    base_vol = float(v[-(r + b):-r].mean()) if n > r else recent_vol
    surge_ratio = recent_vol / max(base_vol, 1.0)
    fw = min(PARAMS["flat_window"], n)
    seg = c[-fw:]
    range_pct = float((seg.max() - seg.min()) / max(seg.mean(), 1.0))
    volsurge_signal = surge_ratio * math.exp(-1.5 * range_pct)
    vol_surge = bool(surge_ratio >= 1.5)
    quiet_accum = bool(vol_surge and range_pct < 0.12)

    # Slow Stochastic: 저점권(%K 낮음) + 반등 시작(%K > %D, %K 상승) 이면 가산
    k_now = slow_k[-1]
    k_prev = slow_k[-2] if n >= 2 else k_now
    d_now = slow_d[-1]
    valid = all(math.isfinite(x) for x in (k_now, k_prev, d_now))
    turning = bool(valid and k_now > d_now and k_now > k_prev)
    base_stoch = (100.0 - k_now) if valid else 50.0
    stoch_subscore = float(np.clip(base_stoch * (1.0 if turning else 0.4), 0.0, 100.0))
    stoch_turn = bool(valid and k_now < 35 and turning)

    return {
        "obv_signal": obv_signal,
        "chk_signal": chk_signal,
        "volsurge_signal": volsurge_signal,
        "surge_ratio": round(surge_ratio, 2),
        "range_pct": round(range_pct, 4),
        "stoch_subscore": stoch_subscore,
        "obv_long_signal": obv_long_signal,
        "chk_long_signal": chk_long_signal,
        "long_avail": long_avail,
        "badges": {
            "obv_up": bool(obv_signal > 0),
            "chaikin_pos": chaikin_pos,
            "chaikin_turn": chaikin_turn,
            "vol_surge": vol_surge,
            "quiet_accum": quiet_accum,
            "stoch_turn": stoch_turn,
        },
    }


# ─────────────────────────── 데이터 수집 ───────────────────────────
def load_universe(limit: int | None) -> pd.DataFrame:
    listing = fdr.StockListing("KRX")
    listing = listing[listing["Market"].isin(MARKETS)].copy()
    listing["Market"] = listing["Market"].replace({"KOSDAQ GLOBAL": "KOSDAQ"})
    listing = listing[["Code", "Name", "Market", "Stocks"]].dropna(subset=["Code", "Name"])
    # 스팩(기업인수목적회사)은 현금 껍데기라 '매집' 해석이 무의미 → 제외
    listing = listing[~listing["Name"].str.contains("스팩|SPAC", case=False, na=False)]
    listing = listing.drop_duplicates(subset="Code").reset_index(drop=True)
    if limit:
        listing = listing.head(limit).reset_index(drop=True)
    return listing


def fetch_history(code: str, start: str) -> pd.DataFrame | None:
    for attempt in range(3):
        try:
            df = fdr.DataReader(code, start)
            if df is not None and len(df):
                return df
        except Exception:
            pass
        time.sleep(0.4 * (attempt + 1))
    return None


# ─────────────────────────── 출력 보조 ───────────────────────────
def _ints(a) -> list[int]:
    return [int(round(x)) if math.isfinite(x) else 0 for x in a]


def _r1(a) -> list[float]:
    return [round(float(x), 1) if math.isfinite(x) else None for x in a]


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


# ─────────────────────────── 메인 ───────────────────────────
def build(limit: int | None, days: int, workers: int) -> None:
    start_date = (dt.date.today() - dt.timedelta(days=days)).strftime("%Y-%m-%d")
    print(f"[1/4] 종목 목록 수집 …")
    uni = load_universe(limit)
    shares_map = dict(zip(uni["Code"], uni["Stocks"]))
    name_map = dict(zip(uni["Code"], uni["Name"]))
    market_map = dict(zip(uni["Code"], uni["Market"]))
    codes = list(uni["Code"])
    print(f"      대상 {len(codes)}종목, 시세 시작일 {start_date}")

    print(f"[2/4] 일봉 다운로드 (workers={workers}) …")
    processed: list[dict] = []
    failed = 0
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fetch_history, code, start_date): code for code in codes}
        for fut in as_completed(futs):
            code = futs[fut]
            done += 1
            if done % 100 == 0 or done == len(codes):
                print(f"      {done}/{len(codes)} (실패 {failed})")
            df = fut.result()
            if df is None or len(df) < PARAMS["min_days"]:
                failed += 1
                continue
            df = df.dropna(subset=["Open", "High", "Low", "Close", "Volume"])
            if len(df) < PARAMS["min_days"]:
                failed += 1
                continue
            o = df["Open"].to_numpy(dtype=float)
            h = df["High"].to_numpy(dtype=float)
            l = df["Low"].to_numpy(dtype=float)
            c = df["Close"].to_numpy(dtype=float)
            v = df["Volume"].to_numpy(dtype=float)
            dates = [d.strftime("%Y-%m-%d") for d in df.index]
            amount = c * v  # 거래대금 근사 (네이버 일봉엔 없음)

            obv, chaikin, chaikin_long, slow_k, slow_d = compute_indicators(h, l, c, v)
            sig = extract_signals(c, v, obv, chaikin, chaikin_long, slow_k, slow_d)

            last_close = float(c[-1])
            shares = shares_map.get(code)
            mcap = int(last_close * shares) if shares and math.isfinite(shares) else None
            tail = min(20, len(amount))
            illiquid = bool(np.median(amount[-tail:]) < PARAMS["illiquid_amount"])
            change_pct = round((c[-1] / c[-2] - 1.0) * 100.0, 2) if len(c) >= 2 else 0.0

            n = len(c)
            dd = min(PARAMS["detail_days"], n)
            processed.append({
                "code": code,
                "name": name_map.get(code, code),
                "market": market_map.get(code, ""),
                "close": int(round(last_close)),
                "change": change_pct,
                "amount": int(amount[-1]),
                "mcap": mcap,
                "illiquid": illiquid,
                "last_date": dates[-1],
                "sig": sig,
                "detail": {
                    "dates": dates[-dd:],
                    "o": _ints(o[-dd:]), "h": _ints(h[-dd:]), "l": _ints(l[-dd:]),
                    "c": _ints(c[-dd:]), "v": _ints(v[-dd:]),
                    "obv": _ints(obv[-dd:]), "chaikin": _ints(chaikin[-dd:]),
                    "stochK": _r1(slow_k[-dd:]), "stochD": _r1(slow_d[-dd:]),
                },
            })

    if not processed:
        sys.exit("처리된 종목이 없습니다. 네트워크/소스 상태를 확인하세요.")

    print(f"[3/4] 점수 산정 ({len(processed)}종목, 실패 {failed}) …")
    # 단기 신호들을 전 종목 백분위(0~100)로 정규화
    obv_pct = (pd.Series([p["sig"]["obv_signal"] for p in processed]).rank(pct=True) * 100).to_numpy()
    chk_pct = (pd.Series([p["sig"]["chk_signal"] for p in processed]).rank(pct=True) * 100).to_numpy()
    vsg_pct = (pd.Series([p["sig"]["volsurge_signal"] for p in processed]).rank(pct=True) * 100).to_numpy()
    # 소형주: 시가총액이 작을수록 높게 (없으면 중립 50)
    mcaps = pd.Series([p["mcap"] if p["mcap"] else np.nan for p in processed])
    small_pct = ((1.0 - mcaps.rank(pct=True)) * 100).fillna(50.0).to_numpy()
    # 장기 신호: 데이터가 충분한 종목들끼리만 백분위 산정
    chk_long_raw = pd.Series([(p["sig"]["chk_long_signal"] if p["sig"]["long_avail"] else np.nan) for p in processed])
    obv_long_raw = pd.Series([(p["sig"]["obv_long_signal"] if p["sig"]["long_avail"] else np.nan) for p in processed])
    chk_long_pct = (chk_long_raw.rank(pct=True) * 100).to_numpy()
    obv_long_pct = (obv_long_raw.rank(pct=True) * 100).to_numpy()

    w = PARAMS["weights"]
    wsum = sum(w.values())
    lw = PARAMS["long_weights"]
    lwsum = sum(lw.values())
    base_date = max(p["last_date"] for p in processed)

    screener = []
    for i, p in enumerate(processed):
        sub = {
            "obv": int(round(obv_pct[i])),
            "chaikin": int(round(chk_pct[i])),
            "volsurge": int(round(vsg_pct[i])),
            "stoch": int(round(p["sig"]["stoch_subscore"])),
            "smallcap": int(round(small_pct[i])),
        }
        score = int(round(sum(sub[k] * w[k] for k in w) / wsum))
        badges = [k for k, on in p["sig"]["badges"].items() if on]

        # 장기 매집 점수 (Chaikin 3,220 + OBV 220일 기울기 평균)
        if p["sig"]["long_avail"] and math.isfinite(chk_long_pct[i]) and math.isfinite(obv_long_pct[i]):
            long_sub = {"chaikin_long": int(round(chk_long_pct[i])),
                        "obv_long":     int(round(obv_long_pct[i]))}
            long_score = int(round(sum(long_sub[k] * lw[k] for k in lw) / lwsum))
            long_avail = True
        else:
            long_sub = {"chaikin_long": None, "obv_long": None}
            long_score = None
            long_avail = False

        screener.append({
            "code": p["code"], "name": p["name"], "market": p["market"],
            "close": p["close"], "change": p["change"], "amount": p["amount"],
            "mcap": p["mcap"], "illiquid": p["illiquid"],
            "score": score, "sub": sub, "badges": badges,
            "longScore": long_score, "longSub": long_sub, "longAvail": long_avail,
            "surgeRatio": p["sig"]["surge_ratio"], "rangePct": p["sig"]["range_pct"],
            "lastDate": p["last_date"],
        })
        # 종목 상세 파일
        det = p["detail"]
        det.update({"code": p["code"], "name": p["name"], "market": p["market"],
                    "score": score, "sub": sub, "badges": badges,
                    "longScore": long_score, "longSub": long_sub, "longAvail": long_avail,
                    "close": p["close"], "change": p["change"]})
        write_json(STOCKS_DIR / f"{p['code']}.json", det)

    screener.sort(key=lambda r: r["score"], reverse=True)

    print(f"[4/4] JSON 저장 …")
    write_json(DATA_DIR / "screener.json", screener)
    long_count = sum(1 for r in screener if r["longAvail"])
    write_json(DATA_DIR / "meta.json", {
        "baseDate": base_date,
        "generatedAt": dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(timespec="seconds"),
        "stockCount": len(screener),
        "failedCount": failed,
        "longAvailCount": long_count,
        "params": {k: PARAMS[k] for k in (
            "obv_slope_window", "chaikin_fast", "chaikin_slow", "stoch_period", "stoch_smooth",
            "vol_recent", "vol_base", "flat_window", "illiquid_amount",
            "chaikin_long_slow", "obv_slope_long_window", "min_long_days")},
        "weights": PARAMS["weights"],
        "longWeights": PARAMS["long_weights"],
        "badgeLabels": BADGE_LABELS,
        "dataSource": "FinanceDataReader (네이버 일봉)",
        "note": "유통주식비율 데이터 미연결 — 'smallcap'(시가총액 하위 가산)으로 대체 중. 교육용 자료이며 투자 권유가 아닙니다.",
    })
    print(f"완료: {len(screener)}종목(장기점수 {long_count}종목) → {DATA_DIR}  (기준일 {base_date})")


def main() -> None:
    ap = argparse.ArgumentParser(description="거래량 기반 세력 유입 스크리너 데이터 빌드")
    ap.add_argument("--limit", type=int, default=None, help="처리할 종목 수 제한 (테스트용)")
    ap.add_argument("--days", type=int, default=900, help="다운로드할 과거 일수(달력일). 기본 900 (~600 거래일 — Chaikin(3,220)·OBV 220일 안정화 위해)")
    ap.add_argument("--workers", type=int, default=10, help="동시 다운로드 스레드 수")
    args = ap.parse_args()
    build(limit=args.limit, days=max(args.days, 90), workers=max(args.workers, 1))


if __name__ == "__main__":
    main()
