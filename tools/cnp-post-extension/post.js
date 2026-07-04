// CNP TIMES 投稿ツール: post.html のフォーム制御。
// APIキーはchrome.storage.localから読み、選択テキストはchrome.storage.sessionから受け取る。

const API_BASE_URL = 'https://cnp-auth-289412336991.asia-northeast1.run.app';
const API_KEY_STORAGE_KEY = 'cnpApiKey';
const SELECTION_STORAGE_KEY = 'cnpPendingSelection';

const dateInput = document.getElementById('date-input');
const titleInput = document.getElementById('title-input');
const bodyInput = document.getElementById('body-input');
const statusMsg = document.getElementById('status-msg');
const saveBtn = document.getElementById('save-btn');
const postForm = document.getElementById('post-form');
const noKeyBanner = document.getElementById('no-key-banner');
const openOptionsLink = document.getElementById('open-options-link');
const existingBanner = document.getElementById('existing-banner');
const loadExistingBtn = document.getElementById('load-existing-btn');
const successBox = document.getElementById('success-box');

let apiKey = null;
let existingEntryCache = null; // 現在の日付でGET済みの記事（無ければnull）
let titleTouched = false; // タイトルをユーザーが手で編集したら自動抽出で上書きしない

const api = window.CnpApi.createApiClient(API_BASE_URL, () => apiKey);
const { fetchEntry, putEntry, uploadImage } = api;

function setStatus(text, kind) {
  statusMsg.textContent = text || '';
  statusMsg.classList.remove('cnp-status-error', 'cnp-status-ok');
  if (kind === 'error') statusMsg.classList.add('cnp-status-error');
  if (kind === 'ok') statusMsg.classList.add('cnp-status-ok');
}

function handleAuthError() {
  setStatus('APIキーが正しくない、または期限切れの可能性があります。設定画面を確認してください。', 'error');
  noKeyBanner.classList.remove('hidden');
}

function handleNetworkError(err) {
  cnpLogError('通信エラー', err && (err.stack || err.message || err));
  if (err && err.message === 'UNAUTHORIZED') {
    handleAuthError();
    return;
  }
  setStatus('通信エラーが発生しました。ネットワーク状態を確認してもう一度お試しください。', 'error');
}

// --- 既存記事チェック --------------------------------------------------------

async function checkExisting(date) {
  existingBanner.classList.add('hidden');
  existingEntryCache = null;
  if (!apiKey) return;
  cnpLog('既存記事チェック開始', { date });
  try {
    const entry = await fetchEntry(date);
    if (entry) {
      existingEntryCache = entry;
      existingBanner.classList.remove('hidden');
      cnpLog('既存記事チェック結果: あり', { date, title: entry.title });
    } else {
      cnpLog('既存記事チェック結果: なし', { date });
    }
  } catch (err) {
    // 既存チェックの失敗は投稿自体をブロックしない。ログのみ。
    cnpLogError('既存記事チェックに失敗', { date, error: err && (err.message || err) });
  }
}

loadExistingBtn.addEventListener('click', () => {
  if (!existingEntryCache) return;
  titleInput.value = existingEntryCache.title || '';
  bodyInput.value = existingEntryCache.body_md || '';
  titleTouched = true;
  setStatus('既存の記事内容を読み込みました。', 'ok');
});

dateInput.addEventListener('change', () => {
  checkExisting(dateInput.value);
});

// --- タイトル自動抽出 --------------------------------------------------------

function autoFillTitleFromBody() {
  if (titleTouched) return;
  const picked = window.CnpPostLogic.pickTitleLine(bodyInput.value);
  if (picked) titleInput.value = picked;
}

titleInput.addEventListener('input', () => {
  titleTouched = true;
});

bodyInput.addEventListener('input', () => {
  autoFillTitleFromBody();
});

// --- 画像ペースト ------------------------------------------------------------

const PASTE_MIME_EXT = {
  'image/png': 'png',
  'image/jpeg': 'jpg',
  'image/gif': 'gif',
  'image/webp': 'webp'
};

async function uploadAndInsert(file) {
  cnpLog('画像ペーストを検知', { fileName: file && file.name, fileType: file && file.type, fileSize: file && file.size });
  if (!apiKey) {
    setStatus('APIキーが設定されていません。設定画面でキーを保存してください。', 'error');
    cnpLog('画像アップロード中止: APIキー未設定');
    return;
  }
  setStatus('画像をアップロード中...', null);
  try {
    const { url } = await uploadImage(file);
    const insertion = `![](${url})`;
    const start = bodyInput.selectionStart ?? bodyInput.value.length;
    const end = bodyInput.selectionEnd ?? bodyInput.value.length;
    bodyInput.value = bodyInput.value.slice(0, start) + insertion + bodyInput.value.slice(end);
    const cursor = start + insertion.length;
    bodyInput.focus();
    bodyInput.setSelectionRange(cursor, cursor);
    setStatus('画像を挿入しました。', 'ok');
    cnpLog('画像アップロード成功・本文に挿入しました', { url });
  } catch (err) {
    cnpLogError('画像アップロード失敗', err && (err.message || err));
    handleNetworkError(err);
  }
}

bodyInput.addEventListener('paste', (event) => {
  const items = event.clipboardData && event.clipboardData.items;
  if (!items) return;
  for (const item of items) {
    const ext = PASTE_MIME_EXT[item.type];
    if (item.kind === 'file' && ext) {
      event.preventDefault();
      const blob = item.getAsFile();
      if (blob) {
        uploadAndInsert(new File([blob], `paste.${ext}`, { type: item.type }));
      }
      return;
    }
  }
});

// --- 保存 --------------------------------------------------------------------

postForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  cnpLog('保存ボタンが押されました');
  if (!apiKey) {
    setStatus('APIキーが設定されていません。設定画面でキーを保存してください。', 'error');
    noKeyBanner.classList.remove('hidden');
    cnpLog('保存中止: APIキー未設定');
    return;
  }

  const date = dateInput.value;
  const title = titleInput.value.trim();
  const bodyMd = bodyInput.value;
  if (!date || !title || !bodyMd.trim()) {
    setStatus('日付・タイトル・本文をすべて入力してください。', 'error');
    cnpLog('保存中止: 必須項目の未入力あり', { hasDate: !!date, hasTitle: !!title, hasBody: !!bodyMd.trim() });
    return;
  }

  saveBtn.disabled = true;
  setStatus('保存中...', null);
  try {
    // 新規記事の場合のみ posted_at（現在のJST時刻）を同梱する。
    // 既存記事があった場合はバックエンド側でposted_atが引き継がれ、上書きされない。
    const payload = { title, body_md: bodyMd };
    const isNewEntry = !existingEntryCache;
    if (isNewEntry) {
      payload.posted_at = window.CnpPostLogic.nowJstIso();
    }
    cnpLog('保存処理開始', { date, isNewEntry, titleLength: title.length, bodyLength: bodyMd.length });
    await putEntry(date, payload);
    setStatus('', null);
    postForm.classList.add('hidden');
    successBox.classList.remove('hidden');
    cnpLog('保存成功', { date });
  } catch (err) {
    cnpLogError('保存失敗', err && (err.message || err));
    handleNetworkError(err);
  } finally {
    saveBtn.disabled = false;
  }
});

openOptionsLink.addEventListener('click', (event) => {
  event.preventDefault();
  chrome.runtime.openOptionsPage();
});

// --- 初期化 -------------------------------------------------------------------

async function init() {
  cnpLog('post.js 起動（投稿フォーム表示）');

  const stored = await chrome.storage.local.get(API_KEY_STORAGE_KEY);
  apiKey = stored[API_KEY_STORAGE_KEY] || null;
  cnpLog('APIキー読み込み', { hasKey: !!apiKey, maskedKey: window.CnpLog.maskSecret(apiKey) });
  if (!apiKey) {
    noKeyBanner.classList.remove('hidden');
  }

  const session = await chrome.storage.session.get(SELECTION_STORAGE_KEY);
  const selection = session[SELECTION_STORAGE_KEY] || '';
  // 一度読み取ったら消費する（次回起動時に古い選択テキストが残らないように）
  chrome.storage.session.remove(SELECTION_STORAGE_KEY);
  cnpLog('選択テキストを受け取りました', { selectionLength: selection.length });

  dateInput.value = window.CnpPostLogic.yesterdayJst();
  bodyInput.value = selection;
  if (selection) {
    autoFillTitleFromBody();
  }

  if (apiKey) {
    checkExisting(dateInput.value);
  }
}

init().catch((err) => {
  cnpLogError('post.js 初期化処理で例外が発生しました', err && (err.stack || err.message || err));
});
