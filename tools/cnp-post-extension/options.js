// CNP TIMES 投稿ツール: options.html（APIキー設定画面）の制御。

const API_BASE_URL = 'https://cnp-auth-289412336991.asia-northeast1.run.app';
const API_KEY_STORAGE_KEY = 'cnpApiKey';

const apiKeyInput = document.getElementById('api-key-input');
const statusMsg = document.getElementById('status-msg');
const optionsForm = document.getElementById('options-form');
const testBtn = document.getElementById('test-btn');

function setStatus(text, kind) {
  statusMsg.textContent = text || '';
  statusMsg.classList.remove('cnp-status-error', 'cnp-status-ok');
  if (kind === 'error') statusMsg.classList.add('cnp-status-error');
  if (kind === 'ok') statusMsg.classList.add('cnp-status-ok');
}

const TEST_CONNECTION_TIMEOUT_MS = 20000;

async function loadStoredKey() {
  const stored = await chrome.storage.local.get(API_KEY_STORAGE_KEY);
  const key = stored[API_KEY_STORAGE_KEY] || '';
  apiKeyInput.value = key;
  cnpLog('options.js 起動', { hasStoredKey: !!key, maskedKey: window.CnpLog.maskSecret(key) });
}

optionsForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const key = apiKeyInput.value.trim();
  if (!key) {
    setStatus('APIキーを入力してください。', 'error');
    cnpLog('APIキー保存: 未入力のため中止');
    return;
  }
  await chrome.storage.local.set({ [API_KEY_STORAGE_KEY]: key });
  setStatus('保存しました。', 'ok');
  cnpLog('APIキーを保存しました', { maskedKey: window.CnpLog.maskSecret(key) });
});

testBtn.addEventListener('click', async () => {
  const key = apiKeyInput.value.trim();
  cnpLog('接続テストボタンが押されました', { maskedKey: window.CnpLog.maskSecret(key) });
  if (!key) {
    setStatus('APIキーを入力してください。', 'error');
    cnpLog('接続テスト: APIキー未入力のため中止');
    return;
  }
  // 押した瞬間に「確認中...」を出し、処理中はボタンをdisabledにして
  // 「無反応に見える」状態を防ぐ（サーバー応答が遅い場合の見え方対策）。
  testBtn.disabled = true;
  setStatus('確認中...', null);
  const startedAt = Date.now();
  try {
    const api = window.CnpApi.createApiClient(API_BASE_URL, () => key);
    const count = await api.testConnection({ timeoutMs: TEST_CONNECTION_TIMEOUT_MS });
    const elapsedMs = Date.now() - startedAt;
    setStatus(`✅ 接続OK（${count}件の記事）`, 'ok');
    cnpLog('接続テスト成功', { count, elapsedMs });
  } catch (err) {
    const elapsedMs = Date.now() - startedAt;
    cnpLogError('接続テスト失敗', { elapsedMs, error: err && (err.message || String(err)) });
    if (err && err.message === 'UNAUTHORIZED') {
      setStatus('❌ 失敗: APIキーを確認してください（401 Unauthorized）。', 'error');
    } else if (err && err.message === 'TIMEOUT') {
      setStatus('❌ 失敗: 時間切れ。ネットワークかAPIキーを確認してください。', 'error');
    } else {
      setStatus('❌ 失敗: 通信エラーが発生しました。ネットワーク状態を確認してください。', 'error');
    }
  } finally {
    testBtn.disabled = false;
  }
});

loadStoredKey();
