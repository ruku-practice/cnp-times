// CNP TIMES 投稿ツール: 共通デバッグログ。
// 配布先（ひろゆきさん）環境で不具合が起きたときに、
// Chromeの「検証」→Consoleタブに出るログだけで状況を追えるようにするための仕組み。
// デフォルトで有効（無効化スイッチは用意していない＝常時ON）。
//
// 使い方: cnpLog('メッセージ', { 任意の付随情報 });
// 出力形式: [CNP投稿] 2026-07-04T12:00:00.000+09:00 メッセージ 付随情報...
//
// post.js / options.js / background.js / api.js の全てから読み込む。
// ブラウザ（<script>タグ, グローバルwindow）とnode（ESM import, test_api.mjs）の
// 両方で使えるよう、他の共通ファイル（logic.js, api.js）と同じくグローバルオブジェクトへの
// 代入で公開する。

function nowStampForLog() {
  // ログの見やすさ優先でJST表記にする（サーバー側の掲載日もJST基準のため）。
  try {
    const now = new Date();
    const jst = new Date(now.getTime() + 9 * 60 * 60000);
    const pad = (n) => String(n).padStart(2, '0');
    const y = jst.getUTCFullYear();
    const mo = pad(jst.getUTCMonth() + 1);
    const d = pad(jst.getUTCDate());
    const h = pad(jst.getUTCHours());
    const mi = pad(jst.getUTCMinutes());
    const s = pad(jst.getUTCSeconds());
    const ms = String(jst.getUTCMilliseconds()).padStart(3, '0');
    return `${y}-${mo}-${d}T${h}:${mi}:${s}.${ms}+09:00`;
  } catch (_err) {
    return new Date().toISOString();
  }
}

// APIキーなど機密値をログに出すときは、有無と先頭数文字のマスク表示に留める。
// 例: maskSecret('cnpt_abcdef123456') -> 'cnpt_ab…(20文字)'
function maskSecret(value) {
  if (!value) return '(未設定)';
  const str = String(value);
  const visible = str.slice(0, 7); // 'cnpt_ab' 程度
  return `${visible}…(${str.length}文字)`;
}

function cnpLog(...args) {
  try {
    // eslint-disable-next-line no-console
    console.log('[CNP投稿]', nowStampForLog(), ...args);
  } catch (_err) {
    // ログ出力自体の失敗で本処理を止めない。
  }
}

function cnpLogError(...args) {
  try {
    // eslint-disable-next-line no-console
    console.error('[CNP投稿]', nowStampForLog(), ...args);
  } catch (_err) {
    // ログ出力自体の失敗で本処理を止めない。
  }
}

const CnpLog = { cnpLog, cnpLogError, maskSecret };

if (typeof module !== 'undefined' && module.exports) {
  module.exports = CnpLog;
}
if (typeof window !== 'undefined') {
  window.CnpLog = CnpLog;
  // 各所で毎回 window.CnpLog.cnpLog(...) と書かなくて済むようグローバル関数としても公開。
  window.cnpLog = cnpLog;
  window.cnpLogError = cnpLogError;
}
if (typeof self !== 'undefined' && typeof window === 'undefined') {
  // Service Worker（background.js）はwindowを持たずselfがグローバル。
  self.CnpLog = CnpLog;
  self.cnpLog = cnpLog;
  self.cnpLogError = cnpLogError;
}
