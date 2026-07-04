// CNP TIMES 投稿ツール: バックエンドAPI呼び出しをまとめたモジュール。
// post.js / options.js から読み込む。DOMや chrome.* に依存しないため、
// fetchをモックしたnodeテスト（test_api.mjs）で動作を検証できる。

function createApiClient(baseUrl, getApiKey) {
  function headers(extra) {
    return Object.assign({ 'X-Api-Key': getApiKey() || '' }, extra || {});
  }

  async function fetchEntry(date) {
    const resp = await fetch(`${baseUrl}/api/entries/${encodeURIComponent(date)}`, {
      headers: headers()
    });
    if (resp.status === 404) return null;
    if (resp.status === 401) throw new Error('UNAUTHORIZED');
    if (!resp.ok) throw new Error('FETCH_FAILED');
    return resp.json();
  }

  async function putEntry(date, payload) {
    const resp = await fetch(`${baseUrl}/api/entries/${encodeURIComponent(date)}`, {
      method: 'PUT',
      headers: headers({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(payload)
    });
    if (resp.status === 401) throw new Error('UNAUTHORIZED');
    if (!resp.ok) {
      const errBody = await resp.json().catch(() => ({}));
      throw new Error(errBody.error || `SAVE_FAILED_${resp.status}`);
    }
    return resp.json();
  }

  async function uploadImage(file) {
    const form = new FormData();
    form.append('file', file);
    const resp = await fetch(`${baseUrl}/api/images`, {
      method: 'POST',
      headers: headers(),
      body: form
    });
    if (resp.status === 401) throw new Error('UNAUTHORIZED');
    if (!resp.ok) {
      const errBody = await resp.json().catch(() => ({}));
      throw new Error(errBody.error || `UPLOAD_FAILED_${resp.status}`);
    }
    return resp.json();
  }

  async function testConnection() {
    const resp = await fetch(`${baseUrl}/api/entries`, { headers: headers() });
    if (resp.status === 401) throw new Error('UNAUTHORIZED');
    if (!resp.ok) throw new Error(`HTTP_${resp.status}`);
    const items = await resp.json();
    return Array.isArray(items) ? items.length : 0;
  }

  return { fetchEntry, putEntry, uploadImage, testConnection };
}

const CnpApi = { createApiClient };

if (typeof module !== 'undefined' && module.exports) {
  module.exports = CnpApi;
}
if (typeof window !== 'undefined') {
  window.CnpApi = CnpApi;
}
