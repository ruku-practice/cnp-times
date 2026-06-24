// 勝手にCNP TIMES - Webダッシュボード制御スクリプト
// Version: 1.3 (ローカルJSONキャッシュ対応高速版)
document.addEventListener('DOMContentLoaded', () => {
  // Local JSON cache URLs (speeds up loading to sub-second)
  const HTML2_URL = 'html2_data.json';
  const FLOORPRICE_URL = 'floorprice_data.json';

  // Character Images mapping from NFTT Marketplace
  const charImages = {
    'オロチ': 'orochi.png',
    'ミタマ': 'mitama.png',
    'ナルカミ': 'narukami.png',
    'リーリー': 'leelee.png',
    'ルナ': 'luna.png',
    'ヤーマ': 'yama.png',
    'マカミ': 'makami.png',
    'トワ': 'towa.png',
    'セツナ': 'setsuna.png',
    'エマ': 'ema.png',
    'タルト': 'taruto.png'
  };

  const charactersList = ['オロチ', 'ミタマ', 'ナルカミ', 'リーリー', 'ルナ', 'ヤーマ', 'マカミ', 'トワ', 'セツナ', 'エマ', 'タルト'];

  let historyChartInstance = null;
  let chartData = {
    labels: [],
    floorPrices: [],
    listedCounts: []
  };

  // UI elements
  const loader = document.getElementById('loader-container');
  const dashboard = document.getElementById('dashboard-content');
  const toggleChartBtn = document.getElementById('toggle-chart-btn');
  const chartPanel = document.getElementById('chart-panel');

  // Load Data
  Promise.all([
    fetchJSON(HTML2_URL),
    fetchJSON(FLOORPRICE_URL)
  ])
  .then(([html2Data, floorpriceData]) => {
    loader.classList.add('hidden');
    dashboard.classList.remove('hidden');
    
    // Parse and display HTML2 stats
    renderDashboard(html2Data);
    
    // Parse history and draw chart
    processHistoryData(floorpriceData);
    drawChart('floor');
    
    // Bind chart tab clicks & toggle
    setupChartEvents();
  })
  .catch(error => {
    console.error('Data loading error:', error);
    loader.innerHTML = `
      <div style="color: var(--bg-red); font-size: 40px; margin-bottom: 10px;">⚠️</div>
      <p style="color: var(--bg-red); font-weight: bold;">データの読み込みに失敗しました。</p>
      <p style="color: #666; font-size: 12px; margin-top: 5px;">${error.message}</p>
    `;
  });

  // Fetch JSON file directly
  function fetchJSON(url) {
    return fetch(url)
      .then(response => {
        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
      });
  }

  // Render HTML2 page data to dashboard
  function renderDashboard(data) {
    // 1. Header Metadata (Issue & Time)
    const headerInfo = findHeaderInfo(data);
    setText('header-date', headerInfo.date);
    setText('header-time', headerInfo.time);
    setText('header-issue', `第${headerInfo.issue}号`);

    // Extract Floor Price dynamically to highlight minimum character price
    let globalFloorPrice = 0.0;
    const floorRow = findRowByLabel(data, '最安価格（FloorPrice）');
    if (floorRow) {
      globalFloorPrice = parseFloat(floorRow[4]);
    }

    // 2. Metrics & Subvalues
    updateRowValues(data, '最安価格（FloorPrice）', 'floor-eth', 'floor-eth-diff', 'floor-jpy', 'floor-jpy-diff');
    updateRowValues(data, '平均販売価格', 'avg-eth', 'avg-eth-diff', 'avg-jpy', 'avg-jpy-diff');
    updateRowValues(data, '時価総額（MarketCap）', 'cap-eth', 'cap-eth-diff', 'cap-jpy', 'cap-jpy-diff');
    
    // Owner & Sales counts (placed in same row)
    const ownerRow = findRowByLabel(data, 'オーナー数');
    if (ownerRow) {
      setText('owners-count', ownerRow[4]);
      setCellDiffAndBg('owners-diff', ownerRow[6]);
      
      // sales value is usually at index 10: e.g. "12件(+9)"
      setText('sales-count', ownerRow[10]);
    }

    // Listed & Rate counts
    const listedRow = findRowByLabel(data, '出品数');
    if (listedRow) {
      setText('listed-count', listedRow[4]);
      setCellDiffAndBg('listed-diff', listedRow[6]);
      setText('listed-rate', listedRow[10]);
    }

    // 3. Past Data Comparison
    updateRowValues(data, '7日前のフロア', 'past-7-eth', 'past-7-eth-diff', 'past-7-jpy', 'past-7-jpy-diff');
    updateRowValues(data, '30日前のフロア', 'past-30-eth', 'past-30-eth-diff', 'past-30-jpy', 'past-30-jpy-diff');

    // 4. Reference Prices
    updateRefRow(data, 'ETH価格', 'ref-eth', 'ref-eth-diff');
    updateRefRow(data, 'USD価格', 'ref-usd', 'ref-usd-diff');

    // 5. Character List Rows
    renderCharacterRows(data, globalFloorPrice);
  }

  // --- Helper Functions to extract & format HTML2 cell values ---

  function findHeaderInfo(data) {
    let issue = '---';
    let date = '----/--/--';
    let time = '0:00';
    
    // Scan rows for metadata
    for (let row of data) {
      const text = row.join(' ');
      
      // Issue Number
      if (text.includes('第') && text.includes('号')) {
        const match = text.match(/第(\d+)号/);
        if (match) issue = match[1];
      }
      
      // Date in brackets, e.g. 2026/6/24(水)
      const dateMatch = text.match(/\d{4}\/\d{1,2}\/\d{1,2}\([^)]+\)/);
      if (dateMatch) {
        date = dateMatch[0];
      }
      
      // Hour and Minute, e.g. 0:03
      const timeMatch = text.match(/\d{1,2}:\d{2}/);
      if (timeMatch) {
        time = timeMatch[0];
      }
    }
    
    // Fail-safe check
    if (issue === '---' && data[0] && data[0][10]) issue = data[0][10];
    
    return { issue, date, time };
  }

  function findRowByLabel(data, label) {
    return data.find(row => row[1] && row[1].trim() === label);
  }

  function findRefRowByLabel(data, label) {
    return data.find(row => row[2] && row[2].trim() === label);
  }

  function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text ? text.trim() : '';
  }

  function updateRowValues(data, label, ethId, ethDiffId, jpyId, jpyDiffId) {
    const row = findRowByLabel(data, label);
    if (!row) return;

    setText(ethId, row[4]);
    setCellDiffAndBg(ethDiffId, row[6]);
    setText(jpyId, row[8]);
    setCellDiffAndBg(jpyDiffId, row[10]);
  }

  function updateRefRow(data, label, priceId, diffId) {
    const row = findRefRowByLabel(data, label);
    if (!row) return;

    setText(priceId, row[4]);
    setCellDiffAndBg(diffId, row[6]);
  }

  function setCellDiffAndBg(id, value) {
    const el = document.getElementById(id);
    if (!el) return;

    const trimmed = value ? value.trim() : '';
    el.textContent = trimmed;
    el.className = 'diff-cell bold'; // Reset

    if (!trimmed || trimmed === '--') {
      return;
    }

    // Number extraction for positive/negative coloring
    // Matches patterns like "+0.004", "-5", "-0.056", "+1,072"
    const cleaned = trimmed.replace(/,/g, '');
    const num = parseFloat(cleaned);
    
    if (isNaN(num)) {
      if (trimmed.startsWith('-')) {
        el.classList.add('down');
      } else {
        el.classList.add('up');
      }
    } else {
      if (num >= 0) {
        el.classList.add('up');
      } else {
        el.classList.add('down');
      }
    }
  }

  function renderCharacterRows(data, globalFloorPrice) {
    const tbody = document.getElementById('character-rows');
    tbody.innerHTML = '';

    // Find the start of the character section
    const startIndex = data.findIndex(row => row[1] && row[1].trim() === 'キャラクター') + 1;
    if (startIndex <= 0) return;

    for (let i = startIndex; i < data.length; i++) {
      const row = data[i];
      // Break if we reached next section
      if (row[1] && (row[1].trim() === '過去データ' || row[1].trim() === '参考')) {
        break;
      }
      
      const charName = row[2] ? row[2].trim() : '';
      if (!charName || !charactersList.includes(charName)) continue;

      const imgUrl = charImages[charName] || '';
      const priceEth = row[4] ? row[4].trim() : '0.000';
      const priceDiff = row[6] ? row[6].trim() : '0';
      const listRate = row[8] ? row[8].trim() : '0/0.00%';
      const listDiff = row[10] ? row[10].trim() : '0/0.00%';

      const tr = document.createElement('tr');

      // 1. Character Name Cell
      const nameTd = document.createElement('td');
      nameTd.className = 'label-cell';
      const container = document.createElement('div');
      container.className = 'char-name-container';
      
      const img = document.createElement('img');
      img.src = imgUrl;
      img.className = 'char-img';
      img.alt = charName;
      
      const span = document.createElement('span');
      span.className = 'char-name-txt';
      span.textContent = charName;
      
      container.appendChild(img);
      container.appendChild(span);
      nameTd.appendChild(container);

      // 2. Price ETH Cell
      const priceTd = document.createElement('td');
      priceTd.className = 'value-cell';
      priceTd.textContent = priceEth;
      
      // Blue text highlight if matches global floor price
      const charPriceNum = parseFloat(priceEth);
      if (!isNaN(charPriceNum) && charPriceNum === globalFloorPrice) {
        priceTd.classList.add('min-price-highlight');
      }

      // 3. Price ETH Diff Cell
      const priceDiffTd = document.createElement('td');
      priceDiffTd.className = 'diff-cell bold';
      priceDiffTd.textContent = priceDiff;
      setCellColorByVal(priceDiffTd, priceDiff);

      // 4. List Rate Cell
      const listTd = document.createElement('td');
      listTd.className = 'value-cell';
      listTd.textContent = listRate;

      // 5. List Diff Cell
      const listDiffTd = document.createElement('td');
      listDiffTd.className = 'diff-cell bold';
      listDiffTd.textContent = listDiff;
      setCellColorByVal(listDiffTd, listDiff);

      tr.appendChild(nameTd);
      tr.appendChild(priceTd);
      tr.appendChild(priceDiffTd);
      tr.appendChild(listTd);
      tr.appendChild(listDiffTd);

      tbody.appendChild(tr);
    }
  }

  function setCellColorByVal(element, valString) {
    const trimmed = valString ? valString.trim() : '';
    const cleaned = trimmed.replace(/,/g, '');
    const num = parseFloat(cleaned);
    
    element.classList.remove('up', 'down', 'flat');

    if (!trimmed || trimmed === '--') {
      return;
    }

    if (isNaN(num)) {
      if (trimmed.startsWith('-')) {
        element.classList.add('down');
      } else {
        element.classList.add('up');
      }
    } else {
      if (num >= 0) {
        element.classList.add('up');
      } else {
        element.classList.add('down');
      }
    }
  }

  // --- Process and Draw history Chart ---

  function processHistoryData(data) {
    if (data.length < 6) return;

    const numCols = data[0].length;
    
    chartData.labels = [];
    chartData.floorPrices = [];
    chartData.listedCounts = [];

    // Parse columns starting from col 2 (skipping header column 0 and index column 1)
    for (let colIdx = 2; colIdx < numCols; colIdx++) {
      const dateVal = data[1][colIdx] ? data[1][colIdx].trim() : '';
      const timeVal = data[2][colIdx] ? data[2][colIdx].trim() : '';
      const floorVal = data[4][colIdx] ? parseFloat(data[4][colIdx].trim()) : null;
      const listedVal = data[5][colIdx] ? parseInt(data[5][colIdx].trim()) : null;

      if (dateVal && timeVal && !isNaN(floorVal)) {
        chartData.labels.push(`${dateVal} ${timeVal}`);
        chartData.floorPrices.push(floorVal);
        chartData.listedCounts.push(isNaN(listedVal) ? 0 : listedVal);
      }
    }

    // Filter to last 60 points for better readability
    const maxPoints = 60;
    if (chartData.labels.length > maxPoints) {
      chartData.labels = chartData.labels.slice(-maxPoints);
      chartData.floorPrices = chartData.floorPrices.slice(-maxPoints);
      chartData.listedCounts = chartData.listedCounts.slice(-maxPoints);
    }
  }

  function drawChart(type) {
    const ctx = document.getElementById('historyChart').getContext('2d');
    
    if (historyChartInstance) {
      historyChartInstance.destroy();
    }

    const isFloor = type === 'floor';
    const chartDataset = {
      label: isFloor ? 'Floor Price (ETH)' : 'Listed Items',
      data: isFloor ? chartData.floorPrices : chartData.listedCounts,
      borderColor: isFloor ? '#4a86e8' : '#e69138',
      backgroundColor: isFloor ? 'rgba(74, 134, 232, 0.05)' : 'rgba(230, 145, 56, 0.05)',
      borderWidth: 2,
      pointRadius: 2,
      pointHoverRadius: 5,
      tension: 0.3,
      fill: true
    };

    historyChartInstance = new Chart(ctx, {
      type: 'line',
      data: {
        labels: chartData.labels,
        datasets: [chartDataset]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            display: false
          },
          tooltip: {
            mode: 'index',
            intersect: false,
            backgroundColor: '#ffffff',
            titleColor: '#000000',
            bodyColor: '#333333',
            borderColor: '#cccccc',
            borderWidth: 1
          }
        },
        scales: {
          x: {
            grid: {
              color: 'rgba(0, 0, 0, 0.02)',
            },
            ticks: {
              color: '#666666',
              font: {
                size: 10
              },
              maxTicksLimit: 6
            }
          },
          y: {
            grid: {
              color: 'rgba(0, 0, 0, 0.04)',
            },
            ticks: {
              color: '#666666',
              font: {
                size: 11
              }
            }
          }
        }
      }
    });
  }

  function setupChartEvents() {
    // 1. Toggle panel collapse
    toggleChartBtn.addEventListener('click', () => {
      chartPanel.classList.toggle('hidden');
      const arrow = toggleChartBtn.querySelector('.arrow');
      if (chartPanel.classList.contains('hidden')) {
        toggleChartBtn.querySelector('span').textContent = '時系列推移グラフを表示';
        arrow.textContent = '▼';
      } else {
        toggleChartBtn.querySelector('span').textContent = '時系列推移グラフを非表示';
        arrow.textContent = '▲';
        // Redraw chart to fit dimensions when expanded
        historyChartInstance.resize();
      }
    });

    // 2. Chart tabs
    const tabs = document.querySelectorAll('.chart-tab');
    tabs.forEach(tab => {
      tab.addEventListener('click', (e) => {
        tabs.forEach(t => t.classList.remove('active'));
        e.target.classList.add('active');
        
        const chartType = e.target.getAttribute('data-chart');
        drawChart(chartType);
      });
    });
  }
});
