// 共通ロジック（タイトル自動抽出・JST日付計算）。
// post.js（拡張のUI）と test_logic.mjs（node単体テスト）の両方から読み込む。
// ブラウザ（<script>タグ, グローバルwindow）とnode（ESM import）の両方で使えるよう、
// module.exports / export の代わりにグローバルオブジェクトへの代入で公開する。

// deploy/auth/scripts/collect_discord.py の _pick_title_line と同じロジック。
// 1. 「分析N回目」を含む行（新サーバー形式。例: 相場分析【分析1502回目 …】）
// 2. 【...】見出しを含む最初の行（旧サーバー形式。中身のみ使う）
// 3. URLだけの行を除いた最初の非空行
// 4. 全行がURL・空行なら最初の非空行にフォールバック
const ANCHOR_RE = /分析\s*(\d+)\s*回目/;
const URL_ONLY_RE = /^https?:\/\/\S+$/;
const HEADLINE_RE = /【([^】]+)】/;

function firstNonEmptyLine(text) {
  const lines = (text || '').split(/\r\n|\r|\n/);
  for (const line of lines) {
    const stripped = line.trim();
    if (stripped) return stripped;
  }
  return '';
}

function pickTitleLine(text) {
  const lines = (text || '').split(/\r\n|\r|\n/).map((ln) => ln.trim());

  for (const stripped of lines) {
    if (stripped && ANCHOR_RE.test(stripped)) return stripped;
  }
  for (const stripped of lines) {
    if (!stripped) continue;
    const m = HEADLINE_RE.exec(stripped);
    if (m) return m[1].trim();
  }
  for (const stripped of lines) {
    if (stripped && !URL_ONLY_RE.test(stripped)) return stripped;
  }
  return firstNonEmptyLine(text);
}

// JSTの壁時計表示に変換したDateを返す内部ヘルパー。
// Date#getTime() はローカルタイムゾーンに依存しないUTCエポックms値なので、
// 「+9時間」するだけでJST壁時計時刻が得られる（ローカルTZ分の補正は不要かつ有害）。
// ローカルTZがJST以外の環境で "9*60 - getTimezoneOffset()" のような式を使うと、
// ローカルTZ分だけ余計にズレるので注意（member.js の旧yesterdayJst()にあった不具合と同種）。
function toJstWallClock(base) {
  return new Date(base.getTime() + 9 * 60 * 60000);
}

// JSTの「昨日」を YYYY-MM-DD で返す（掲載日=投稿日の前日ルール）。
function yesterdayJst(now) {
  const base = now || new Date();
  const jst = toJstWallClock(base);
  jst.setUTCDate(jst.getUTCDate() - 1);
  return jst.toISOString().slice(0, 10);
}

// 現在時刻のJST ISO文字列を返す（新規投稿時のposted_at用）。
// 例: 2026-07-04T21:00:00+09:00
function nowJstIso(now) {
  const base = now || new Date();
  const jst = toJstWallClock(base);
  const pad = (n) => String(n).padStart(2, '0');
  const y = jst.getUTCFullYear();
  const mo = pad(jst.getUTCMonth() + 1);
  const d = pad(jst.getUTCDate());
  const h = pad(jst.getUTCHours());
  const mi = pad(jst.getUTCMinutes());
  const s = pad(jst.getUTCSeconds());
  return `${y}-${mo}-${d}T${h}:${mi}:${s}+09:00`;
}

const CnpPostLogic = { pickTitleLine, yesterdayJst, nowJstIso, firstNonEmptyLine };

if (typeof module !== 'undefined' && module.exports) {
  module.exports = CnpPostLogic;
}
if (typeof window !== 'undefined') {
  window.CnpPostLogic = CnpPostLogic;
}
