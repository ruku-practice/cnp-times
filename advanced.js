// 勝手にCNP TIMES — 高機能版ロジック
(() => {
  const CHARS = ['オロチ', 'ミタマ', 'ナルカミ', 'リーリー', 'ルナ', 'ヤーマ', 'マカミ', 'トワ', 'セツナ', 'エマ', 'タルト'];
  const CHAR_IMG = {
    'オロチ': 'orochi.png', 'ミタマ': 'mitama.png', 'ナルカミ': 'narukami.png', 'リーリー': 'leelee.png',
    'ルナ': 'luna.png', 'ヤーマ': 'yama.png', 'マカミ': 'makami.png', 'トワ': 'towa.png',
    'セツナ': 'setsuna.png', 'エマ': 'ema.png', 'タルト': 'taruto.png'
  };

  // ---------- Theme ----------
  const themeBtn = document.getElementById('theme-btn');
  function applyTheme(t) {
    document.documentElement.setAttribute('data-theme', t);
    themeBtn.textContent = t === 'dark' ? '☀️' : '🌙';
  }
  const saved = localStorage.getItem('cnp-theme');
  applyTheme(saved || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'));
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
    if (num > 0) return 'up';
    if (num < 0) return 'down';
    return 'flat';
  }

  // ---------- html2 parser ----------
  function parseHtml2(data) {
    const byC1 = (label) => data.find(r => txt(r[1]) === label);
    const byC1pre = (pre) => data.find(r => txt(r[1]).startsWith(pre));
    const byC2 = (label) => data.find(r => txt(r[2]) === label);
    const m4 = (r) => r ? { eth: txt(r[4]), ethDiff: txt(r[6]), jpy: txt(r[8]), jpyDiff: txt(r[10]) } : {};

    // header
    let issue = '', date = '', time = '';
    for (const r of data) {
      const j = r.join(' ');
      const mi = j.match(/第(\d+)号/); if (mi) issue = mi[1];
      const md = j.match(/\d{4}\/\d{1,2}\/\d{1,2}\([^)]*\)/); if (md) date = md[0];
      const mt = (r[10] || '').match(/^\d{1,2}:\d{2}$/); if (mt) time = mt[0];
    }

    const owners = byC1('オーナー数');
    const listed = byC1('出品数');
    const chars = [];
    for (const r of data) {
      const name = txt(r[2]);
      if (CHARS.includes(name)) {
        chars.push({ name, eth: txt(r[4]), ethDiff: txt(r[6]), list: txt(r[8]), listDiff: txt(r[10]) });
      }
    }
    return {
      issue, date, time,
      floor: m4(byC1('最安価格（FloorPrice）')),
      avg: m4(byC1('平均販売価格')),
      totalVol: m4(byC1pre('総取引量')),
      marketcap: m4(byC1('時価総額（MarketCap）')),
      owners: owners ? { count: txt(owners[4]), diff: txt(owners[6]), sales: txt(owners[10]) } : {},
      listed: listed ? { count: txt(listed[4]), diff: txt(listed[6]), rate: txt(listed[10]) } : {},
      past7: m4(byC1('7日前のフロア')),
      past30: m4(byC1('30日前のフロア')),
      refEth: (() => { const r = byC2('ETH価格'); return r ? { price: txt(r[4]), diff: txt(r[6]) } : {}; })(),
      refUsd: (() => { const r = byC2('USD価格'); return r ? { price: txt(r[4]), diff: txt(r[6]) } : {}; })(),
      chars
    };
  }

  // ---------- today cards ----------
  function diffPill(s) {
    const t = txt(s);
    if (!t) return '';
    return `<span class="d ${classifyDiff(t)}">${t}</span>`;
  }
  function card(k, vMain, vSmall, diff) {
    return `<div class="card"><div class="k">${k}</div>` +
      `<div class="v mono">${vMain || '--'}${vSmall ? `<small>${vSmall}</small>` : ''}</div>` +
      (diff != null && txt(diff) !== '' ? `<div>${diffPill(diff)}</div>` : '') + `</div>`;
  }
  function renderToday(p) {
    $('today-cards').innerHTML = [
      card('最安フロア (ETH)', p.floor.eth, p.floor.jpy ? `¥${p.floor.jpy}` : '', p.floor.ethDiff),
      card('平均販売価格 (ETH)', p.avg.eth, p.avg.jpy ? `¥${p.avg.jpy}` : '', p.avg.ethDiff),
      card('時価総額 (円)', p.marketcap.jpy, p.marketcap.eth ? `${p.marketcap.eth} ETH` : '', p.marketcap.jpyDiff),
      card('総取引量 (ETH)', p.totalVol.eth, p.totalVol.jpy ? `¥${p.totalVol.jpy}` : '', p.totalVol.ethDiff),
      card('オーナー数', p.owners.count, '', p.owners.diff),
      card('出品数', p.listed.count, p.listed.rate ? `率 ${p.listed.rate}` : '', p.listed.diff),
      card('セールス数 (24h)', p.owners.sales, '', null),
      card('ETH価格', p.refEth.price, '', p.refEth.diff),
      card('USD価格', p.refUsd.price, '', p.refUsd.diff),
    ].join('');
    $('today-hint').textContent = p.date ? `（${p.date} ${p.time} 時点）` : '';
    $('meta-date').textContent = p.date || '';
    $('meta-issue').textContent = p.issue ? `第${p.issue}号` : '';
  }

  // ---------- Chart ----------
  let chart = null;
  const chartState = { target: 'ALL', metric: 'floor', days: 365 };
  function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  function seriesFor(target) {
    return target === 'ALL' ? HISTORY.all : (HISTORY.chars[target] || { floor: [], listed: [] });
  }
  function renderChart() {
    const s = seriesFor(chartState.target);
    let dates = HISTORY.dates, vals = s[chartState.metric] || [];
    if (chartState.days > 0 && dates.length > chartState.days) {
      dates = dates.slice(-chartState.days);
      vals = vals.slice(-chartState.days);
    }
    const accent = chartState.metric === 'floor' ? cssVar('--accent-2') : cssVar('--accent');
    const grid = cssVar('--border'), tick = cssVar('--text-dim');
    if (chart) chart.destroy();
    chart = new Chart($('chart').getContext('2d'), {
      type: 'line',
      data: {
        labels: dates,
        datasets: [{
          label: (chartState.target) + ' / ' + (chartState.metric === 'floor' ? 'フロア(ETH)' : '出品数'),
          data: vals, borderColor: accent, backgroundColor: accent + '22',
          borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0.25, fill: true, spanGaps: true
        }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: { legend: { display: false },
          tooltip: { backgroundColor: cssVar('--surface'), titleColor: cssVar('--text'),
            bodyColor: cssVar('--text'), borderColor: grid, borderWidth: 1 } },
        scales: {
          x: { grid: { color: grid }, ticks: { color: tick, maxTicksLimit: 8, font: { size: 10 } } },
          y: { grid: { color: grid }, ticks: { color: tick, font: { size: 11 } } }
        }
      }
    });
  }
  function setupChartControls() {
    const sel = $('chart-target');
    sel.innerHTML = ['ALL', ...CHARS].map(c => `<option value="${c}">${c === 'ALL' ? '全体 (ALL)' : c}</option>`).join('');
    sel.addEventListener('change', () => { chartState.target = sel.value; renderChart(); });
    document.querySelectorAll('.btn.metric').forEach(b => b.addEventListener('click', () => {
      document.querySelectorAll('.btn.metric').forEach(x => x.classList.remove('active'));
      b.classList.add('active'); chartState.metric = b.dataset.metric; renderChart();
    }));
    document.querySelectorAll('.btn.period').forEach(b => b.addEventListener('click', () => {
      document.querySelectorAll('.btn.period').forEach(x => x.classList.remove('active'));
      b.classList.add('active'); chartState.days = parseInt(b.dataset.days); renderChart();
    }));
  }

  // ---------- Date time-travel ----------
  function fmtNum(n, d) { return n == null ? '--' : Number(n).toFixed(d); }
  function signed(n, d) { if (n == null) return ''; const v = Number(n); return (v > 0 ? '+' : '') + v.toFixed(d); }

  function renderFullTable(p, iso) {
    const sec = (label) => `<tr class="seclabel"><td colspan="5">${label}</td></tr>`;
    const rowM = (name, m) => `<tr><td>${name}</td><td class="mono">${m.eth || '--'}</td>` +
      `<td class="mono ${classifyDiff(m.ethDiff)}">${txt(m.ethDiff)}</td>` +
      `<td class="mono">${m.jpy || '--'}</td><td class="mono ${classifyDiff(m.jpyDiff)}">${txt(m.jpyDiff)}</td></tr>`;
    let html = `<table class="t"><caption>${iso} の記録（フル）</caption>` +
      `<thead><tr><th>項目</th><th>Price(ETH)</th><th>前日差</th><th>Price(JPY)</th><th>前日差</th></tr></thead><tbody>`;
    html += sec('本日データ');
    html += rowM('最安価格（フロア）', p.floor);
    html += rowM('平均販売価格', p.avg);
    html += rowM('時価総額', p.marketcap);
    html += rowM('総取引量', p.totalVol);
    html += `<tr><td>オーナー数</td><td class="mono">${p.owners.count || '--'}</td>` +
      `<td class="mono ${classifyDiff(p.owners.diff)}">${txt(p.owners.diff)}</td>` +
      `<td>セールス数</td><td class="mono">${p.owners.sales || '--'}</td></tr>`;
    html += `<tr><td>出品数</td><td class="mono">${p.listed.count || '--'}</td>` +
      `<td class="mono ${classifyDiff(p.listed.diff)}">${txt(p.listed.diff)}</td>` +
      `<td>出品率</td><td class="mono">${p.listed.rate || '--'}</td></tr>`;
    // characters
    html += `<tr class="seclabel"><td>キャラクター</td><td>Price(ETH)</td><td>前日差</td><td>リスト数/率</td><td>前日差</td></tr>`;
    for (const c of p.chars) {
      const img = CHAR_IMG[c.name] || '';
      html += `<tr><td><div class="charcell"><img src="${img}" alt="">${c.name}</div></td>` +
        `<td class="mono">${c.eth || '--'}</td><td class="mono ${classifyDiff(c.ethDiff)}">${txt(c.ethDiff)}</td>` +
        `<td class="mono">${c.list || '--'}</td><td class="mono ${classifyDiff(c.listDiff)}">${txt(c.listDiff)}</td></tr>`;
    }
    html += sec('過去データ');
    html += rowM('7日前のフロア', p.past7);
    html += rowM('30日前のフロア', p.past30);
    html += `<tr class="seclabel"><td>参考</td><td>Price</td><td>前日差</td><td></td><td></td></tr>`;
    html += `<tr><td>ETH価格</td><td class="mono">${p.refEth.price || '--'}</td><td class="mono ${classifyDiff(p.refEth.diff)}">${txt(p.refEth.diff)}</td><td></td><td></td></tr>`;
    html += `<tr><td>USD価格</td><td class="mono">${p.refUsd.price || '--'}</td><td class="mono ${classifyDiff(p.refUsd.diff)}">${txt(p.refUsd.diff)}</td><td></td><td></td></tr>`;
    html += `</tbody></table>`;
    $('travel-panel').innerHTML = html;
  }

  function renderPartialTable(idx) {
    const prev = idx > 0 ? idx - 1 : null;
    const entRow = (name, ser, img) => {
      const f = ser.floor[idx], l = ser.listed[idx];
      const fd = prev != null && f != null && ser.floor[prev] != null ? f - ser.floor[prev] : null;
      const ld = prev != null && l != null && ser.listed[prev] != null ? l - ser.listed[prev] : null;
      const nameCell = img ? `<div class="charcell"><img src="${img}" alt="">${name}</div>` : name;
      return `<tr><td>${nameCell}</td><td class="mono">${f == null ? '--' : fmtNum(f, 3)}</td>` +
        `<td class="mono ${fd == null ? '' : (fd >= 0 ? 'up' : 'down')}">${fd == null ? '' : signed(fd, 3)}</td>` +
        `<td class="mono">${l == null ? '--' : l}</td>` +
        `<td class="mono ${ld == null ? '' : (ld >= 0 ? 'up' : 'down')}">${ld == null ? '' : signed(ld, 0)}</td></tr>`;
    };
    let html = `<table class="t"><caption>${HISTORY.dates[idx]} の記録（フロア価格・出品数のみ）</caption>` +
      `<thead><tr><th>項目</th><th>フロア(ETH)</th><th>前日差</th><th>出品数</th><th>前日差</th></tr></thead><tbody>`;
    html += `<tr class="seclabel"><td colspan="5">全体</td></tr>`;
    html += entRow('ALL（全体）', HISTORY.all, '');
    html += `<tr class="seclabel"><td colspan="5">キャラクター</td></tr>`;
    for (const c of CHARS) {
      if (HISTORY.chars[c]) html += entRow(c, HISTORY.chars[c], CHAR_IMG[c]);
    }
    html += `</tbody></table>`;
    $('travel-panel').innerHTML = html;
  }

  function nearestHistoryIdx(iso) {
    const ds = HISTORY.dates;
    let idx = ds.indexOf(iso);
    if (idx >= 0) return idx;
    // nearest date <= iso
    let best = -1;
    for (let i = 0; i < ds.length; i++) { if (ds[i] <= iso) best = i; else break; }
    return best >= 0 ? best : 0;
  }

  function showDate(iso) {
    $('date-picker').value = iso;
    if (SNAP_SET.has(iso)) {
      fetchJSON(`snapshots/${iso}.json`).then(d => {
        renderFullTable(parseHtml2(d), iso);
        $('date-note').className = 'note';
        $('date-note').textContent = `📸 ${iso} のフルスナップショット記録です。`;
      }).catch(() => {
        const idx = nearestHistoryIdx(iso); renderPartialTable(idx);
        $('date-note').className = 'note warn';
        $('date-note').textContent = `スナップショット読込に失敗したため、${HISTORY.dates[idx]} のフロア/出品数のみ表示しています。`;
      });
    } else {
      const idx = nearestHistoryIdx(iso);
      renderPartialTable(idx);
      $('date-note').className = 'note warn';
      const exact = HISTORY.dates[idx] === iso;
      $('date-note').textContent = exact
        ? `この日はフル記録がありません（自動記録の開始前）。フロア価格・出品数のみ表示しています。`
        : `${iso} ちょうどの記録がないため、直近の記録日 ${HISTORY.dates[idx]} を表示しています（フロア/出品数のみ）。`;
    }
  }

  function setupDateControls() {
    const ds = HISTORY.dates;
    const picker = $('date-picker');
    picker.min = ds[0]; picker.max = ds[ds.length - 1];
    picker.value = ds[ds.length - 1];
    picker.addEventListener('change', () => showDate(picker.value));
    const step = (dir) => {
      let idx = nearestHistoryIdx(picker.value);
      if (ds[idx] === picker.value) idx += dir; // 既にその日なら隣へ
      else if (dir > 0) idx += 1;               // 近似日からは前後どちらかへ
      idx = Math.max(0, Math.min(ds.length - 1, idx));
      showDate(ds[idx]);
    };
    $('date-prev').addEventListener('click', () => step(-1));
    $('date-next').addEventListener('click', () => step(1));
    $('date-latest').addEventListener('click', () => showDate(ds[ds.length - 1]));
  }

  // ---------- boot ----------
  let HISTORY = null, SNAP_SET = new Set();
  Promise.all([
    fetchJSON('html2_data.json'),
    fetchJSON('data/history.json'),
    fetchJSON('snapshots/index.json').catch(() => [])
  ]).then(([html2, history, snaps]) => {
    HISTORY = history;
    SNAP_SET = new Set(snaps || []);
    $('loader').classList.add('hidden');
    $('main').classList.remove('hidden');

    renderToday(parseHtml2(html2));
    setupChartControls();
    renderChart();
    setupDateControls();
    showDate(HISTORY.dates[HISTORY.dates.length - 1]);
  }).catch(err => {
    $('loader').innerHTML = `<p style="color:var(--down)">データの読み込みに失敗しました。</p><p style="font-size:12px">${err.message}</p>`;
  });
})();
