// api.js（バックエンド呼び出し）の単体テスト。node test_api.mjs で実行。
// グローバルfetchをモックして、正しいURL・ヘッダー・エラーハンドリングになっているかを検証する。
// 実ネットワーク通信は行わない。

import { createRequire } from 'module';
import assert from 'assert';
import path from 'path';
import { fileURLToPath } from 'url';

const require = createRequire(import.meta.url);
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const { createApiClient } = require(path.join(__dirname, 'api.js'));

const BASE_URL = 'https://cnp-auth-289412336991.asia-northeast1.run.app';

let passed = 0;
let failed = 0;

async function test(name, fn) {
  try {
    await fn();
    passed += 1;
    console.log(`ok - ${name}`);
  } catch (err) {
    failed += 1;
    console.error(`NG - ${name}`);
    console.error(`     ${err.stack || err.message}`);
  }
}

// FormDataはnode 22なら組み込み。無ければ簡易ポリフィルを使う。
if (typeof globalThis.FormData === 'undefined') {
  globalThis.FormData = class {
    constructor() { this._data = {}; }
    append(key, value) { this._data[key] = value; }
  };
}
if (typeof globalThis.File === 'undefined') {
  globalThis.File = class {
    constructor(parts, name, opts) { this.parts = parts; this.name = name; this.type = (opts || {}).type; }
  };
}

function mockFetch(handler) {
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return handler(url, options);
  };
  return calls;
}

function jsonResponse(status, body) {
  return {
    status,
    ok: status >= 200 && status < 300,
    json: async () => body
  };
}

// --- fetchEntry --------------------------------------------------------------

await test('fetchEntry: 正しいURLとX-Api-Keyヘッダーでリクエストする', async () => {
  const calls = mockFetch(() => jsonResponse(200, { date: '2026-07-01', title: 't', body_md: 'b' }));
  const api = createApiClient(BASE_URL, () => 'cnpt_test');
  const entry = await api.fetchEntry('2026-07-01');
  assert.strictEqual(calls.length, 1);
  assert.strictEqual(calls[0].url, `${BASE_URL}/api/entries/2026-07-01`);
  assert.strictEqual(calls[0].options.headers['X-Api-Key'], 'cnpt_test');
  assert.strictEqual(entry.title, 't');
});

await test('fetchEntry: 404はnullを返す（例外を投げない）', async () => {
  mockFetch(() => jsonResponse(404, { error: 'not found' }));
  const api = createApiClient(BASE_URL, () => 'cnpt_test');
  const entry = await api.fetchEntry('2099-01-01');
  assert.strictEqual(entry, null);
});

await test('fetchEntry: 401はUNAUTHORIZEDエラーを投げる', async () => {
  mockFetch(() => jsonResponse(401, { error: 'unauthorized' }));
  const api = createApiClient(BASE_URL, () => 'cnpt_wrong');
  await assert.rejects(() => api.fetchEntry('2026-07-01'), /UNAUTHORIZED/);
});

await test('fetchEntry: 日付はURLエンコードされる（パストラバーサル対策）', async () => {
  const calls = mockFetch(() => jsonResponse(200, {}));
  const api = createApiClient(BASE_URL, () => 'cnpt_test');
  await api.fetchEntry('../../etc/passwd');
  assert.strictEqual(calls[0].url, `${BASE_URL}/api/entries/..%2F..%2Fetc%2Fpasswd`);
});

// --- putEntry ------------------------------------------------------------------

await test('putEntry: PUTメソッド・Content-Type・bodyが正しい', async () => {
  const calls = mockFetch(() => jsonResponse(200, { title: 'ok' }));
  const api = createApiClient(BASE_URL, () => 'cnpt_test');
  await api.putEntry('2026-07-01', { title: 'タイトル', body_md: '本文' });
  assert.strictEqual(calls[0].options.method, 'PUT');
  assert.strictEqual(calls[0].options.headers['Content-Type'], 'application/json');
  assert.strictEqual(calls[0].options.headers['X-Api-Key'], 'cnpt_test');
  const sentBody = JSON.parse(calls[0].options.body);
  assert.strictEqual(sentBody.title, 'タイトル');
  assert.strictEqual(sentBody.body_md, '本文');
});

await test('putEntry: posted_atをbodyに含めて送れる（新規投稿時の想定）', async () => {
  const calls = mockFetch(() => jsonResponse(200, {}));
  const api = createApiClient(BASE_URL, () => 'cnpt_test');
  await api.putEntry('2026-07-01', { title: 't', body_md: 'b', posted_at: '2026-07-01T21:00:00+09:00' });
  const sentBody = JSON.parse(calls[0].options.body);
  assert.strictEqual(sentBody.posted_at, '2026-07-01T21:00:00+09:00');
});

await test('putEntry: 401はUNAUTHORIZEDエラーを投げる', async () => {
  mockFetch(() => jsonResponse(401, { error: 'unauthorized' }));
  const api = createApiClient(BASE_URL, () => 'cnpt_wrong');
  await assert.rejects(() => api.putEntry('2026-07-01', { title: 't', body_md: 'b' }), /UNAUTHORIZED/);
});

await test('putEntry: 400番台はサーバーのerrorメッセージ付きで例外を投げる', async () => {
  mockFetch(() => jsonResponse(400, { error: 'title is required' }));
  const api = createApiClient(BASE_URL, () => 'cnpt_test');
  await assert.rejects(() => api.putEntry('2026-07-01', { title: '', body_md: 'b' }), /title is required/);
});

// --- uploadImage ----------------------------------------------------------------

await test('uploadImage: POST /api/images にFormDataで送信する', async () => {
  const calls = mockFetch(() => jsonResponse(200, { url: '/api/images/abc123.png' }));
  const api = createApiClient(BASE_URL, () => 'cnpt_test');
  const file = new File([new Uint8Array([1, 2, 3])], 'paste.png', { type: 'image/png' });
  const result = await api.uploadImage(file);
  assert.strictEqual(calls[0].url, `${BASE_URL}/api/images`);
  assert.strictEqual(calls[0].options.method, 'POST');
  assert.strictEqual(calls[0].options.headers['X-Api-Key'], 'cnpt_test');
  assert.ok(calls[0].options.body instanceof FormData);
  assert.strictEqual(result.url, '/api/images/abc123.png');
});

await test('uploadImage: 401はUNAUTHORIZEDエラーを投げる', async () => {
  mockFetch(() => jsonResponse(401, {}));
  const api = createApiClient(BASE_URL, () => 'cnpt_wrong');
  const file = new File([new Uint8Array([1])], 'paste.png', { type: 'image/png' });
  await assert.rejects(() => api.uploadImage(file), /UNAUTHORIZED/);
});

await test('uploadImage: 400番台のエラーメッセージを伝播する', async () => {
  mockFetch(() => jsonResponse(400, { error: 'unsupported file type' }));
  const api = createApiClient(BASE_URL, () => 'cnpt_test');
  const file = new File([new Uint8Array([1])], 'paste.exe', { type: 'application/octet-stream' });
  await assert.rejects(() => api.uploadImage(file), /unsupported file type/);
});

// --- testConnection ---------------------------------------------------------------

await test('testConnection: 200なら記事件数を返す', async () => {
  mockFetch(() => jsonResponse(200, [{ date: '2026-07-01' }, { date: '2026-07-02' }]));
  const api = createApiClient(BASE_URL, () => 'cnpt_test');
  const count = await api.testConnection();
  assert.strictEqual(count, 2);
});

await test('testConnection: 401はUNAUTHORIZEDエラーを投げる', async () => {
  mockFetch(() => jsonResponse(401, {}));
  const api = createApiClient(BASE_URL, () => 'cnpt_wrong');
  await assert.rejects(() => api.testConnection(), /UNAUTHORIZED/);
});

// --- サマリ -------------------------------------------------------------------

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) {
  process.exit(1);
}
