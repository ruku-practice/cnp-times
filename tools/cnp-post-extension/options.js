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

async function loadStoredKey() {
  const stored = await chrome.storage.local.get(API_KEY_STORAGE_KEY);
  apiKeyInput.value = stored[API_KEY_STORAGE_KEY] || '';
}

optionsForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const key = apiKeyInput.value.trim();
  if (!key) {
    setStatus('APIキーを入力してください。', 'error');
    return;
  }
  await chrome.storage.local.set({ [API_KEY_STORAGE_KEY]: key });
  setStatus('保存しました。', 'ok');
});

testBtn.addEventListener('click', async () => {
  const key = apiKeyInput.value.trim();
  if (!key) {
    setStatus('APIキーを入力してください。', 'error');
    return;
  }
  testBtn.disabled = true;
  setStatus('接続確認中...', null);
  try {
    const api = window.CnpApi.createApiClient(API_BASE_URL, () => key);
    const count = await api.testConnection();
    setStatus(`✅ 接続OK（${count}件の記事が見えています）`, 'ok');
  } catch (err) {
    console.error('[cnp-post-extension] 接続テスト失敗:', err);
    if (err.message === 'UNAUTHORIZED') {
      setStatus('APIキーを確認してください（401 Unauthorized）。', 'error');
    } else {
      setStatus('通信エラーが発生しました。ネットワーク状態を確認してください。', 'error');
    }
  } finally {
    testBtn.disabled = false;
  }
});

loadStoredKey();
