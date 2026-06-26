// 勝手にCNP TIMES — 高機能版ロジック
(() => {
  const CHARS = ['オロチ', 'ミタマ', 'ナルカミ', 'リーリー', 'ルナ', 'ヤーマ', 'マカミ', 'トワ', 'セツナ', 'エマ', 'タルト'];
  const CHAR_IMG = {
    'オロチ': 'orochi.png', 'ミタマ': 'mitama.png', 'ナルカミ': 'narukami.png', 'リーリー': 'leelee.png',
    'ルナ': 'luna.png', 'ヤーマ': 'yama.png', 'マカミ': 'makami.png', 'トワ': 'towa.png',
    'セツナ': 'setsuna.png', 'エマ': 'ema.png', 'タルト': 'taruto.png'
  };
  // 各キャラの供給数（リスト率の母数）。
  // CHAR_SUPPLY = 現在（エマ・タルト登場後）、OLD_CHAR_SUPPLY = それ以前（旧スプレッドシート計算式の母数）
  const CHAR_SUPPLY = {
    'オロチ': 3148, 'ミタマ': 3593, 'ナルカミ': 3348, 'リーリー': 4389, 'ルナ': 1950, 'ヤーマ': 1618,
    'マカミ': 1345, 'トワ': 924, 'セツナ': 914, 'エマ': 495, 'タルト': 496
  };
  const OLD_CHAR_SUPPLY = {
    'オロチ': 3468, 'ミタマ': 3732, 'ナルカミ': 3444, 'リーリー': 4560, 'ルナ': 1977, 'ヤーマ': 1651, 'マカミ': 1394
  };
  // 当該日が「現在の母数」を適用できる時期か（エマが存在する＝floorが入っている）
  function emaExists(i) { const e = HISTORY.chars['エマ']; return !!(e && e.floor[i] != null); }
  function charRate(name, listed, i) {
    if (listed == null) return null;
    const supply = emaExists(i) ? CHAR_SUPPLY[name] : OLD_CHAR_SUPPLY[name];
    if (!supply) return null;
    return (listed / supply * 100).toFixed(2) + '%';
  }

  // ---------- Theme ----------
  const themeBtn = document.getElementById('theme-btn');
  function applyTheme(t) {
    document.documentElement.setAttribute('data-theme', t);
    themeBtn.textContent = t === 'dark' ? '☀️' : '🌙';
  }
  applyTheme(localStorage.getItem('cnp-theme') || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'));
  themeBtn.addEventListener('click', () => {
    const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    localStorage.setItem('cnp-theme', next);
    applyTheme(next);
    if (chart) renderChart();
  });

  // ---------- helpers ----------
  const $ = (id) => document.getElementById(id);
  const txt = (v) => (v == null ? '' : String(v).trim());
  function fetchJSON(url) {
    return fetch(url).then(r => { if (!r.ok) throw new Error(`${url}: ${r.status}`); return r.json(); });
  }
  function classifyDiff(s) {
    const t = txt(s);
    if (!t || t === '--' || t === '#REF!') return 'flat';
    const num = parseFloat(t.replace(/,/g, ''));
    if (isNaN(num)) return t.startsWith('-') ? 'down' : 'flat';
    if (num > 0) return 'up'; if (num < 0) return 'down'; return 'flat';
  }
  const nf = (n, d = 0) => n == null ? '--' : Number(n).toLocaleString('ja-JP', { minimumFractionDigits: d, maximumFractionDigits: d });
  const eth = (n, d = 3) => n == null ? '--' : Number(n).toFixed(d);
  const yen = (n) => n == null ? '--' : '¥' + Math.round(n).toLocaleString('ja-JP');
  function diffCell(cur, prev, d = 3, comma = false) {
    if (cur == null || prev == null) return '<td class="mono"></td>';
    const v = cur - prev;
    const cls = v > 0 ? 'up' : v < 0 ? 'down' : 'flat';
    const s = (v > 0 ? '+' : '') + (comma ? Math.round(v).toLocaleString('ja-JP') : v.toFixed(d));
    return `<td class="mono ${cls}">${s}</td>`;
  }

  // ---------- html2 parser (今日のカード用) ----------
  function parseHtml2(data) {
    const byC1 = (label) => data.find(r => txt(r[1]) === label);
    const byC1pre = (pre) => data.find(r => txt(r[1]).startsWith(pre));
    const byC2 = (label) => data.find(r => txt(r[2]) === label);
    const m4 = (r) => r ? { eth: txt(r[4]), ethDiff: txt(r[6]), jpy: txt(r[8]), jpyDiff: txt(r[10]) } : {};
    let issue = '', date = '', time = '';
    for (const r of data) {
      const j = r.join(' ');
      const mi = j.match(/第(\d+)号/); if (mi) issue = mi[1];
      const md = j.match(/\d{4}\/\d{1,2}\/\d{1,2}\([^)]*\)/); if (md) date = md[0];
      const mt = (r[10] || '').match(/^\d{1,2}:\d{2}$/); if (mt) time = mt[0];
    }
    const owners = byC1('オーナー数'), listed = byC1('出品数');
    return {
      issue, date, time,
      floor: m4(byC1('最安価格（FloorPrice）')), avg: m4(byC1('平均販売価格')),
      totalVol: m4(byC1pre('総取引量')), marketcap: m4(byC1('時価総額（MarketCap）')),
      owners: owners ? { count: txt(owners[4]), diff: txt(owners[6]), sales: txt(owners[10]) } : {},
      listed: listed ? { count: txt(listed[4]), diff: txt(listed[6]), rate: txt(listed[10]) } : {},
      refEth: (() => { const r = byC2('ETH価格'); return r ? { price: txt(r[4]), diff: txt(r[6]) } : {}; })(),
      refUsd: (() => { const r = byC2('USD価格'); return r ? { price: txt(r[4]), diff: txt(r[6]) } : {}; })(),
    };
  }
  function diffPill(s) { const t = txt(s); return t ? `<span class="d ${classifyDiff(t)}">${t}</span>` : ''; }
  function card(k, vMain, unit, vSmall, diff) {
    const u = unit ? ` <span class="unit">${unit}</span>` : '';
    return `<div class="card"><div class="k">${k}</div>` +
      `<div class="v mono">${vMain || '--'}${u}${vSmall ? `<small>${vSmall}</small>` : ''}</div>` +
      (diff != null && txt(diff) !== '' ? `<div>${diffPill(diff)}</div>` : '') + `</div>`;
  }
  // 円を 億/万/円 で見やすく整形
  function yenSmart(v) {
    if (v == null) return '--';
    const a = Math.abs(v);
    if (a >= 1e8) return '¥' + (v / 1e8).toFixed(1) + '億';
    return '¥' + Math.round(v).toLocaleString('ja-JP');
  }
  function renderToday(p) {
    // すべて history（対象日 = 取得日の前日＝0:00時点）から算出して整合させる
    const H = HISTORY, li = H.dates.length - 1, prev = li > 0 ? li - 1 : null, ej = H.eth_jpy[li];
    const A = H.all, G = H.agg, O = OFFERS || {};
    const jpyOf = (v) => (v != null && ej != null) ? yenSmart(v * ej) : '';
    // 前日差（li=対象日 と prev=その前日）
    const dd = (arr, dec, comma) => {
      if (prev == null || arr[li] == null || arr[prev] == null) return null;
      const v = arr[li] - arr[prev];
      return (v > 0 ? '+' : '') + (comma ? Math.round(v).toLocaleString('ja-JP') : v.toFixed(dec));
    };
    const rate = A.listed[li] != null ? (A.listed[li] / (G.supply[li] || 22222) * 100).toFixed(2) + '%' : '';
    // CNP の情報（上段）
    $('today-cards').innerHTML = [
      card('最安フロア', eth(A.floor[li], 3), 'ETH', jpyOf(A.floor[li]), dd(A.floor, 3)),
      card('平均販売価格', eth(G.avg[li], 3), 'ETH', jpyOf(G.avg[li]), dd(G.avg, 3)),
      card('日次トータル販売額', eth(G.day_volume[li], 4), 'ETH', jpyOf(G.day_volume[li]), null),
      card('時価総額', nf(G.mcap[li], 0), 'ETH', jpyOf(G.mcap[li]), dd(G.mcap, 0, true)),
      card('累計取引量', nf(G.volume[li], 1), 'ETH', jpyOf(G.volume[li]), null),
      card('オーナー数', G.owners[li] != null ? nf(G.owners[li]) : '--', '件', '', dd(G.owners, 0)),
      card('出品数', A.listed[li] != null ? nf(A.listed[li]) : '--', '点', rate ? `率 ${rate}` : '', dd(A.listed, 0)),
      card('セールス数 (24h)', G.sales[li] != null ? nf(G.sales[li]) : '--', '件', '', dd(G.sales, 0)),
      card('トップオファー', eth(O.top_offer, 3), 'WETH', jpyOf(O.top_offer), null),
      card('オファー数', O.offer_count != null ? nf(O.offer_count) : '--', '口', '', null),
      card('オファー総額', eth(O.offer_total, 3), 'WETH', jpyOf(O.offer_total), null),
    ].join('');
    // 参考レート（為替・下段）
    $('today-ref-cards').innerHTML = [
      card('ETH価格', H.eth_jpy[li] != null ? '¥' + nf(H.eth_jpy[li]) : '--', '', '', dd(H.eth_jpy, 0, true)),
      card('USD価格', H.usd[li] != null ? '¥' + Number(H.usd[li]).toFixed(2) : '--', '', '', dd(H.usd, 2)),
    ].join('');
    // 対象日 = 取得日の前日（history の最新日付）。取得日時は latest_collected。
    const repDay = H.dates[li];
    const coll = H.latest_collected || {};
    $('today-title').textContent = `${jpDate(repDay)} のサマリ`;
    $('today-hint').textContent = coll.date ? `（取得: ${jpDate(coll.date)} ${coll.time || ''}）` : '';
    // 第N号の横は「発行日」＝取得日に合わせる
    $('meta-date').textContent = coll.date ? jpDate(coll.date) : '';
    $('meta-issue').textContent = (p && p.issue) ? `第${p.issue}号` : '';
  }
  const WD = ['日', '月', '火', '水', '木', '金', '土'];
  function jpDate(iso) {
    if (!iso) return '';
    const [y, m, d] = iso.split('-').map(Number);
    const w = new Date(iso + 'T00:00:00').getDay();
    return `${m}月${d}日(${WD[w]})`;
  }
  function addDays(iso, n) {
    const d = new Date(iso + 'T00:00:00Z'); d.setUTCDate(d.getUTCDate() + n);
    return d.toISOString().slice(0, 10);
  }
  // 取得日時（= 対象日の翌日 + 保存済み時刻）の表示。過去日でも可能な限り出す。
  function collLabel(i) {
    const ct = (HISTORY.collected_times || [])[i] || '';
    const cd = addDays(HISTORY.dates[i], 1);
    return `（取得: ${jpDate(cd)}${ct ? ' ' + ct : ''}）`;
  }

  // ---------- Chart ----------
  let chart = null;
  const chartState = { target: 'ALL', metric: 'floor', cur: 'eth', days: 365 };
  function cssVar(n) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }
  function seriesFor(t) { return t === 'ALL' ? HISTORY.all : (HISTORY.chars[t] || { floor: [], listed: [] }); }
  // 指標の定義: type(line/bar), cur(円換算対応), perChar(対象キャラ選択が効くか)
  const METRICS = {
    floor:      { label: 'フロア価格', type: 'line', cur: true,  perChar: true },
    listed:     { label: '出品数',     type: 'line', cur: false, perChar: true },
    sales:      { label: 'セールス数', type: 'bar',  cur: false, perChar: false },
    day_volume: { label: 'セールス額', type: 'bar',  cur: true,  perChar: false },
    volume:     { label: '累計取引量', type: 'line', cur: true,  perChar: false },
    mcap:       { label: '時価総額',   type: 'line', cur: true,  perChar: false },
  };
  function metricSeries(metric) {
    if (metric === 'floor' || metric === 'listed') return seriesFor(chartState.target)[metric] || [];
    return HISTORY.agg[metric] || [];
  }
  const fmtYenAxis = (v) => {
    const a = Math.abs(v);
    if (a >= 1e8) return '¥' + (v / 1e8).toFixed(1) + '億';
    if (a >= 1e4) return '¥' + Math.round(v / 1e4) + '万';
    return '¥' + v;
  };
  function renderChart() {
    const m = METRICS[chartState.metric] || METRICS.floor;
    const isBar = m.type === 'bar';
    let dates = HISTORY.dates, vals = metricSeries(chartState.metric), ej = HISTORY.eth_jpy || [];
    let lo = 0, hi = dates.length;
    if (chartState.days === 'custom' && chartState.from && chartState.to) {
      lo = dates.findIndex(d => d >= chartState.from); if (lo < 0) lo = dates.length;
      for (let i = dates.length - 1; i >= 0; i--) { if (dates[i] <= chartState.to) { hi = i + 1; break; } }
    } else if (typeof chartState.days === 'number' && chartState.days > 0 && dates.length > chartState.days) {
      lo = dates.length - chartState.days;
    }
    dates = dates.slice(lo, hi); vals = vals.slice(lo, hi); ej = ej.slice(lo, hi);
    const cEth = cssVar('--accent-2'), cJpy = cssVar('--accent'), grid = cssVar('--border'), tick = cssVar('--text-dim');
    const tgt = m.perChar ? chartState.target + ' ' : '';
    const datasets = [], scales = { x: { grid: { color: grid }, ticks: { color: tick, maxTicksLimit: 8, font: { size: 10 } } } };
    const mk = (label, data, color, axis) => ({
      label, data, borderColor: color, backgroundColor: isBar ? color + 'cc' : color + '22', yAxisID: axis,
      borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0.25, fill: !isBar && axis === 'y',
      spanGaps: true, maxBarThickness: 18, borderRadius: 2
    });
    if (m.cur) {
      const wantEth = chartState.cur === 'eth' || chartState.cur === 'both';
      const wantJpy = chartState.cur === 'jpy' || chartState.cur === 'both';
      const jpyVals = vals.map((v, i) => (v != null && ej[i] != null) ? Math.round(v * ej[i]) : null);
      if (wantEth) {
        datasets.push(mk(`${tgt}${m.label} (ETH)`, vals, cEth, 'y'));
        scales.y = { position: 'left', grid: { color: grid }, ticks: { color: cEth, callback: v => v + ' Ξ' } };
      }
      if (wantJpy) {
        const axis = (chartState.cur === 'both') ? 'y2' : 'y';
        datasets.push(mk(`${tgt}${m.label} (円)`, jpyVals, cJpy, axis));
        const ax = { grid: { color: chartState.cur === 'both' ? 'transparent' : grid }, ticks: { color: cJpy, callback: fmtYenAxis } };
        if (chartState.cur === 'both') { ax.position = 'right'; scales.y2 = ax; } else scales.y = ax;
      }
    } else {
      datasets.push(mk(`${tgt}${m.label}`, vals, cJpy, 'y'));
      scales.y = { grid: { color: grid }, ticks: { color: tick } };
    }
    if (chart) chart.destroy();
    chart = new Chart($('chart').getContext('2d'), {
      type: m.type, data: { labels: dates, datasets },
      options: {
        responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
        onClick: (evt, _els, ch) => {
          const pts = ch.getElementsAtEventForMode(evt, 'index', { intersect: false }, true);
          if (!pts.length) return;
          const date = ch.data.labels[pts[0].index];
          if (date && idxByDate(date) >= 0) {
            showDate(date);
            const el = document.getElementById('travel-panel');
            if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
          }
        },
        plugins: {
          legend: { display: datasets.length > 1, labels: { color: tick, boxWidth: 12, font: { size: 11 } } },
          tooltip: { backgroundColor: cssVar('--surface'), titleColor: cssVar('--text'), bodyColor: cssVar('--text'), borderColor: grid, borderWidth: 1 }
        },
        scales
      }
    });
    updateChartControlStates();
  }
  function updateChartControlStates() {
    const m = METRICS[chartState.metric] || {};
    const sel = $('chart-target');
    sel.disabled = !m.perChar; sel.style.opacity = m.perChar ? '1' : '0.4';
    document.querySelectorAll('.btn.cur').forEach(b => { b.disabled = !m.cur; b.style.opacity = m.cur ? '' : '0.4'; });
  }
  function setupChartControls() {
    const sel = $('chart-target');
    sel.innerHTML = ['ALL', ...CHARS].map(c => `<option value="${c}">${c === 'ALL' ? '全体 (ALL)' : c}</option>`).join('');
    sel.addEventListener('change', () => { chartState.target = sel.value; renderChart(); });
    const grp = (cls, key) => document.querySelectorAll('.btn.' + cls).forEach(b => b.addEventListener('click', () => {
      document.querySelectorAll('.btn.' + cls).forEach(x => x.classList.remove('active'));
      b.classList.add('active'); chartState[key] = b.dataset[key]; renderChart();
    }));
    grp('metric', 'metric'); grp('cur', 'cur');
    document.querySelectorAll('.btn.period').forEach(b => b.addEventListener('click', () => {
      document.querySelectorAll('.btn.period').forEach(x => x.classList.remove('active'));
      b.classList.add('active');
      const v = b.dataset.days;
      if (v === 'custom') {
        chartState.days = 'custom';
        const ds = HISTORY.dates, rf = $('range-from'), rt = $('range-to');
        rf.min = rt.min = ds[0]; rf.max = rt.max = ds[ds.length - 1];
        if (!rf.value) rf.value = ds[Math.max(0, ds.length - 90)];
        if (!rt.value) rt.value = ds[ds.length - 1];
        chartState.from = rf.value; chartState.to = rt.value;
        $('custom-range').classList.remove('hidden');
      } else {
        chartState.days = parseInt(v);
        $('custom-range').classList.add('hidden');
      }
      renderChart();
    }));
    $('range-apply').addEventListener('click', () => {
      chartState.from = $('range-from').value; chartState.to = $('range-to').value;
      chartState.days = 'custom'; renderChart();
    });
  }

  // ---------- Date time-travel: 履歴からフル表を再現 ----------
  let DATE_IDX = {};
  function idxByDate(iso) {
    if (iso in DATE_IDX) return DATE_IDX[iso];
    const ds = HISTORY.dates; let best = -1;
    for (let i = 0; i < ds.length; i++) { if (ds[i] <= iso) best = i; else break; }
    return best;
  }
  function shiftDays(iso, n) {
    const d = new Date(iso + 'T00:00:00Z'); d.setUTCDate(d.getUTCDate() + n);
    return d.toISOString().slice(0, 10);
  }
  function renderDayTable(i) {
    const H = HISTORY, ej = H.eth_jpy[i], prev = i > 0 ? i - 1 : null;
    const jv = (v) => (v != null && ej != null) ? v * ej : null;
    const A = H.all, G = H.agg;
    // 金額メトリクス行: ETH | 前日差 | JPY | 前日差
    const moneyRow = (name, arr, dec) => {
      const cur = arr[i], pv = prev != null ? arr[prev] : null;
      return `<tr><td>${name}</td><td class="mono">${eth(cur, dec)}</td>${diffCell(cur, pv, dec)}` +
        `<td class="mono">${yen(jv(cur))}</td>${diffCell(jv(cur), prev != null ? jv(arr[prev]) : null, 0, true)}</tr>`;
    };
    // 件数メトリクス（単位は件/%なので左寄せ。Price(JPY)列は空欄）
    const countRow = (name, arr) => {
      const cur = arr[i], pv = prev != null ? arr[prev] : null;
      return `<tr><td>${name}</td><td class="mono">${nf(cur)}</td>${diffCell(cur, pv, 0)}<td></td><td></td></tr>`;
    };
    const sec = (t) => `<tr class="seclabel"><td colspan="5">${t}</td></tr>`;
    let h = `<table class="t"><caption>${jpDate(H.dates[i])} の記録 <span class="cap-sub">${collLabel(i)}</span></caption>` +
      `<thead><tr><th>項目</th><th>Price(ETH)/件</th><th>前日差</th><th>Price(JPY)</th><th>前日差</th></tr></thead><tbody>`;
    h += sec('本日データ');
    h += moneyRow('最安価格（フロア）', A.floor, 3);
    h += moneyRow('平均販売価格', G.avg, 3);
    h += moneyRow('日次トータル販売額', G.day_volume, 4);
    h += moneyRow('時価総額', G.mcap, 0);
    h += moneyRow('累計取引量', G.volume, 1);
    h += countRow('オーナー数', G.owners);
    h += countRow('セールス数(24h)', G.sales);
    h += countRow('出品数', A.listed);
    // 出品率（%表示・前日差はポイント差）
    const rateAt = (k) => (k != null && A.listed[k] != null) ? (A.listed[k] / (G.supply[k] || 22222) * 100) : null;
    const rCur = rateAt(i), rPrev = rateAt(prev);
    h += `<tr><td>出品率</td><td class="mono">${rCur != null ? rCur.toFixed(2) + '%' : '--'}</td>` +
      `${diffCell(rCur, rPrev, 2)}<td></td><td></td></tr>`;
    // characters
    h += `<tr class="seclabel"><td>キャラクター</td><td>Price(ETH)</td><td>前日差</td><td>リスト数 (率)</td><td>前日差</td></tr>`;
    for (const c of CHARS) {
      const ser = H.chars[c]; if (!ser) continue;
      const f = ser.floor[i], pf = prev != null ? ser.floor[prev] : null;
      const l = ser.listed[i], pl = prev != null ? ser.listed[prev] : null;
      const img = CHAR_IMG[c] || '';
      const rate = charRate(c, l, i);
      const lcell = l == null ? '--' : nf(l) + (rate ? ` <small style="color:var(--text-dim)">${rate}</small>` : '');
      h += `<tr><td><div class="charcell"><img src="${img}" alt="">${c}</div></td>` +
        `<td class="mono">${eth(f, 3)}</td>${diffCell(f, pf, 3)}` +
        `<td class="mono">${lcell}</td>${diffCell(l, pl, 0)}</tr>`;
    }
    // past comparison
    h += sec('過去データ（本日との比較）');
    [['7日前のフロア', 7], ['30日前のフロア', 30]].forEach(([lbl, n]) => {
      const j = idxByDate(shiftDays(H.dates[i], -n));
      const pastF = j >= 0 ? A.floor[j] : null, cur = A.floor[i];
      const dEth = (cur != null && pastF != null) ? cur - pastF : null;
      h += `<tr><td>${lbl}</td><td class="mono">${eth(pastF, 3)}</td>` +
        `<td class="mono ${dEth == null ? '' : dEth >= 0 ? 'up' : 'down'}">${dEth == null ? '' : (dEth >= 0 ? '+' : '') + dEth.toFixed(3)}</td>` +
        `<td class="mono">${yen(jv(pastF))}</td><td></td></tr>`;
    });
    // reference
    h += `<tr class="seclabel"><td>参考</td><td>価格</td><td>前日差</td><td>円換算</td><td></td></tr>`;
    h += `<tr><td>ETH価格 (円)</td><td class="mono">${yen(H.eth_jpy[i])}</td>${diffCell(H.eth_jpy[i], prev != null ? H.eth_jpy[prev] : null, 0, true)}<td></td><td></td></tr>`;
    h += `<tr><td>USD価格 (円)</td><td class="mono">${H.usd[i] == null ? '--' : '¥' + Number(H.usd[i]).toFixed(2)}</td>${diffCell(H.usd[i], prev != null ? H.usd[prev] : null, 2)}<td></td><td></td></tr>`;
    h += `</tbody></table>`;
    $('travel-panel').innerHTML = h;
    $('date-note').className = 'note';
    $('date-note').textContent = (H.dates[i] === iso0) ? '' : `${H.dates[i]} 時点の全データを表示しています。`;
  }
  // ---------- セールス明細（NFTT） ----------
  const CONTRACT = '0x138A5C693279b6Cd82F48d4bEf563251Bc15ADcE';
  const shortAddr = (a) => a ? a.slice(0, 6) + '…' + a.slice(-4) : '--';
  // ニックネーム（あれば）＋アドレスのリンク。無ければアドレスのみ。
  function walletHtml(addr, title) {
    if (!addr) return '<span>--</span>';
    const w = (WALLETS || {})[addr.toLowerCase()] || {};
    const inner = w.name
      ? `${w.name} <span class="waddr">(${shortAddr(addr)})</span>`
      : shortAddr(addr);
    return `<a href="https://opensea.io/${addr}" target="_blank" rel="noopener" title="${title}">${inner}</a>`;
  }
  // ウォレットの取得時点のCNP保有数バッジ（🐤）。label=送信元/受信先
  // snap=セールス記録に焼き込まれた値（取得時点）。無ければ従来キャッシュにフォールバック。
  function cnpBadge(addr, label, snap) {
    const c = (snap != null) ? snap
      : (addr ? ((WALLETS || {})[addr.toLowerCase()] || {}).cnp : null);
    return (c != null) ? `<span class="sale-cnp" title="${label}の取得時点のCNP保有数">🐤${c}</span>` : '';
  }
  let SALES_SEQ = 0;
  function renderSales(iso) {
    const panel = $('sales-panel');
    const seq = ++SALES_SEQ;
    panel.innerHTML = `<div class="sales-head">🧾 ${jpDate(iso)} のセールス明細</div><div class="note">読み込み中…</div>`;
    fetch(`data/sales/${iso}.json`).then(r => r.ok ? r.json() : null).catch(() => null).then(sales => {
      if (seq !== SALES_SEQ) return; // 日付が変わっていたら破棄
      if (!sales || !sales.length) {
        panel.innerHTML = `<div class="sales-head">🧾 ${jpDate(iso)} のセールス明細</div>` +
          `<div class="note">この日のセールス記録はありません（明細の自動記録を順次蓄積しています）。</div>`;
        return;
      }
      let h = `<div class="sales-head">🧾 ${jpDate(iso)} のセールス（${sales.length}件）</div><div class="sales-list">`;
      for (const s of sales) {
        const item = s.token ? `https://opensea.io/item/ethereum/${CONTRACT}/${s.token}` : '#';
        const jpy = s.price_jpy != null ? `¥${Number(s.price_jpy).toLocaleString('ja-JP')}` : '';
        h += `<div class="sale">` +
          `<a class="sale-img" href="${item}" target="_blank" rel="noopener" title="OpenSeaで#${s.token}を見る">` +
          `${s.image ? `<img src="${s.image}" alt="#${s.token}" loading="lazy">` : ''}` +
          `<span class="sale-tok">#${s.token || '?'}</span></a>` +
          `<div class="sale-main">` +
          `<div class="sale-top"><span class="sale-char">${s.character || ''}</span><span class="sale-time">${s.time || ''}</span></div>` +
          `<div class="sale-price">${eth(s.price_eth, s.price_eth < 1 ? 3 : 2)} <span class="unit">ETH</span>${jpy ? `<small>${jpy}</small>` : ''}</div>` +
          `<div class="sale-addr">` +
          walletHtml(s.from, '送信元') +
          cnpBadge(s.from, '送信元', s.from_cnp) +
          `<span class="arrow">→</span>` +
          walletHtml(s.to, '受信先') +
          cnpBadge(s.to, '受信先', s.to_cnp) +
          `${s.tx ? `<a class="sale-tx" href="https://etherscan.io/tx/${s.tx}" target="_blank" rel="noopener">tx↗</a>` : ''}` +
          `</div></div></div>`;
      }
      h += '</div>';
      panel.innerHTML = h;
    });
  }

  let iso0 = '';
  function showDate(iso) {
    const i = idxByDate(iso);
    if (i < 0) return;
    $('date-picker').value = HISTORY.dates[i];
    renderDayTable(i);
    renderNews(HISTORY.dates[i]);
    renderSales(HISTORY.dates[i]);
  }

  // クリプトニンジャ・ニュース（X投稿）の埋め込み
  let twttrLoading = false;
  function loadTwitterWidgets(cb) {
    if (window.twttr && window.twttr.widgets) { cb && cb(); return; }
    const done = () => { const t = setInterval(() => { if (window.twttr && window.twttr.widgets) { clearInterval(t); cb && cb(); } }, 100); };
    if (twttrLoading) { done(); return; }
    twttrLoading = true;
    const s = document.createElement('script');
    s.src = 'https://platform.twitter.com/widgets.js';
    s.async = true; s.charset = 'utf-8';
    s.onload = () => cb && cb();
    document.head.appendChild(s);
  }
  function renderNews(iso) {
    const panel = $('news-panel');
    if (!panel) return;
    const n = (NEWS || {})[iso];
    if (!n || (!n.danku && !n.shack)) { panel.innerHTML = ''; return; }
    let h = `<div class="news-head">📰 ${iso} のクリプトニンジャ・ニュース <span class="cap-sub">（前日まとめ・X投稿）</span></div><div class="news-embeds">`;
    ['shack', 'danku'].forEach(g => {
      if (n[g] && n[g].url) h += `<blockquote class="twitter-tweet" data-lang="ja" data-dnt="true" data-conversation="none"><a href="${n[g].url}"></a></blockquote>`;
    });
    h += '</div>';
    panel.innerHTML = h;
    loadTwitterWidgets(() => { try { window.twttr.widgets.load(panel); } catch (e) {} });
  }
  function setupDateControls() {
    const ds = HISTORY.dates, picker = $('date-picker');
    picker.min = ds[0]; picker.max = ds[ds.length - 1]; picker.value = ds[ds.length - 1];
    iso0 = ds[ds.length - 1];
    picker.addEventListener('change', () => showDate(picker.value));
    const step = (dir) => {
      let i = idxByDate(picker.value);
      i = Math.max(0, Math.min(ds.length - 1, i + dir));
      showDate(ds[i]);
    };
    $('date-prev').addEventListener('click', () => step(-1));
    $('date-next').addEventListener('click', () => step(1));
    $('date-latest').addEventListener('click', () => showDate(ds[ds.length - 1]));
  }

  // ---------- boot ----------
  let HISTORY = null, OFFERS = null, WALLETS = {}, NEWS = {};
  Promise.all([
    fetchJSON('html2_data.json'),
    fetchJSON('data/history.json'),
    fetchJSON('data/offers.json').catch(() => null),
    fetchJSON('data/wallets.json').catch(() => ({})),
    fetchJSON('news.json').catch(() => ({}))
  ])
    .then(([html2, history, offers, wallets, news]) => {
      HISTORY = history; OFFERS = offers; WALLETS = wallets || {}; NEWS = news || {};
      HISTORY.dates.forEach((d, i) => DATE_IDX[d] = i);
      $('loader').classList.add('hidden');
      $('main').classList.remove('hidden');
      renderToday(parseHtml2(html2));
      setupChartControls(); renderChart();
      setupDateControls(); showDate(HISTORY.dates[HISTORY.dates.length - 1]);
    })
    .catch(err => {
      $('loader').innerHTML = `<p style="color:var(--down)">データの読み込みに失敗しました。</p><p style="font-size:12px">${err.message}</p>`;
    });
})();
