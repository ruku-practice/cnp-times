// CNP TIMES 投稿ツール: バックエンドAPI呼び出しをまとめたモジュール。
// post.js / options.js から読み込む。DOMや chrome.* に依存しないため、
// fetchをモックしたnodeテスト（test_api.mjs）で動作を検証できる。

// log.js のcnpLog/cnpLogErrorをブラウザ・node両方から参照できるようにする。
// ブラウザではlog.jsが先に読み込まれてwindow.cnpLog等を作るのでそれを使う。
// node（test_api.mjs）ではlog.jsをrequireしていないため、ここでフォールバックを用意する。
/* global module, window, self */
const _cnpLogFns = (() => {
  if (typeof window !== 'undefined' && window.cnpLog) {
    return { cnpLog: window.cnpLog, cnpLogError: window.cnpLogError, maskSecret: window.CnpLog.maskSecret };
  }
  if (typeof self !== 'undefined' && self.cnpLog) {
    return { cnpLog: self.cnpLog, cnpLogError: self.cnpLogError, maskSecret: self.CnpLog.maskSecret };
  }
  if (typeof module !== 'undefined' && module.exports) {
    try {
      // eslint-disable-next-line global-require
      const path = require('path');
      // eslint-disable-next-line global-require
      const logMod = require(path.join(__dirname, 'log.js'));
      return { cnpLog: logMod.cnpLog, cnpLogError: logMod.cnpLogError, maskSecret: logMod.maskSecret };
    } catch (_err) {
      // requireできない環境（ブラウザのモジュールバンドル等）向けの最終フォールバック。
    }
  }
  const noop = () => {};
  return { cnpLog: noop, cnpLogError: noop, maskSecret: (v) => (v ? '***' : '(未設定)') };
})();
const { cnpLog, cnpLogError } = _cnpLogFns;

const DEFAULT_TIMEOUT_MS = 20000;

function createApiClient(baseUrl, getApiKey) {
  function headers(extra) {
    return Object.assign({ 'X-Api-Key': getApiKey() || '' }, extra || {});
  }

  // fetchの開始・終了（所要ms・ステータス）を必ずログに残す共通ラッパー。
  // timeoutMsを指定するとAbortControllerでタイムアウトさせ、TIMEOUTエラーを投げる。
  async function loggedFetch(method, url, options, timeoutMs) {
    const startedAt = Date.now();
    cnpLog(`API呼び出し開始: ${method} ${url}`);

    let controller = null;
    let timeoutId = null;
    const fetchOptions = Object.assign({}, options);
    if (timeoutMs && typeof AbortController !== 'undefined') {
      controller = new AbortController();
      fetchOptions.signal = controller.signal;
      timeoutId = setTimeout(() => controller.abort(), timeoutMs);
    }

    try {
      const resp = await fetch(url, fetchOptions);
      const elapsedMs = Date.now() - startedAt;
      cnpLog(`API呼び出し完了: ${method} ${url}`, { status: resp.status, elapsedMs });
      return resp;
    } catch (err) {
      const elapsedMs = Date.now() - startedAt;
      const isAbort = err && (err.name === 'AbortError');
      if (isAbort) {
        cnpLogError(`API呼び出しタイムアウト: ${method} ${url}`, { elapsedMs, timeoutMs });
        throw new Error('TIMEOUT');
      }
      cnpLogError(`API呼び出し失敗（例外）: ${method} ${url}`, { elapsedMs, error: err && (err.message || String(err)) });
      throw err;
    } finally {
      if (timeoutId) clearTimeout(timeoutId);
    }
  }

  async function fetchEntry(date) {
    const url = `${baseUrl}/api/entries/${encodeURIComponent(date)}`;
    const resp = await loggedFetch('GET', url, { headers: headers() });
    if (resp.status === 404) {
      cnpLog('fetchEntry: 該当日付の記事は無し（404）', { date });
      return null;
    }
    if (resp.status === 401) throw new Error('UNAUTHORIZED');
    if (!resp.ok) throw new Error('FETCH_FAILED');
    return resp.json();
  }

  async function putEntry(date, payload) {
    const url = `${baseUrl}/api/entries/${encodeURIComponent(date)}`;
    const resp = await loggedFetch('PUT', url, {
      method: 'PUT',
      headers: headers({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(payload)
    });
    if (resp.status === 401) throw new Error('UNAUTHORIZED');
    if (!resp.ok) {
      const errBody = await resp.json().catch(() => ({}));
      cnpLogError('putEntry: 保存失敗', { status: resp.status, error: errBody.error });
      throw new Error(errBody.error || `SAVE_FAILED_${resp.status}`);
    }
    cnpLog('putEntry: 保存成功', { date });
    return resp.json();
  }

  async function uploadImage(file) {
    const form = new FormData();
    form.append('file', file);
    const url = `${baseUrl}/api/images`;
    const resp = await loggedFetch('POST', url, {
      method: 'POST',
      headers: headers(),
      body: form
    });
    if (resp.status === 401) throw new Error('UNAUTHORIZED');
    if (!resp.ok) {
      const errBody = await resp.json().catch(() => ({}));
      cnpLogError('uploadImage: アップロード失敗', { status: resp.status, error: errBody.error });
      throw new Error(errBody.error || `UPLOAD_FAILED_${resp.status}`);
    }
    cnpLog('uploadImage: アップロード成功', { fileName: file && file.name, fileSize: file && file.size });
    return resp.json();
  }

  // options.jsの「接続テスト」から呼ばれる。timeoutMsを渡すと無応答時に
  // 'TIMEOUT' エラーで打ち切る（デフォルト20秒）。
  async function testConnection(opts) {
    const timeoutMs = (opts && opts.timeoutMs) || DEFAULT_TIMEOUT_MS;
    const url = `${baseUrl}/api/entries`;
    const resp = await loggedFetch('GET', url, { headers: headers() }, timeoutMs);
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
