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
  if (!authHeader && !section) return;

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
      <button type="button" class="btn ghost cnp-login-btn" data-cnp-login>Discordでログイン</button>
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

  async function fetchEntry(token, date) {
    const resp = await fetch(AUTH_BASE_URL + '/api/entries/' + encodeURIComponent(date), {
      headers: { Authorization: 'Bearer ' + token }
    });
    if (resp.status === 404) return null;
    if (!resp.ok) throw new Error('api/entries/' + date + ' failed: ' + resp.status);
    return resp.json();
  }

  async function putEntry(token, date, title, bodyMd) {
    const resp = await fetch(AUTH_BASE_URL + '/api/entries/' + encodeURIComponent(date), {
      method: 'PUT',
      headers: {
        Authorization: 'Bearer ' + token,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ title, body_md: bodyMd })
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
      ? `<button type="button" class="btn cnp-editor-toggle-btn" data-cnp-editor-toggle>✏️ 記事を書く・編集</button>`
      : '';

    body.innerHTML = `
      <div class="cnp-exclusive-header">
        <span class="cnp-owner-badge">✅ ${ctx.owner ? 'CNP Owner確認済み' : 'アクセス確認済み'}</span>
        ${editorToggle}
      </div>
      <div class="cnp-entry-editor hidden" data-cnp-editor></div>
      <div class="cnp-entry-viewer" data-cnp-viewer></div>
    `;

    const editorToggleBtn = body.querySelector('[data-cnp-editor-toggle]');
    const editorEl = body.querySelector('[data-cnp-editor]');
    const viewerEl = body.querySelector('[data-cnp-viewer]');
    if (editorToggleBtn) {
      // フォームは記事本文より上（ボタン直下）に開く。長い記事の下に開くと
      // 画面上何も起きていないように見えるため（Brave等での実測不具合）。
      editorToggleBtn.addEventListener('click', () => {
        const opened = editorEl.classList.toggle('hidden') === false;
        editorToggleBtn.textContent = opened ? '✖ 編集を閉じる' : '✏️ 記事を書く・編集';
        if (opened) {
          editorEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
      });
    }

    return { viewerEl, editorEl };
  }

  function renderViewer(viewerEl, token, entries) {
    if (entries.length === 0) {
      viewerEl.innerHTML = `<p class="cnp-exclusive-msg">まだ記事がありません。分析者が記事を書くとここに表示されます。</p>`;
      return;
    }

    const options = entries
      .map((e) => `<option value="${escapeHtml(e.date)}">${escapeHtml(jpDateLabel(e.date))} - ${escapeHtml(e.title)}</option>`)
      .join('');

    viewerEl.innerHTML = `
      <div class="cnp-date-selector">
        <label for="cnp-entry-date-select">日付</label>
        <select id="cnp-entry-date-select" data-cnp-date-select>${options}</select>
      </div>
      <div class="cnp-entry-content" data-cnp-entry-content>
        <p class="cnp-exclusive-msg">読み込み中...</p>
      </div>
    `;

    const select = viewerEl.querySelector('[data-cnp-date-select]');
    const contentEl = viewerEl.querySelector('[data-cnp-entry-content]');

    async function showEntry(date) {
      contentEl.innerHTML = `<p class="cnp-exclusive-msg">読み込み中...</p>`;
      try {
        await ensureMarkdownLibs().catch(() => {});
        const entry = await fetchEntry(token, date);
        if (!entry) {
          contentEl.innerHTML = `<p class="cnp-exclusive-msg">記事が見つかりませんでした。</p>`;
          return;
        }
        contentEl.innerHTML = `
          <h3 class="cnp-exclusive-title">${escapeHtml(entry.title)}</h3>
          <p class="cnp-exclusive-updated">最終更新: ${escapeHtml(new Date(entry.updated_at).toLocaleString('ja-JP'))} ${entry.author_name ? '（' + escapeHtml(entry.author_name) + '）' : ''}</p>
          <div class="cnp-entry-body">${renderMarkdown(entry.body_md)}</div>
        `;
        await hydrateAuthedImages(token, contentEl);
      } catch (err) {
        console.error('[member.js] 記事の取得に失敗しました:', err);
        contentEl.innerHTML = `<p class="cnp-exclusive-msg">${STATUS_MESSAGES.fetch_error}</p>`;
      }
    }

    select.addEventListener('change', () => showEntry(select.value));
    // 最新（先頭 = 日付降順の1件目）を初期表示
    showEntry(entries[0].date);

    return { select, showEntry };
  }

  // --- editor用フォームの描画 ---------------------------------------------------

  function renderEditorForm(editorEl, token, state) {
    editorEl.innerHTML = `
      <div class="cnp-editor-form">
        <div class="cnp-editor-row">
          <label for="cnp-editor-date">日付</label>
          <input type="date" id="cnp-editor-date" data-cnp-field="date">
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
    const saveBtn = editorEl.querySelector('[data-cnp-save]');
    const deleteBtn = editorEl.querySelector('[data-cnp-delete]');

    dateInput.value = todayJst();

    async function loadForDate(date) {
      statusEl.textContent = '';
      try {
        const entry = await fetchEntry(token, date);
        if (entry) {
          titleInput.value = entry.title;
          bodyTextarea.value = entry.body_md;
        } else {
          titleInput.value = '';
          bodyTextarea.value = '';
        }
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

    imageInput.addEventListener('change', async () => {
      const file = imageInput.files && imageInput.files[0];
      if (!file) return;
      const ext = (file.name.split('.').pop() || '').toLowerCase();
      if (!['png', 'jpg', 'jpeg', 'gif', 'webp'].includes(ext)) {
        statusEl.textContent = STATUS_MESSAGES.file_type_error;
        imageInput.value = '';
        return;
      }
      if (file.size > 5 * 1024 * 1024) {
        statusEl.textContent = STATUS_MESSAGES.file_size_error;
        imageInput.value = '';
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
        statusEl.textContent = '画像を挿入しました。';
      } catch (err) {
        console.error('[member.js] 画像アップロードに失敗しました:', err);
        statusEl.textContent = STATUS_MESSAGES.upload_error;
      } finally {
        imageInput.value = '';
      }
    });

    saveBtn.addEventListener('click', async () => {
      const date = dateInput.value;
      const title = titleInput.value.trim();
      const bodyMd = bodyTextarea.value;
      if (!date || !title || !bodyMd.trim()) {
        statusEl.textContent = '日付・タイトル・本文をすべて入力してください。';
        return;
      }
      statusEl.textContent = '保存中...';
      saveBtn.disabled = true;
      try {
        await putEntry(token, date, title, bodyMd);
        statusEl.textContent = '保存しました。';
        if (state.onSaved) await state.onSaved(date);
      } catch (err) {
        console.error('[member.js] 保存に失敗しました:', err);
        statusEl.textContent = STATUS_MESSAGES.save_error;
      } finally {
        saveBtn.disabled = false;
      }
    });

    deleteBtn.addEventListener('click', async () => {
      const date = dateInput.value;
      if (!date) return;
      if (!window.confirm(`${date} の記事を削除します。よろしいですか？`)) return;
      statusEl.textContent = '削除中...';
      deleteBtn.disabled = true;
      try {
        await deleteEntry(token, date);
        statusEl.textContent = '削除しました。';
        titleInput.value = '';
        bodyTextarea.value = '';
        if (state.onDeleted) await state.onDeleted(date);
      } catch (err) {
        console.error('[member.js] 削除に失敗しました:', err);
        statusEl.textContent = STATUS_MESSAGES.delete_error;
      } finally {
        deleteBtn.disabled = false;
      }
    });

    return { dateInput, loadForDate };
  }

  // --- 記事ビュー全体（閲覧+editor）を組み立てる -------------------------------

  async function renderEntries(token, me) {
    if (!section) return;

    let entries;
    try {
      entries = await fetchEntries(token);
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
    const { viewerEl, editorEl } = shell;

    async function reloadViewer() {
      try {
        const list = await fetchEntries(token);
        renderViewer(viewerEl, token, list);
      } catch (err) {
        console.error('[member.js] 記事一覧の取得に失敗しました:', err);
        viewerEl.innerHTML = `<p class="cnp-exclusive-msg">${STATUS_MESSAGES.fetch_error}</p>`;
      }
    }

    if (entries === null) {
      viewerEl.innerHTML = `<p class="cnp-exclusive-msg">${STATUS_MESSAGES.fetch_error}</p>`;
    } else {
      renderViewer(viewerEl, token, entries);
    }

    if (me.editor) {
      renderEditorForm(editorEl, token, {
        onSaved: reloadViewer,
        onDeleted: reloadViewer
      });
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
      return;
    }

    try {
      const realMe = await fetchMe(token);
      if (realMe.expired) {
        // JWTが期限切れ → トークン破棄してログインボタンに戻す
        localStorage.removeItem(TOKEN_KEY);
        renderHeaderLoggedOut();
        if (section) section.classList.add('hidden');
        return;
      }

      // 記事セクションの描画は表示モード（effective owner/editor）に応じて切り替える。
      // モードセレクタ自体は realMe.editor（実際のJWTクレーム）で判定するため、
      // 非ホルダーモード中でも editor であればセレクタは出続ける。
      async function renderContentForMode(mode) {
        setViewMode(mode);
        const effectiveMe = applyViewMode(realMe, mode);
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
    }
  }

  init();
});
