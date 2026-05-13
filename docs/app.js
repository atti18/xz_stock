/* 시흥XZ청년단 거래량 퀀트 — 스크리너 프런트엔드 (정적, 의존성: lightweight-charts) */
'use strict';

const LIST_LIMIT = 120;
const SUB_KEYS = ['obv', 'chaikin', 'volsurge', 'stoch', 'smallcap'];
const SUB_LABELS = { obv: 'OBV 추세', chaikin: '차이킨 오실레이터', volsurge: '거래량 급증·주가 횡보', stoch: '스토캐스틱 슬로우', smallcap: '소형주 가중' };
const MARKET_LABEL = { KOSPI: '코스피', KOSDAQ: '코스닥' };

const state = {
  meta: null,
  rows: [],            // 원본 종목 배열
  weights: null,       // 현재 가중치
  defaultWeights: null,
  charts: [],          // 상세 화면에서 만든 차트 (닫을 때 정리)
};

// ───────────────────────── 유틸 ─────────────────────────
const $ = (sel, root = document) => root.querySelector(sel);
const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };
const fmtInt = n => (n == null ? '—' : Number(n).toLocaleString('ko-KR'));
function fmtMoney(n) {
  if (n == null || !isFinite(n)) return '—';
  if (n >= 1e12) return (n / 1e12).toFixed(2) + '조원';
  if (n >= 1e8) return Math.round(n / 1e8).toLocaleString('ko-KR') + '억원';
  return Math.round(n).toLocaleString('ko-KR') + '원';
}
function changeSpan(c) {
  const cls = c > 0 ? 'up' : c < 0 ? 'down' : 'flat';
  const s = (c > 0 ? '+' : '') + Number(c).toFixed(2) + '%';
  return `<span class="${cls}">${s}</span>`;
}
function badgeLabel(key) { return (state.meta && state.meta.badgeLabels && state.meta.badgeLabels[key]) || key; }

function scoreFor(row, w) {
  let num = 0, den = 0;
  for (const k of SUB_KEYS) { num += (row.sub[k] || 0) * (w[k] || 0); den += (w[k] || 0); }
  return den ? Math.round(num / den) : 0;
}

// ───────────────────────── 초기화 ─────────────────────────
async function init() {
  try {
    const [meta, rows] = await Promise.all([
      fetch('data/meta.json').then(r => r.json()),
      fetch('data/screener.json').then(r => r.json()),
    ]);
    state.meta = meta;
    state.rows = rows;
    state.defaultWeights = Object.assign({}, meta.weights);
    state.weights = Object.assign({}, meta.weights);
  } catch (e) {
    $('#dataInfo').textContent = '데이터를 불러오지 못했습니다. tools/build_data.py 로 docs/data 를 먼저 만들어 주세요.';
    $('#stockList').innerHTML = '<li class="empty">데이터 없음 — 빌드 스크립트를 실행하세요.</li>';
    return;
  }

  $('#dataInfo').textContent = `데이터 기준일 ${state.meta.baseDate} · ${fmtInt(state.meta.stockCount)}종목 · 출처 ${state.meta.dataSource || 'KRX'}`;
  $('#footMeta').textContent = `생성: ${state.meta.generatedAt || ''} · ${state.meta.note || ''}`;
  renderWeightTable();
  renderWeightSliders();
  wireControls();
  renderList();
}

function renderWeightTable() {
  const w = state.defaultWeights, sum = SUB_KEYS.reduce((a, k) => a + (w[k] || 0), 0);
  let html = '<thead><tr><th>신호</th><th class="num">기본 가중치</th><th>무엇을 보나</th></tr></thead><tbody>';
  const desc = {
    obv: '오른 날 거래량 + / 내린 날 거래량 − 누적의 추세 (전 종목 백분위)',
    chaikin: 'ADL의 단기·중기 평균 차이 = 최근 매집 압력 (전 종목 백분위)',
    volsurge: '최근 평균거래량 ÷ 기준 평균거래량, 단 주가가 이미 움직였으면 감점 (전 종목 백분위)',
    stoch: '%K가 과매도권(20 아래)에서 %D를 위로 뚫고 올라오는가 (0~100 직접 점수)',
    smallcap: '시가총액이 작을수록 가산 — 유통주식비율 데이터 연결 전 임시 (전 종목 백분위)',
  };
  for (const k of SUB_KEYS) html += `<tr><td>${SUB_LABELS[k]}</td><td class="num">${w[k]} / ${sum}</td><td class="muted">${desc[k]}</td></tr>`;
  html += '</tbody>';
  $('#weightTable').innerHTML = html;
  const p = state.meta.params || {};
  $('#paramNote').textContent = `기본 파라미터 — OBV 추세 ${p.obv_slope_window}일, 차이킨 EMA(${p.chaikin_fast},${p.chaikin_slow}), 스토캐스틱(${p.stoch_period},${p.stoch_smooth}), 거래량 비교 최근 ${p.vol_recent}일 vs 기준 ${p.vol_base}일, 횡보 판단 ${p.flat_window}일, 저유동성 기준 일거래대금 ${fmtMoney(p.illiquid_amount)}.`;
}

function renderWeightSliders() {
  const box = $('#weightSliders');
  box.innerHTML = '';
  for (const k of SUB_KEYS) {
    const row = el('div', 'wrow');
    row.innerHTML = `<label for="w_${k}">${SUB_LABELS[k]}</label><input type="range" id="w_${k}" min="0" max="50" step="5" value="${state.weights[k]}"><span class="wval" id="wv_${k}">${state.weights[k]}</span>`;
    box.appendChild(row);
    row.querySelector('input').addEventListener('input', e => {
      state.weights[k] = Number(e.target.value);
      $('#wv_' + k).textContent = e.target.value;
      renderList();
    });
  }
}

function wireControls() {
  $('#fMarket').addEventListener('change', renderList);
  $('#fHideIlliq').addEventListener('change', renderList);
  $('#fSearch').addEventListener('input', renderList);
  const ms = $('#fMinScore');
  ms.addEventListener('input', () => { $('#fMinScoreOut').textContent = ms.value; renderList(); });
  $('#weightReset').addEventListener('click', () => {
    state.weights = Object.assign({}, state.defaultWeights);
    for (const k of SUB_KEYS) { $('#w_' + k).value = state.weights[k]; $('#wv_' + k).textContent = state.weights[k]; }
    renderList();
  });
  $('#detailClose').addEventListener('click', closeDetail);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDetail(); });
  window.addEventListener('resize', () => { for (const c of state.charts) { try { c.applyOptions({ width: c.__host.clientWidth }); } catch (_) {} } });
}

// ───────────────────────── 리스트 렌더 ─────────────────────────
function renderList() {
  const market = $('#fMarket').value;
  const minScore = Number($('#fMinScore').value);
  const hideIlliq = $('#fHideIlliq').checked;
  const q = $('#fSearch').value.trim().toLowerCase();

  let list = state.rows.map(r => Object.assign({}, r, { _score: scoreFor(r, state.weights) }));
  if (market) list = list.filter(r => r.market === market);
  if (hideIlliq) list = list.filter(r => !r.illiquid);
  if (minScore > 0) list = list.filter(r => r._score >= minScore);
  if (q) list = list.filter(r => r.name.toLowerCase().includes(q) || r.code.includes(q));
  list.sort((a, b) => b._score - a._score || (b.surgeRatio || 0) - (a.surgeRatio || 0));

  const total = list.length;
  const shown = q ? list : list.slice(0, LIST_LIMIT);
  const ul = $('#stockList');
  ul.innerHTML = '';
  if (shown.length === 0) { ul.innerHTML = '<li class="empty">조건에 맞는 종목이 없습니다.</li>'; $('#listMore').textContent = ''; $('#screenerMeta').textContent = ''; return; }
  shown.forEach((r, i) => ul.appendChild(rowEl(r, i + 1)));
  $('#screenerMeta').innerHTML = `조건 충족 <b>${fmtInt(total)}</b>종목 · 세력 유입 점수 높은 순`;
  $('#listMore').textContent = (!q && total > shown.length) ? `상위 ${shown.length}개만 표시 중입니다. 검색으로 특정 종목을 찾아보세요.` : '';
}

function rowEl(r, rank) {
  const li = el('li', 'srow');
  li.tabIndex = 0;
  const badges = (r.badges || []).slice(0, 4).map(b => `<span class="badge b-${b}">${badgeLabel(b)}</span>`).join('');
  const illiq = r.illiquid ? ' <span class="illiq-tag">· 저유동성</span>' : '';
  li.innerHTML = `
    <div class="rank">${rank}</div>
    <div class="nm">${escapeHtml(r.name)}
      <div class="sub1">${r.code} · ${MARKET_LABEL[r.market] || r.market}${illiq}</div>
      <div class="badges">${badges}</div>
    </div>
    <div class="right">
      <div class="score">${r._score}</div><div class="scorelbl">SCORE</div>
      <div class="price">${fmtInt(r.close)}원 ${changeSpan(r.change)}</div>
    </div>
    <div class="scorebar" style="grid-column:1/-1"><i style="width:${Math.max(0, Math.min(100, r._score))}%"></i></div>`;
  const open = () => openDetail(r.code);
  li.addEventListener('click', open);
  li.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } });
  return li;
}

function escapeHtml(s) { return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }

// ───────────────────────── 상세 화면 ─────────────────────────
async function openDetail(code) {
  const ov = $('#detailOverlay'), body = $('#detailBody');
  $('#detailTitle').textContent = code;
  body.innerHTML = '<p class="muted">불러오는 중…</p>';
  ov.classList.remove('hidden');
  document.body.classList.add('noscroll');
  let d;
  try { d = await fetch(`data/stocks/${code}.json`).then(r => { if (!r.ok) throw new Error(); return r.json(); }); }
  catch (e) { body.innerHTML = '<p class="muted">이 종목의 상세 데이터를 찾지 못했습니다.</p>'; return; }
  renderDetail(d);
}

function closeDetail() {
  $('#detailOverlay').classList.add('hidden');
  document.body.classList.remove('noscroll');
  for (const c of state.charts) { try { c.remove(); } catch (_) {} }
  state.charts = [];
  $('#detailBody').innerHTML = '';
}

function renderDetail(d) {
  const w = state.weights, score = scoreFor(d, w);
  $('#detailTitle').innerHTML = `${escapeHtml(d.name)} <span class="muted" style="font-weight:500">${d.code} · ${MARKET_LABEL[d.market] || d.market}</span>`;
  const body = $('#detailBody');
  body.innerHTML = '';

  const head = el('div');
  head.innerHTML = `<div class="reading"><b>세력 유입 점수 ${score}</b> · 현재가 ${fmtInt(d.close)}원 ${changeSpan(d.change)} · 기준일 ${d.dates[d.dates.length - 1]}<br>${makeReading(d)}</div>`;
  const bd = el('div', 'detail-badges', (d.badges || []).map(b => `<span class="badge b-${b}">${badgeLabel(b)}</span>`).join(''));
  head.appendChild(bd);
  body.appendChild(head);

  // 1) 캔들 + 거래량
  body.appendChild(el('h4', null, '① 일봉 + 거래량 — 거래량이 늘어난 자리(빨강↑/파랑↓)를 보세요'));
  const cPrice = mkChart(body, 200);
  const candle = cPrice.addCandlestickSeries({ upColor: '#ff5a5f', wickUpColor: '#ff5a5f', downColor: '#4d8df0', wickDownColor: '#4d8df0', borderVisible: false });
  candle.setData(d.dates.map((t, i) => ({ time: t, open: d.o[i], high: d.h[i], low: d.l[i], close: d.c[i] })));
  const vol = cPrice.addHistogramSeries({ priceFormat: { type: 'volume' }, priceScaleId: 'vol' });
  cPrice.priceScale('vol').applyOptions({ scaleMargins: { top: 0.78, bottom: 0 } });
  vol.setData(d.dates.map((t, i) => ({ time: t, value: d.v[i], color: d.c[i] >= d.o[i] ? 'rgba(255,90,95,.45)' : 'rgba(77,141,240,.45)' })));
  cPrice.timeScale().fitContent();

  // 2) OBV
  body.appendChild(el('h4', null, '② OBV(누적거래량) — 우상향이면 "조용히 사 모으는 손"'));
  const cObv = mkChart(body, 130, true);
  const obvLine = cObv.addLineSeries({ color: '#8a5cf6', lineWidth: 2, priceLineVisible: false });
  obvLine.setData(d.dates.map((t, i) => ({ time: t, value: d.obv[i] })));
  cObv.timeScale().fitContent();

  // 3) Chaikin Oscillator
  body.appendChild(el('h4', null, '③ 차이킨 오실레이터 — 0 위(초록)면 매집 압력 ↑'));
  const cChk = mkChart(body, 130, true);
  const chk = cChk.addBaselineSeries({ baseValue: { type: 'price', price: 0 }, lineWidth: 2, priceLineVisible: false,
    topLineColor: '#38c172', topFillColor1: 'rgba(56,193,114,.35)', topFillColor2: 'rgba(56,193,114,.04)',
    bottomLineColor: '#ff5a5f', bottomFillColor1: 'rgba(255,90,95,.04)', bottomFillColor2: 'rgba(255,90,95,.35)' });
  chk.setData(d.dates.map((t, i) => ({ time: t, value: d.chaikin[i] })));
  cChk.timeScale().fitContent();

  // 4) Slow Stochastic
  body.appendChild(el('h4', null, '④ 스토캐스틱 슬로우 — 20 아래에서 보라(%K)가 주황(%D)을 위로 뚫으면 반등 타이밍'));
  body.appendChild(el('div', 'legend', '<span><i style="background:#8a5cf6"></i>%K</span><span><i style="background:#f0a500"></i>%D</span><span><i style="background:#2c3450"></i>20 / 80 기준선</span>'));
  const cSt = mkChart(body, 140, true);
  const kS = cSt.addLineSeries({ color: '#8a5cf6', lineWidth: 2, priceLineVisible: false });
  const dS = cSt.addLineSeries({ color: '#f0a500', lineWidth: 1, priceLineVisible: false });
  kS.setData(d.dates.map((t, i) => ({ time: t, value: d.stochK[i] })).filter(p => p.value != null));
  dS.setData(d.dates.map((t, i) => ({ time: t, value: d.stochD[i] })).filter(p => p.value != null));
  for (const lvl of [20, 80]) kS.createPriceLine({ price: lvl, color: '#2c3450', lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed, axisLabelVisible: true });
  cSt.timeScale().fitContent();

  // 점수 분해
  body.appendChild(el('h4', null, '이 점수는 이렇게 나왔습니다 (현재 가중치 기준)'));
  const ul = el('ul', 'sublist');
  for (const k of SUB_KEYS) {
    const v = d.sub[k] || 0;
    const li = el('li');
    li.innerHTML = `<span class="lbl">${SUB_LABELS[k]}<br><span class="muted" style="font-size:.72rem">가중치 ${w[k]}</span></span><span class="scorebar"><i style="width:${v}%"></i></span><span class="val">${v}</span>`;
    ul.appendChild(li);
  }
  body.appendChild(ul);
  body.appendChild(el('p', 'disclaimer', '교육용 화면입니다. 특정 종목 매수·매도 권유가 아니며, 과거 거래량 패턴이 미래를 보장하지 않습니다.'));
  body.scrollTop = 0;
}

function mkChart(parent, height, sm) {
  const host = el('div', sm ? 'chart sm' : 'chart');
  host.style.height = height + 'px';
  parent.appendChild(host);
  const chart = LightweightCharts.createChart(host, {
    width: host.clientWidth, height: height,
    layout: { background: { color: 'transparent' }, textColor: '#97a0bd', fontSize: 11 },
    grid: { vertLines: { color: '#222a40' }, horzLines: { color: '#222a40' } },
    rightPriceScale: { borderColor: '#2c3450' },
    timeScale: { borderColor: '#2c3450', timeVisible: false, fixLeftEdge: true, fixRightEdge: true },
    crosshair: { mode: LightweightCharts.CrosshairMode.Magnet },
    handleScale: { axisPressedMouseMove: false }, handleScroll: { vertTouchDrag: false },
  });
  chart.__host = host;
  state.charts.push(chart);
  return chart;
}

function makeReading(d) {
  const b = new Set(d.badges || []);
  const parts = [];
  if (b.has('obv_up') && b.has('chaikin_pos')) parts.push('OBV가 우상향이고 차이킨도 양(+)이라 — 사 모으는 손이 보이는 편입니다.');
  else if (b.has('obv_up')) parts.push('OBV가 우상향이라 — 조용히 매수 우위가 쌓이는 모습입니다.');
  if (b.has('chaikin_turn')) parts.push('차이킨이 음(−)→양(+)으로 막 전환됐습니다 — 매집 압력이 붙기 시작.');
  if (b.has('quiet_accum')) parts.push('거래량은 늘었는데 주가는 아직 횡보 중 — "오르기 직전" 패턴에 가깝습니다.');
  else if (b.has('vol_surge')) parts.push('최근 거래량이 평소보다 크게 늘었습니다.');
  if (b.has('stoch_turn')) parts.push('스토캐스틱이 과매도권에서 막 반등을 시작했습니다 — 타이밍상 바닥권.');
  if (b.has('smallcap')) parts.push('시가총액이 작은 편이라 같은 매집에도 변동이 클 수 있습니다(리스크도 큼).');
  if (parts.length === 0) parts.push('지금은 뚜렷한 매집·반등 신호가 약한 편입니다 — 아래 점수 구성을 확인해보세요.');
  return parts.join(' ');
}

init();
