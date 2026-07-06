// CNP TIMES - Discord認証によるCNP Owner限定コンテンツ制御スクリプト（高機能版 advanced.html 専用）
// 設計: 設計_Discord認証.md（v2: 日次分析コメントの簡易ブログCMS）
//
// AUTH_BASE_URL が空文字の間は「未デプロイ」とみなし、ヘッダーのログインUI・
// 限定セクションともに display:none のまま何もしない（デプロイ前にpushしても表示崩れしないため）。
const AUTH_BASE_URL = "https://cnp-auth-289412336991.asia-northeast1.run.app";

document.addEventListener('DOMContentLoaded', () => {
  if (!AUTH_BASE_URL) {
    // バックエンド未設定。ヘッダー・限定セクションはHTML側の初期状態（hidden）のまま何もしない。
    return;
  }

  const TOKEN_KEY = 'cnp_auth_token';
  const VIEW_MODE_KEY = 'cnp_view_mode';

  const authHeader = document.querySelector('[data-cnp-auth-header]');
  const section = document.querySelector('[data-cnp-exclusive-section]');
  const listingsSection = document.querySelector('[data-cnp-listings-section]');
  if (!authHeader && !section && !listingsSection) return;

  // セール明細（advanced.jsが描画）もCNPホルダー限定にする。既定はロックし、
  // owner/editor 確認後にアンロックする。advanced.js より先に実行されるので、
  // ここで false にしておけば公開データが一瞬でも出ることはない。
  window.CNP_SALES_UNLOCKED = false;
  function setSalesUnlocked(unlocked) {
    window.CNP_SALES_UNLOCKED = !!unlocked;
    if (typeof window.cnpRerenderSales === 'function') window.cnpRerenderSales();
  }

  // --- 表示モード切替（editor限定・あくまで表示のシミュレーション） --------------
  // JWTやAPI権限はそのまま。描画時に使う owner/editor フラグだけをモードで上書きする。
  // - editor: 現状どおり（デフォルト）
  // - owner : CNPホルダーとしての見え方（記事は見えるが編集UIは出ない）
  // - none  : owner/editorどちらでもない人の見え方（記事セクション非表示）

  const VIEW_MODES = ['editor', 'owner', 'none'];
  const VIEW_MODE_LABELS = {
    editor: '編集者モード',
    owner: 'CNPホルダーモード',
    none: '非ホルダーモード'
  };

  function getViewMode() {
    const mode = sessionStorage.getItem(VIEW_MODE_KEY);
    return VIEW_MODES.includes(mode) ? mode : 'editor';
  }

  function setViewMode(mode) {
    if (VIEW_MODES.includes(mode)) {
      sessionStorage.setItem(VIEW_MODE_KEY, mode);
    }
  }

  // 実際のJWTクレーム（realMe）に表示モードを適用し、描画用の effective な me を返す
  function applyViewMode(realMe, mode) {
    if (mode === 'owner') {
      return Object.assign({}, realMe, { owner: true, editor: false });
    }
    if (mode === 'none') {
      return Object.assign({}, realMe, { owner: false, editor: false });
    }
    return realMe; // editor（デフォルト）はそのまま
  }

  // ヘッダーのログインUI内に表示モードセレクタを差し込む（realMe.editorがtrueの時のみ）
  function renderViewModeSelector(container, currentMode, onChange) {
    const wrap = document.createElement('span');
    wrap.className = 'cnp-view-mode-select';
    wrap.innerHTML = `
      <label for="cnp-view-mode">表示モード</label>
      <select id="cnp-view-mode" data-cnp-view-mode>
        ${VIEW_MODES.map((m) => `<option value="${m}"${m === currentMode ? ' selected' : ''}>${escapeHtml(VIEW_MODE_LABELS[m])}</option>`).join('')}
      </select>
    `;
    container.appendChild(wrap);
    const select = wrap.querySelector('[data-cnp-view-mode]');
    select.addEventListener('change', () => onChange(select.value));
    return wrap;
  }

  // --- marked.js / DOMPurify の動的ロード（AUTH_BASE_URL設定時のみ） -----------

  let mdLibsPromise = null;
  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const el = document.createElement('script');
      el.src = src;
      el.onload = () => resolve();
      el.onerror = () => reject(new Error('script load failed: ' + src));
      document.head.appendChild(el);
    });
  }
  function ensureMarkdownLibs() {
    if (!mdLibsPromise) {
      mdLibsPromise = Promise.all([
        loadScript('https://cdn.jsdelivr.net/npm/marked/marked.min.js'),
        loadScript('https://cdn.jsdelivr.net/npm/dompurify@3/dist/purify.min.js')
      ]).then(() => {
        if (window.marked && window.marked.setOptions) {
          window.marked.setOptions({ breaks: true });
        }
      });
    }
    return mdLibsPromise;
  }

  // --- URLフラグメントからトークンを取り込む -------------------------------

  function consumeAuthFragment() {
    const hash = window.location.hash;
    if (!hash || hash.indexOf('cnp_auth=') === -1 && hash.indexOf('cnp_status=') === -1) {
      return;
    }
    const params = new URLSearchParams(hash.replace(/^#/, ''));
    const token = params.get('cnp_auth');
    const status = params.get('cnp_status');

    if (token) {
      localStorage.setItem(TOKEN_KEY, token);
    }
    if (status) {
      sessionStorage.setItem('cnp_last_status', status);
    }

    // URLを掃除（フラグメントを取り除く）
    const cleanUrl = window.location.pathname + window.location.search;
    history.replaceState(null, '', cleanUrl);
  }

  consumeAuthFragment();

  // --- 共通ユーティリティ -----------------------------------------------------

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = String(str == null ? '' : str);
    return div.innerHTML;
  }

  function todayJst() {
    // JSTの「今日」を YYYY-MM-DD で返す（ブラウザのローカルタイムゾーンに関係なく、
    // UTC時刻から+9時間したものをUTCメソッドで読み出すことで一貫させる）
    const now = new Date();
    const jst = new Date(now.getTime() + 9 * 60 * 60000);
    return jst.toISOString().slice(0, 10);
  }

  function jpDateLabel(iso) {
    if (!iso) return '';
    const [y, m, d] = iso.split('-').map(Number);
    const WD = ['日', '月', '火', '水', '木', '金', '土'];
    const w = new Date(iso + 'T00:00:00').getDay();
    return `${y}年${m}月${d}日(${WD[w]})`;
  }

  // 記事ヘッダーの日時表示: Discordでの実際の発言日時（posted_at）があればそれを、
  // 無ければ掲載日ラベルを表示する
  function postedLabel(entry) {
    if (entry.posted_at) {
      const d = new Date(entry.posted_at);
      if (!isNaN(d)) {
        const WD = ['日', '月', '火', '水', '木', '金', '土'];
        // posted_atはJST（+09:00）のISO文字列。JSTの暦で表示する
        const jst = new Date(d.getTime() + (9 * 60 + d.getTimezoneOffset()) * 60000);
        const hh = String(jst.getHours()).padStart(2, '0');
        const mm = String(jst.getMinutes()).padStart(2, '0');
        return `${jst.getFullYear()}年${jst.getMonth() + 1}月${jst.getDate()}日(${WD[jst.getDay()]}) ${hh}:${mm} 投稿`;
      }
    }
    return jpDateLabel(entry.date);
  }

  const STATUS_MESSAGES = {
    no_role: 'NinjaDAOサーバーで「CNP Owner❤️」ロールが見つかりませんでした。',
    not_member: 'NinjaDAOサーバーのメンバーであることが確認できませんでした。',
    error: '認証中にエラーが発生しました。時間をおいて再度お試しください。',
    fetch_error: '記事の取得に失敗しました。時間をおいて再度お試しください。',
    save_error: '保存に失敗しました。時間をおいて再度お試しください。',
    delete_error: '削除に失敗しました。時間をおいて再度お試しください。',
    upload_error: '画像のアップロードに失敗しました。時間をおいて再度お試しください。',
    file_type_error: '対応していないファイル形式です（png/jpg/jpeg/gif/webpのみ）。',
    file_size_error: '画像サイズが5MBを超えています。'
  };

  // --- ヘッダーのログインUI -----------------------------------------------------

  function renderHeaderLoggedOut(statusMessage) {
    if (!authHeader) return;
    authHeader.classList.remove('hidden');
    const msg = statusMessage ? `<span class="cnp-header-status">${escapeHtml(statusMessage)}</span>` : '';
    authHeader.innerHTML = `
      ${msg}
      <button type="button" class="cnp-discord-login-btn" data-cnp-login>
        <svg class="cnp-discord-mark" viewBox="0 0 127.14 96.36" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path fill="currentColor" d="M107.7,8.07A105.15,105.15,0,0,0,81.47,0a72.06,72.06,0,0,0-3.36,6.83A97.68,97.68,0,0,0,49,6.83,72.37,72.37,0,0,0,45.64,0,105.89,105.89,0,0,0,19.39,8.09C2.79,32.65-1.71,56.6.54,80.21h0A105.73,105.73,0,0,0,32.71,96.36,77.7,77.7,0,0,0,39.6,85.25a68.42,68.42,0,0,1-10.85-5.18c.91-.66,1.8-1.34,2.66-2a75.57,75.57,0,0,0,64.32,0c.87.71,1.76,1.39,2.66,2a68.68,68.68,0,0,1-10.87,5.19,77,77,0,0,0,6.89,11.1A105.25,105.25,0,0,0,126.6,80.22h0C129.24,52.84,122.09,29.11,107.7,8.07ZM42.45,65.69C36.18,65.69,31,60,31,53s5-12.74,11.43-12.74S54,46,53.89,53,48.84,65.69,42.45,65.69Zm42.24,0C78.41,65.69,73.25,60,73.25,53s5-12.74,11.44-12.74S96.23,46,96.12,53,91.08,65.69,84.69,65.69Z"/></svg>
        ログイン
      </button>
    `;
    const loginBtn = authHeader.querySelector('[data-cnp-login]');
    if (loginBtn) {
      loginBtn.addEventListener('click', () => {
        window.location.href = AUTH_BASE_URL + '/login';
      });
    }
  }

  // realMe: /api/me が返した実際のクレーム。realMe.editor が true の場合のみ
  // 表示モードセレクタを出す（実権限とは無関係に描画を切り替えるためのUI）。
  function renderHeaderLoggedIn(realMe, onModeChange) {
    if (!authHeader) return;
    authHeader.classList.remove('hidden');
    authHeader.innerHTML = `
      <span class="cnp-header-name">👤 ${escapeHtml(realMe.name || '')}</span>
      <button type="button" class="btn ghost cnp-logout-btn" data-cnp-logout>ログアウト</button>
    `;
    if (realMe.editor) {
      renderViewModeSelector(authHeader, getViewMode(), onModeChange);
    }
    const logoutBtn = authHeader.querySelector('[data-cnp-logout]');
    if (logoutBtn) {
      logoutBtn.addEventListener('click', resetToLoggedOut);
    }
  }

  function resetToLoggedOut() {
    localStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(VIEW_MODE_KEY);
    if (section) section.classList.add('hidden');
    if (listingsSection) listingsSection.classList.add('hidden');
    setSalesUnlocked(false);
    renderHeaderLoggedOut();
  }

  // --- API呼び出し -----------------------------------------------------------

  async function fetchMe(token) {
    const resp = await fetch(AUTH_BASE_URL + '/api/me', {
      headers: { Authorization: 'Bearer ' + token }
    });
    if (resp.status === 401) return { expired: true };
    if (!resp.ok) throw new Error('api/me failed: ' + resp.status);
    return resp.json();
  }

  async function fetchEntries(token) {
    const resp = await fetch(AUTH_BASE_URL + '/api/entries', {
      headers: { Authorization: 'Bearer ' + token }
    });
    if (!resp.ok) throw new Error('api/entries failed: ' + resp.status);
    return resp.json();
  }

  // 記事一覧の取得を1回にまとめる（認証確認と並行して先読みし、モード切替でも再取得しない）
  let entriesPromise = null;
  function fetchEntriesCached(token, force = false) {
    if (force || !entriesPromise) {
      entriesPromise = fetchEntries(token);
      entriesPromise.catch(() => { entriesPromise = null; }); // 失敗時は次回再取得できるように
    }
    return entriesPromise;
  }

  async function fetchEntry(token, date) {
    const resp = await fetch(AUTH_BASE_URL + '/api/entries/' + encodeURIComponent(date), {
      headers: { Authorization: 'Bearer ' + token }
    });
    if (resp.status === 404) return null;
    if (!resp.ok) throw new Error('api/entries/' + date + ' failed: ' + resp.status);
    return resp.json();
  }

  // 分析コメントの本文まで横断検索する（owner/editor限定）
  async function searchEntries(token, q) {
    const resp = await fetch(AUTH_BASE_URL + '/api/entries/search?' + new URLSearchParams({ q }), {
      headers: { Authorization: 'Bearer ' + token }
    });
    if (!resp.ok) throw new Error('api/entries/search failed: ' + resp.status);
    return resp.json();
  }

  // 最安リスト トップ10 スナップショット（日付ごと・GETのみ）
  async function fetchListing(token, date) {
    const resp = await fetch(AUTH_BASE_URL + '/api/listings/' + encodeURIComponent(date), {
      headers: { Authorization: 'Bearer ' + token }
    });
    if (resp.status === 404) return null;
    if (!resp.ok) throw new Error('api/listings/' + date + ' failed: ' + resp.status);
    return resp.json();
  }

  // JSTの現在時刻を +09:00 付きISO文字列で返す（新規投稿のposted_at用）
  function nowJstIso() {
    const now = new Date();
    const jst = new Date(now.getTime() + (9 * 60 + now.getTimezoneOffset()) * 60000);
    const p = (n) => String(n).padStart(2, '0');
    return `${jst.getFullYear()}-${p(jst.getMonth() + 1)}-${p(jst.getDate())}T${p(jst.getHours())}:${p(jst.getMinutes())}:${p(jst.getSeconds())}+09:00`;
  }

  async function putEntry(token, date, title, bodyMd, isNew) {
    const payload = { title, body_md: bodyMd, source: 'web' };
    // 新規投稿時のみ、投稿日時（=Webエディタで登録した時刻）を付与する
    if (isNew) payload.posted_at = nowJstIso();
    const resp = await fetch(AUTH_BASE_URL + '/api/entries/' + encodeURIComponent(date), {
      method: 'PUT',
      headers: {
        Authorization: 'Bearer ' + token,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    });
    if (!resp.ok) {
      const errBody = await resp.json().catch(() => ({}));
      throw new Error(errBody.error || ('save failed: ' + resp.status));
    }
    return resp.json();
  }

  async function deleteEntry(token, date) {
    const resp = await fetch(AUTH_BASE_URL + '/api/entries/' + encodeURIComponent(date), {
      method: 'DELETE',
      headers: { Authorization: 'Bearer ' + token }
    });
    if (!resp.ok) throw new Error('delete failed: ' + resp.status);
    return resp.json();
  }

  async function uploadImage(token, file) {
    const form = new FormData();
    form.append('file', file);
    const resp = await fetch(AUTH_BASE_URL + '/api/images', {
      method: 'POST',
      headers: { Authorization: 'Bearer ' + token },
      body: form
    });
    if (!resp.ok) {
      const errBody = await resp.json().catch(() => ({}));
      throw new Error(errBody.error || ('upload failed: ' + resp.status));
    }
    return resp.json();
  }

  // 描画済みDOM内の /api/images/ 参照img要素を、Authorization付きfetchで
  // 取得したblobのobject URLに差し替える（<img>はAuthorizationヘッダーを送れないため）
  async function hydrateAuthedImages(token, container) {
    const imgs = Array.from(container.querySelectorAll('img[src^="/api/images/"], img[data-cnp-src]'));
    await Promise.all(imgs.map(async (img) => {
      const path = img.getAttribute('data-cnp-src') || img.getAttribute('src');
      if (!path) return;
      try {
        const resp = await fetch(AUTH_BASE_URL + path, {
          headers: { Authorization: 'Bearer ' + token }
        });
        if (!resp.ok) return;
        const blob = await resp.blob();
        img.src = URL.createObjectURL(blob);
      } catch (err) {
        console.error('[member.js] 画像の取得に失敗しました:', err);
      }
    }));
  }

  function renderMarkdown(md) {
    if (!(window.marked && window.DOMPurify)) {
      // ライブラリ未ロード時のフォールバック（プレーンテキスト表示）
      return `<pre class="cnp-entry-plain">${escapeHtml(md)}</pre>`;
    }
    const html = window.marked.parse(md || '');
    return window.DOMPurify.sanitize(html);
  }

  // --- 記事閲覧UIの描画 --------------------------------------------------------

  function renderExclusiveShell(ctx) {
    if (!section) return null;
    section.classList.remove('hidden');
    const body = section.querySelector('[data-cnp-body]');
    if (!body) return null;

    const editorToggle = ctx.editor
      ? `<span class="cnp-editor-header-actions">
           <button type="button" class="cnp-save-btn hidden" data-cnp-header-save>保存</button>
           <button type="button" class="btn cnp-editor-toggle-btn" data-cnp-editor-toggle>✏️ 記事を書く・編集</button>
         </span>`
      : '';

    body.innerHTML = `
      <div class="cnp-exclusive-header">
        <span class="cnp-owner-badge">✅ ${ctx.owner ? 'CNP Owner確認済み' : 'アクセス確認済み'}</span>
        ${editorToggle}
      </div>
      <div class="cnp-search" data-cnp-search>
        <div class="cnp-search-row">
          <input type="search" class="cnp-search-input" data-cnp-search-input placeholder="コメントを検索（例: ATH フロア）">
          <button type="button" class="btn cnp-search-btn" data-cnp-search-btn>検索</button>
          <button type="button" class="btn ghost cnp-search-clear-btn hidden" data-cnp-search-clear>クリア</button>
        </div>
        <div class="cnp-search-results hidden" data-cnp-search-results></div>
      </div>
      <div class="cnp-entry-editor hidden" data-cnp-editor></div>
      <div class="cnp-entry-viewer" data-cnp-viewer></div>
    `;

    const editorToggleBtn = body.querySelector('[data-cnp-editor-toggle]');
    const headerSaveBtn = body.querySelector('[data-cnp-header-save]');
    const editorEl = body.querySelector('[data-cnp-editor]');
    const viewerEl = body.querySelector('[data-cnp-viewer]');
    const searchEl = body.querySelector('[data-cnp-search]');
    // onOpen / onBeforeClose は renderEntries 側で差し込む（開いた時の記事読込・未保存確認）
    const shellApi = { viewerEl, editorEl, searchEl, editorToggleBtn, headerSaveBtn, onOpen: null, onBeforeClose: null };
    if (editorToggleBtn) {
      // フォームは記事本文より上（ボタン直下）に開く。長い記事の下に開くと
      // 画面上何も起きていないように見えるため（Brave等での実測不具合）。
      editorToggleBtn.addEventListener('click', () => {
        const isOpen = !editorEl.classList.contains('hidden');
        if (isOpen && shellApi.onBeforeClose && !shellApi.onBeforeClose()) return; // 未保存確認でキャンセル
        const opened = editorEl.classList.toggle('hidden') === false;
        editorToggleBtn.textContent = opened ? '✖ 編集を閉じる' : '✏️ 記事を書く・編集';
        if (headerSaveBtn) headerSaveBtn.classList.toggle('hidden', !opened);
        if (opened) {
          if (shellApi.onOpen) shellApi.onOpen();
          editorEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
      });
    }

    return shellApi;
  }

  // 閲覧ビュー: 独自のプルダウンは持たず、ページ上部の日付ナビ（#date-picker）と連動する。
  // 選択日の記事が無い場合は、それより前で直近の記事をフォールバック表示する。
  // 投稿元バッジは管理者（るくさん）にのみ表示する。source: extension/web/discord/api
  const ADMIN_USER_ID = '929922836586446878';
  const SOURCE_LABELS = {
    extension: '🔌 Chrome拡張から投稿',
    api: '🔌 API連携から投稿',
    web: '✍️ Webエディタで編集',
    discord: '🤖 Discordから自動取り込み'
  };
  function sourceBadge(entry, showSource) {
    if (!showSource) return '';
    const label = SOURCE_LABELS[entry.source] || '投稿元不明';
    return `<span class="cnp-entry-source" title="この記事の投稿元（管理者のみ表示）">${escapeHtml(label)}</span>`;
  }

  function renderViewer(viewerEl, token, entries, showSource) {
    if (entries.length === 0) {
      viewerEl.innerHTML = `<p class="cnp-exclusive-msg">まだ記事がありません。分析者が記事を書くとここに表示されます。</p>`;
      return null;
    }

    viewerEl.innerHTML = `
      <div class="cnp-entry-content" data-cnp-entry-content>
        <p class="cnp-exclusive-msg">読み込み中...</p>
      </div>
    `;

    const contentEl = viewerEl.querySelector('[data-cnp-entry-content]');
    const dates = entries.map((e) => e.date); // 日付降順
    const entryCache = {}; // 一度読んだ記事は再取得しない（日付を行き来しても即表示）
    let displayedDate = null;
    let reqSeq = 0; // 連打時に古い取得結果が新しい表示を上書きしないための連番

    async function showForDate(requestedIso) {
      // 選択日と一致する記事のみ表示（無い日は「詳細分析コメント無し」）
      const target = requestedIso
        ? (dates.includes(requestedIso) ? requestedIso : null)
        : dates[0];

      if (!target) {
        displayedDate = null;
        reqSeq += 1; // 取得中のものがあれば破棄
        contentEl.innerHTML = `<p class="cnp-exclusive-msg">${escapeHtml(jpDateLabel(requestedIso))} の詳細分析コメントはありません。</p>`;
        return;
      }
      if (target === displayedDate) return;

      const myReq = ++reqSeq;
      contentEl.innerHTML = `<p class="cnp-exclusive-msg">読み込み中...</p>`;
      try {
        await ensureMarkdownLibs().catch(() => {});
        const entry = entryCache[target] || await fetchEntry(token, target);
        if (myReq !== reqSeq) return; // より新しい表示要求が来ている → この結果は破棄
        if (!entry) {
          contentEl.innerHTML = `<p class="cnp-exclusive-msg">${escapeHtml(jpDateLabel(target))} の詳細分析コメントはありません。</p>`;
          return;
        }
        entryCache[target] = entry;
        contentEl.innerHTML = `
          <h3 class="cnp-exclusive-title">${escapeHtml(entry.title)}</h3>
          <p class="cnp-exclusive-updated">${escapeHtml(postedLabel(entry))}${sourceBadge(entry, showSource)}</p>
          <div class="cnp-entry-body">${renderMarkdown(entry.body_md)}</div>
        `;
        displayedDate = target; // 表示が完了してから確定（失敗時は次の操作で再取得される）
        await hydrateAuthedImages(token, contentEl);
      } catch (err) {
        if (myReq !== reqSeq) return;
        console.error('[member.js] 記事の取得に失敗しました:', err);
        contentEl.innerHTML = `<p class="cnp-exclusive-msg">${STATUS_MESSAGES.fetch_error}</p>`;
      }
    }

    return { showForDate, getDisplayedDate: () => displayedDate };
  }

  // snippet中の検索語をハイライトする。escapeHtml済みの文字列に対して<mark>を差し込む
  // （XSS対策のため、まずsnippet全体をエスケープしてから、エスケープ後の語で置換する）
  function highlightSnippet(snippet, terms) {
    let escaped = escapeHtml(snippet);
    const escapedTerms = terms
      .map((t) => escapeHtml(t))
      .filter((t) => t.length > 0)
      .sort((a, b) => b.length - a.length); // 長い語から置換し部分重複を避ける
    escapedTerms.forEach((term) => {
      const re = new RegExp(term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
      escaped = escaped.replace(re, (m) => `<mark>${m}</mark>`);
    });
    return escaped;
  }

  // 検索UI: 分析コメントの本文まで横断検索し、結果クリックで該当日にジャンプする
  function renderSearch(searchEl, token, onJumpToDate) {
    if (!searchEl) return;
    const input = searchEl.querySelector('[data-cnp-search-input]');
    const searchBtn = searchEl.querySelector('[data-cnp-search-btn]');
    const clearBtn = searchEl.querySelector('[data-cnp-search-clear]');
    const resultsEl = searchEl.querySelector('[data-cnp-search-results]');
    if (!input || !searchBtn || !clearBtn || !resultsEl) return;

    let reqSeq = 0;

    function clearResults() {
      resultsEl.classList.add('hidden');
      resultsEl.innerHTML = '';
      clearBtn.classList.add('hidden');
    }

    function clearAll() {
      input.value = '';
      clearResults();
    }

    async function runSearch() {
      const q = input.value.trim();
      if (!q) {
        clearResults();
        return;
      }
      const myReq = ++reqSeq;
      resultsEl.classList.remove('hidden');
      clearBtn.classList.remove('hidden');
      resultsEl.innerHTML = `<p class="cnp-exclusive-msg">検索中...</p>`;
      try {
        const { results } = await searchEntries(token, q);
        if (myReq !== reqSeq) return;
        if (!results || results.length === 0) {
          resultsEl.innerHTML = `<p class="cnp-exclusive-msg">一致するコメントはありませんでした。</p>`;
          return;
        }
        const terms = q.split(/\s+/).filter(Boolean);
        resultsEl.innerHTML = `
          <ul class="cnp-search-result-list">
            ${results.map((r) => `
              <li class="cnp-search-result-item" data-cnp-search-result data-date="${escapeHtml(r.date)}">
                <span class="cnp-search-result-date">${escapeHtml(jpDateLabel(r.date))}</span>
                <span class="cnp-search-result-title">${escapeHtml(r.title)}</span>
                <span class="cnp-search-result-snippet">${highlightSnippet(r.snippet, terms)}</span>
              </li>
            `).join('')}
          </ul>
        `;
        resultsEl.querySelectorAll('[data-cnp-search-result]').forEach((li) => {
          li.addEventListener('click', () => {
            const date = li.getAttribute('data-date');
            if (date) onJumpToDate(date);
          });
        });
      } catch (err) {
        if (myReq !== reqSeq) return;
        console.error('[member.js] コメントの検索に失敗しました:', err);
        resultsEl.innerHTML = `<p class="cnp-exclusive-msg">${STATUS_MESSAGES.fetch_error}</p>`;
      }
    }

    searchBtn.addEventListener('click', runSearch);
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        runSearch();
      }
    });
    clearBtn.addEventListener('click', clearAll);
  }

  // ページ上部の日付ナビ（advanced.js の #date-picker と◀▶ボタン）に連動フックを張る。
  // ボタンはプログラム的にpickerの値を変える（changeが飛ばない）ため、クリックにも反応する。
  function hookDateNav(onDateChange) {
    const picker = document.getElementById('date-picker');
    if (!picker) return;
    const fire = () => setTimeout(() => { if (picker.value) onDateChange(picker.value); }, 0);
    picker.addEventListener('change', fire);
    ['date-prev', 'date-next', 'date-latest'].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.addEventListener('click', fire);
    });
    // 保険: イベントを取りこぼす経路（プログラム的な値変更等）があっても追従できるよう、
    // pickerの値の変化を定期監視する
    let lastSeen = picker.value;
    setInterval(() => {
      if (picker.value && picker.value !== lastSeen) {
        lastSeen = picker.value;
        onDateChange(picker.value);
      }
    }, 700);
  }

  // pickerの初期値はデータ読込後にadvanced.jsが設定するため、値が入るまで待つ（最大15秒）
  function waitForPickerValue(cb) {
    const picker = document.getElementById('date-picker');
    if (picker && picker.value) { cb(picker.value); return; }
    let tries = 0;
    const t = setInterval(() => {
      tries += 1;
      if (picker && picker.value) { clearInterval(t); cb(picker.value); }
      else if (tries > 50 || !picker) { clearInterval(t); cb(null); } // 諦めて最新記事を表示
    }, 300);
  }

  // --- 最安リスト トップ10（CNP Owner限定・日次スナップショット）の描画 ------------
  // 分析コメントと同様、独自プルダウンは持たず #date-picker と連動する。取得結果は
  // 日付ごとにキャッシュし、選択日に無ければ「この日のリスト記録はありません」と表示する。

  function formatEth(v) {
    if (v == null) return '-';
    return String(v);
  }

  function formatJpy(v) {
    if (v == null) return '-';
    return '¥' + Number(v).toLocaleString('ja-JP');
  }

  function walletLabel(item) {
    // ニックネーム（OpenSea由来）があればそれを、無ければ短縮アドレスを表示する
    if (!item.wallet) return '不明';
    return item.wallet_name ? item.wallet_name : short_addr_js(item.wallet);
  }

  function short_addr_js(addr) {
    if (!addr || addr.length < 10) return addr || '';
    return addr.slice(0, 6) + '…' + addr.slice(-4);
  }

  function priceHistoryLabel(history) {
    if (!Array.isArray(history) || history.length < 2) return '-';
    return history.map((h) => formatEth(h.price)).join('→');
  }

  // NFT個別ページはOpenSeaを見にいく（ユーザー指示）
  const CNP_CONTRACT = '0x138A5C693279b6Cd82F48d4bEf563251Bc15ADcE';

  function renderListingsRow(item) {
    const nftUrl = item.token
      ? `https://opensea.io/item/ethereum/${CNP_CONTRACT}/${encodeURIComponent(item.token)}`
      : null;
    const walletUrl = item.wallet ? `https://opensea.io/ja/${encodeURIComponent(item.wallet)}` : null;
    const walletCell = walletUrl
      ? `<a href="${walletUrl}" target="_blank" rel="noopener">${escapeHtml(walletLabel(item))}</a>`
      : escapeHtml(walletLabel(item));
    const firstSeen = item.first_seen_date
      ? `${escapeHtml(jpDateLabel(item.first_seen_date))}${item.price_history && item.price_history[0] ? '　' + formatEth(item.price_history[0].price) + ' ETH' : ''}`
      : '-';
    return `
      <tr>
        <td class="cnp-listings-nft">
          ${nftUrl ? `<a href="${nftUrl}" target="_blank" rel="noopener" title="OpenSeaで#${escapeHtml(item.token)}を見る" class="charcell">` : '<div class="charcell">'}
            <img src="${escapeHtml(item.image || '')}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">
            <span>#${escapeHtml(item.token)}${item.character ? '　' + escapeHtml(item.character) : ''}</span>
          ${nftUrl ? '</a>' : '</div>'}
        </td>
        <td class="mono">
          ${formatEth(item.price_eth)} ETH<br><span class="cnp-listings-jpy">${formatJpy(item.price_jpy)}</span>
        </td>
        <td>${walletCell}</td>
        <td class="mono">
          リスト ${item.wallet_listing_count != null ? item.wallet_listing_count : '-'}件<br>
          保有 ${item.wallet_cnp_total != null ? item.wallet_cnp_total : '-'}体
        </td>
        <td>${firstSeen}</td>
        <td class="mono">${escapeHtml(priceHistoryLabel(item.price_history))}</td>
      </tr>
    `;
  }

  function renderListingsSnapshot(bodyEl, snapshot, requestedIso) {
    if (!snapshot) {
      bodyEl.innerHTML = `<p class="cnp-exclusive-msg">${escapeHtml(jpDateLabel(requestedIso))} のリスト記録はありません。</p>`;
      return;
    }
    const rows = (snapshot.items || []).map(renderListingsRow).join('');
    // リスト数の集計範囲（例 top40 → 上位40位以内）をヘッダに1回だけ注記する
    const scopeItem = (snapshot.items || []).find((it) => it.wallet_listing_count_scope);
    const scopeNote = scopeItem
      ? `<br><span class="cnp-listings-scope-note">（リスト数は上位${escapeHtml(String(scopeItem.wallet_listing_count_scope).replace('top', ''))}位以内）</span>`
      : '';
    bodyEl.innerHTML = `
      <p class="cnp-listings-summary">${escapeHtml(jpDateLabel(snapshot.date))} 時点（総リスト${escapeHtml(String(snapshot.total_listed != null ? snapshot.total_listed : '-'))}件）</p>
      <div class="cnp-listings-table-wrap">
        <table class="t cnp-listings-table">
          <thead>
            <tr>
              <th>画像/番号/キャラ</th>
              <th>価格</th>
              <th>ウォレット</th>
              <th>リスト数・保有数${scopeNote}</th>
              <th>最初のリスト</th>
              <th>価格履歴</th>
            </tr>
          </thead>
          <tbody>${rows || '<tr><td colspan="6" class="cnp-exclusive-msg">リストがありません。</td></tr>'}</tbody>
        </table>
      </div>
    `;
  }

  function renderListingsViewer(bodyEl, token) {
    const cache = {}; // date -> snapshot|null
    let displayedDate = null;
    let reqSeq = 0;

    async function showForDate(requestedIso) {
      if (!requestedIso || requestedIso === displayedDate) return;
      const myReq = ++reqSeq;
      bodyEl.innerHTML = `<p class="cnp-exclusive-msg">読み込み中...</p>`;
      try {
        const snapshot = Object.prototype.hasOwnProperty.call(cache, requestedIso)
          ? cache[requestedIso]
          : await fetchListing(token, requestedIso);
        if (myReq !== reqSeq) return; // より新しい表示要求が来ている → 破棄
        cache[requestedIso] = snapshot;
        renderListingsSnapshot(bodyEl, snapshot, requestedIso);
        displayedDate = requestedIso;
      } catch (err) {
        if (myReq !== reqSeq) return;
        console.error('[member.js] 最安リストの取得に失敗しました:', err);
        bodyEl.innerHTML = `<p class="cnp-exclusive-msg">${STATUS_MESSAGES.fetch_error}</p>`;
      }
    }

    return { showForDate };
  }

  // 表示モード（owner/editor/none）に応じてセクションの表示可否を切り替え、
  // 表示する場合は日付ナビに連動させる。呼び出しは限定コンテンツ全体の描画と合わせて行う。
  function renderListings(token, me) {
    if (!listingsSection) return;
    if (!me.owner && !me.editor) {
      listingsSection.classList.add('hidden');
      return;
    }
    listingsSection.classList.remove('hidden');
    const bodyEl = listingsSection.querySelector('[data-cnp-listings-body]');
    if (!bodyEl) return;

    const viewerApi = renderListingsViewer(bodyEl, token);
    const applyDate = (iso) => { if (iso) viewerApi.showForDate(iso); };
    hookDateNav(applyDate);
    waitForPickerValue(applyDate);
  }

  // --- editor用フォームの描画 ---------------------------------------------------

  function yesterdayJst() {
    // 掲載日=投稿日の前日ルールに合わせ、JSTの「昨日」を YYYY-MM-DD で返す
    // （todayJstと同じく、ブラウザのタイムゾーンに依存しないようUTC+9時間で計算）
    const now = new Date();
    const jst = new Date(now.getTime() + 9 * 60 * 60000 - 24 * 60 * 60 * 1000);
    return jst.toISOString().slice(0, 10);
  }

  function renderEditorForm(editorEl, token, state) {
    editorEl.innerHTML = `
      <div class="cnp-editor-form">
        <div class="cnp-editor-row">
          <label for="cnp-editor-date">日付</label>
          <input type="date" id="cnp-editor-date" data-cnp-field="date">
          <p class="cnp-editor-hint">日付を変えると、その日付の記事の編集（記事があれば読み込み）／新規作成になります。</p>
        </div>
        <div class="cnp-editor-row">
          <label for="cnp-editor-title">タイトル</label>
          <input type="text" id="cnp-editor-title" data-cnp-field="title" placeholder="タイトル">
        </div>
        <div class="cnp-editor-row">
          <label for="cnp-editor-body">本文（Markdown）</label>
          <textarea id="cnp-editor-body" data-cnp-field="body" rows="12" placeholder="本文をMarkdownで入力"></textarea>
        </div>
        <div class="cnp-editor-toolbar">
          <label class="cnp-image-upload-btn">
            🖼️ 画像を挿入
            <input type="file" accept=".png,.jpg,.jpeg,.gif,.webp" data-cnp-image-input hidden>
          </label>
          <button type="button" class="cnp-preview-toggle-btn" data-cnp-preview-toggle>👁️ プレビュー</button>
          <button type="button" class="cnp-save-btn" data-cnp-save>保存</button>
          <button type="button" class="cnp-delete-btn" data-cnp-delete>削除</button>
        </div>
        <div class="cnp-editor-preview hidden" data-cnp-preview></div>
        <p class="cnp-editor-status" data-cnp-editor-status></p>
        <div class="cnp-editor-actions">
          <button type="button" class="cnp-save-btn" data-cnp-save>保存</button>
          <button type="button" class="cnp-delete-btn" data-cnp-delete>削除</button>
        </div>
      </div>
    `;

    const dateInput = editorEl.querySelector('[data-cnp-field="date"]');
    const titleInput = editorEl.querySelector('[data-cnp-field="title"]');
    const bodyTextarea = editorEl.querySelector('[data-cnp-field="body"]');
    const imageInput = editorEl.querySelector('[data-cnp-image-input]');
    const previewToggleBtn = editorEl.querySelector('[data-cnp-preview-toggle]');
    const previewEl = editorEl.querySelector('[data-cnp-preview]');
    const statusEl = editorEl.querySelector('[data-cnp-editor-status]');
    const saveBtns = Array.from(editorEl.querySelectorAll('[data-cnp-save]'));
    const deleteBtns = Array.from(editorEl.querySelectorAll('[data-cnp-delete]'));

    // 未保存の変更トラッキング（閉じる時の確認に使う）
    let dirty = false;
    let entryExists = false; // 現在の日付に既存記事があるか（保存時の新規判定用）
    const markDirty = () => { dirty = true; };
    titleInput.addEventListener('input', markDirty);
    bodyTextarea.addEventListener('input', markDirty);

    // 初期日付: 表示中の記事があればその日付（＝その記事の編集から始まる）、
    // 無ければ昨日（掲載日=投稿日の前日ルール）
    dateInput.value = state.initialDate || yesterdayJst();

    async function loadForDate(date) {
      statusEl.textContent = '';
      try {
        const entry = await fetchEntry(token, date);
        entryExists = !!entry; // 新規/既存を保存時のsource・posted_at判定に使う
        if (entry) {
          titleInput.value = entry.title;
          bodyTextarea.value = entry.body_md;
        } else {
          titleInput.value = '';
          bodyTextarea.value = '';
        }
        dirty = false; // 読み込み直後は未編集状態
      } catch (err) {
        console.error('[member.js] 編集用記事の取得に失敗しました:', err);
        statusEl.textContent = STATUS_MESSAGES.fetch_error;
      }
    }

    dateInput.addEventListener('change', () => loadForDate(dateInput.value));
    loadForDate(dateInput.value);

    previewToggleBtn.addEventListener('click', async () => {
      const showing = !previewEl.classList.contains('hidden');
      if (showing) {
        previewEl.classList.add('hidden');
        return;
      }
      await ensureMarkdownLibs().catch(() => {});
      previewEl.innerHTML = renderMarkdown(bodyTextarea.value);
      await hydrateAuthedImages(token, previewEl);
      previewEl.classList.remove('hidden');
    });

    // 画像をアップロードしてカーソル位置にMarkdownを挿入する（ファイル選択・ペースト共通）
    async function uploadAndInsert(file) {
      const ext = (file.name.split('.').pop() || '').toLowerCase();
      if (!['png', 'jpg', 'jpeg', 'gif', 'webp'].includes(ext)) {
        statusEl.textContent = STATUS_MESSAGES.file_type_error;
        return;
      }
      if (file.size > 5 * 1024 * 1024) {
        statusEl.textContent = STATUS_MESSAGES.file_size_error;
        return;
      }
      statusEl.textContent = 'アップロード中...';
      try {
        const { url } = await uploadImage(token, file);
        const insertion = `![](${url})`;
        const start = bodyTextarea.selectionStart ?? bodyTextarea.value.length;
        const end = bodyTextarea.selectionEnd ?? bodyTextarea.value.length;
        bodyTextarea.value = bodyTextarea.value.slice(0, start) + insertion + bodyTextarea.value.slice(end);
        bodyTextarea.focus();
        const cursor = start + insertion.length;
        bodyTextarea.setSelectionRange(cursor, cursor);
        dirty = true; // プログラム挿入はinputイベントが飛ばないため明示
        statusEl.textContent = '画像を挿入しました。';
      } catch (err) {
        console.error('[member.js] 画像アップロードに失敗しました:', err);
        statusEl.textContent = STATUS_MESSAGES.upload_error;
      }
    }

    imageInput.addEventListener('change', async () => {
      const file = imageInput.files && imageInput.files[0];
      if (!file) return;
      await uploadAndInsert(file);
      imageInput.value = '';
    });

    // クリップボードの画像を本文欄に直接ペースト（スクショ等をCmd/Ctrl+Vで挿入）
    const PASTE_MIME_EXT = { 'image/png': 'png', 'image/jpeg': 'jpg', 'image/gif': 'gif', 'image/webp': 'webp' };
    bodyTextarea.addEventListener('paste', (e) => {
      const items = e.clipboardData && e.clipboardData.items;
      if (!items) return;
      for (const item of items) {
        const ext = PASTE_MIME_EXT[item.type];
        if (item.kind === 'file' && ext) {
          e.preventDefault(); // 画像バイナリの文字列表現が貼られるのを防ぐ
          const blob = item.getAsFile();
          if (blob) {
            // ペースト画像はファイル名が無い/不定のため、MIMEから拡張子を確定させて渡す
            uploadAndInsert(new File([blob], `paste.${ext}`, { type: item.type }));
          }
          return;
        }
      }
    });

    async function doSave() {
      const date = dateInput.value;
      const title = titleInput.value.trim();
      const bodyMd = bodyTextarea.value;
      if (!date || !title || !bodyMd.trim()) {
        statusEl.textContent = '日付・タイトル・本文をすべて入力してください。';
        return;
      }
      statusEl.textContent = '保存中...';
      saveBtns.forEach((b) => { b.disabled = true; });
      try {
        await putEntry(token, date, title, bodyMd, !entryExists);
        entryExists = true;
        dirty = false;
        statusEl.textContent = '保存しました。';
        if (state.onSaved) await state.onSaved(date);
      } catch (err) {
        console.error('[member.js] 保存に失敗しました:', err);
        statusEl.textContent = STATUS_MESSAGES.save_error;
      } finally {
        saveBtns.forEach((b) => { b.disabled = false; });
      }
    }

    async function doDelete() {
      const date = dateInput.value;
      if (!date) return;
      if (!window.confirm(`${date} の記事を削除します。よろしいですか？`)) return;
      statusEl.textContent = '削除中...';
      deleteBtns.forEach((b) => { b.disabled = true; });
      try {
        await deleteEntry(token, date);
        dirty = false;
        statusEl.textContent = '削除しました。';
        titleInput.value = '';
        bodyTextarea.value = '';
        if (state.onDeleted) await state.onDeleted(date);
      } catch (err) {
        console.error('[member.js] 削除に失敗しました:', err);
        statusEl.textContent = STATUS_MESSAGES.delete_error;
      } finally {
        deleteBtns.forEach((b) => { b.disabled = false; });
      }
    }

    saveBtns.forEach((b) => b.addEventListener('click', doSave));
    deleteBtns.forEach((b) => b.addEventListener('click', doDelete));

    return { dateInput, loadForDate, save: doSave, isDirty: () => dirty };
  }

  // --- 記事ビュー全体（閲覧+editor）を組み立てる -------------------------------

  async function renderEntries(token, me) {
    if (!section) return;

    let entries;
    try {
      entries = await fetchEntriesCached(token);
    } catch (err) {
      console.error('[member.js] 記事一覧の取得に失敗しました:', err);
      entries = null;
    }

    // 記事が無い、かつeditorでもない場合はセクション自体を表示しない
    if (!me.editor && (!entries || entries.length === 0)) {
      section.classList.add('hidden');
      return;
    }

    const shell = renderExclusiveShell({ owner: me.owner, editor: me.editor });
    if (!shell) return;
    const { viewerEl, editorEl, searchEl } = shell;

    // 上部の日付ナビと連動するビューア。保存・削除後の再描画でもフックを張り直さないよう
    // viewerApi を差し替える形にする
    let viewerApi = null;
    let currentIso = null; // 日付ナビで現在選ばれている日付

    const applyDate = (iso) => {
      currentIso = iso || currentIso;
      if (viewerApi) viewerApi.showForDate(currentIso);
    };

    // 検索結果クリック時: ページ上部の日付ピッカーの値をその日付にしてchangeイベントを
    // 発火させる（hookDateNav経由で分析コメント表示がその日に切り替わる）
    function jumpToDate(date) {
      const picker = document.getElementById('date-picker');
      if (!picker) return;
      picker.value = date;
      picker.dispatchEvent(new Event('change'));
    }

    renderSearch(searchEl, token, jumpToDate);

    async function reloadViewer() {
      try {
        const list = await fetchEntriesCached(token, true); // 保存・削除後は取り直す
        viewerApi = renderViewer(viewerEl, token, list, me.editor && me.id === ADMIN_USER_ID);
        if (viewerApi) viewerApi.showForDate(currentIso);
      } catch (err) {
        console.error('[member.js] 記事一覧の取得に失敗しました:', err);
        viewerEl.innerHTML = `<p class="cnp-exclusive-msg">${STATUS_MESSAGES.fetch_error}</p>`;
      }
    }

    if (entries === null) {
      viewerEl.innerHTML = `<p class="cnp-exclusive-msg">${STATUS_MESSAGES.fetch_error}</p>`;
    } else {
      viewerApi = renderViewer(viewerEl, token, entries, me.editor && me.id === ADMIN_USER_ID);
    }

    hookDateNav(applyDate);
    waitForPickerValue(applyDate);

    if (me.editor) {
      const editorApi = renderEditorForm(editorEl, token, {
        initialDate: entries && entries.length > 0 ? entries[0].date : null,
        onSaved: reloadViewer,
        onDeleted: reloadViewer
      });

      // フォームを開いたとき、いま表示中の記事を読み込む（「表示中の記事を編集する」体験にする）
      shell.onOpen = () => {
        const current = (viewerApi && viewerApi.getDisplayedDate()) || currentIso;
        if (current && current !== editorApi.dateInput.value) {
          editorApi.dateInput.value = current;
          editorApi.loadForDate(current);
        }
      };
      // 未保存の変更があるまま閉じようとしたら確認する（閉じるだけでは保存されないため）
      shell.onBeforeClose = () =>
        !editorApi.isDirty() || window.confirm('保存されていない変更があります。保存せずに閉じますか？');
      // ヘッダー側（「編集を閉じる」の左隣）の保存ボタン
      if (shell.headerSaveBtn) {
        shell.headerSaveBtn.addEventListener('click', () => editorApi.save());
      }
    }
  }

  // --- 初期化 -------------------------------------------------------------

  async function init() {
    const lastStatus = sessionStorage.getItem('cnp_last_status');
    sessionStorage.removeItem('cnp_last_status'); // 一度表示したら消す（リロードでログインボタンに戻れるように）
    const token = localStorage.getItem(TOKEN_KEY);

    if (!token) {
      renderHeaderLoggedOut(lastStatus && STATUS_MESSAGES[lastStatus] ? STATUS_MESSAGES[lastStatus] : null);
      if (section) section.classList.add('hidden');
      if (listingsSection) listingsSection.classList.add('hidden');
      return;
    }

    // 体感速度向上: 認証確認を待たずに箱と「読み込み中」を先に出し、
    // 記事一覧・Markdownライブラリも並行して先読みする（非ownerだった場合は後で隠す）
    if (section) {
      section.classList.remove('hidden');
      const body = section.querySelector('[data-cnp-body]');
      if (body) body.innerHTML = `<p class="cnp-exclusive-msg">読み込み中...</p>`;
    }
    if (listingsSection) {
      listingsSection.classList.remove('hidden');
      const lbody = listingsSection.querySelector('[data-cnp-listings-body]');
      if (lbody) lbody.innerHTML = `<p class="cnp-exclusive-msg">読み込み中...</p>`;
    }
    fetchEntriesCached(token);
    ensureMarkdownLibs().catch(() => {});

    try {
      const realMe = await fetchMe(token);
      if (realMe.expired) {
        // JWTが期限切れ → トークン破棄してログインボタンに戻す
        localStorage.removeItem(TOKEN_KEY);
        renderHeaderLoggedOut();
        if (section) section.classList.add('hidden');
        if (listingsSection) listingsSection.classList.add('hidden');
        setSalesUnlocked(false);
        return;
      }

      // 記事セクションの描画は表示モード（effective owner/editor）に応じて切り替える。
      // モードセレクタ自体は realMe.editor（実際のJWTクレーム）で判定するため、
      // 非ホルダーモード中でも editor であればセレクタは出続ける。
      async function renderContentForMode(mode) {
        setViewMode(mode);
        const effectiveMe = applyViewMode(realMe, mode);
        setSalesUnlocked(effectiveMe.owner || effectiveMe.editor); // セール明細もホルダー限定
        renderListings(token, effectiveMe);
        if (!effectiveMe.owner && !effectiveMe.editor) {
          if (section) section.classList.add('hidden');
          return;
        }
        await renderEntries(token, effectiveMe);
      }

      renderHeaderLoggedIn(realMe, (mode) => {
        renderContentForMode(mode);
      });

      // モード切替UIはeditor限定のため、editorでない場合は常に実権限どおり（editorモード相当）で描画する
      await renderContentForMode(realMe.editor ? getViewMode() : 'editor');
    } catch (err) {
      console.error('[member.js] 限定コンテンツの取得に失敗しました:', err);
      renderHeaderLoggedOut(STATUS_MESSAGES.error);
      if (section) section.classList.add('hidden');
      if (listingsSection) listingsSection.classList.add('hidden');
    }
  }

  init();
});
