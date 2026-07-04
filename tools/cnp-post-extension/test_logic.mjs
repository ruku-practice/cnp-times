// logic.js の単体テスト。node test_logic.mjs で実行（依存パッケージ不要）。
// logic.js は module.exports で公開しているため、node の ESM から createRequire 経由で読み込む。

import { createRequire } from 'module';
import assert from 'assert';
import path from 'path';
import { fileURLToPath } from 'url';

const require = createRequire(import.meta.url);
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const { pickTitleLine, yesterdayJst, nowJstIso } = require(path.join(__dirname, 'logic.js'));

let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    fn();
    passed += 1;
    console.log(`ok - ${name}`);
  } catch (err) {
    failed += 1;
    console.error(`NG - ${name}`);
    console.error(`     ${err.message}`);
  }
}

// --- pickTitleLine ---------------------------------------------------------

test('「分析N回目」を含む行を最優先で選ぶ', () => {
  const text = 'https://twitter.com/foo/status/123\n相場分析【分析1502回目 ドル円編】\n本文本文';
  assert.strictEqual(pickTitleLine(text), '相場分析【分析1502回目 ドル円編】');
});

test('分析N回目の行が無ければ【】見出しの中身を使う（旧サーバー形式）', () => {
  const text = 'https://twitter.com/foo/status/123\n【今日の相場観】\n本文本文';
  assert.strictEqual(pickTitleLine(text), '今日の相場観');
});

test('見出しも分析N回目も無ければURL以外の最初の非空行を使う', () => {
  const text = 'https://twitter.com/foo/status/123\n\nここが本文の1行目です\n続き';
  assert.strictEqual(pickTitleLine(text), 'ここが本文の1行目です');
});

test('全行URLまたは空行ならフォールバックで最初の非空行(URL)を使う', () => {
  const text = '\nhttps://twitter.com/foo/status/123\nhttps://example.com/bar';
  assert.strictEqual(pickTitleLine(text), 'https://twitter.com/foo/status/123');
});

test('空文字列・undefinedでも例外を投げず空文字を返す', () => {
  assert.strictEqual(pickTitleLine(''), '');
  assert.strictEqual(pickTitleLine(undefined), '');
});

test('前後の空白はトリムされる', () => {
  const text = '   タイトル行の前後に空白   \n本文';
  assert.strictEqual(pickTitleLine(text), 'タイトル行の前後に空白');
});

test('複数の分析N回目候補があっても最初の行を選ぶ', () => {
  const text = '相場分析【分析1回目】\n相場分析【分析2回目】';
  assert.strictEqual(pickTitleLine(text), '相場分析【分析1回目】');
});

test('URLの後ろに直接テキストが続く行はURLだけの行ではないので採用される', () => {
  const text = 'https://twitter.com/foo/status/123 これは補足コメント\n次の行';
  assert.strictEqual(pickTitleLine(text), 'https://twitter.com/foo/status/123 これは補足コメント');
});

// --- yesterdayJst -----------------------------------------------------------

test('yesterdayJst: JST 2026-07-04 12:00 の"今"なら昨日は2026-07-03', () => {
  // 2026-07-04T12:00:00+09:00 = 2026-07-04T03:00:00Z
  const now = new Date('2026-07-04T03:00:00Z');
  assert.strictEqual(yesterdayJst(now), '2026-07-03');
});

test('yesterdayJst: JST日付が変わる直前(23:59)でも正しく前日になる', () => {
  // 2026-07-04T23:59:00+09:00 = 2026-07-04T14:59:00Z
  const now = new Date('2026-07-04T14:59:00Z');
  assert.strictEqual(yesterdayJst(now), '2026-07-03');
});

test('yesterdayJst: JST日付が変わった直後(00:01)は前日が正しく計算される', () => {
  // 2026-07-05T00:01:00+09:00 = 2026-07-04T15:01:00Z
  const now = new Date('2026-07-04T15:01:00Z');
  assert.strictEqual(yesterdayJst(now), '2026-07-04');
});

test('yesterdayJst: 月をまたぐケース(8/1のJST未明 → 7/31)', () => {
  // 2026-08-01T00:30:00+09:00 = 2026-07-31T15:30:00Z
  const now = new Date('2026-07-31T15:30:00Z');
  assert.strictEqual(yesterdayJst(now), '2026-07-31');
});

// --- nowJstIso ---------------------------------------------------------------

test('nowJstIso: JSTのISO形式文字列（+09:00オフセット）を返す', () => {
  const now = new Date('2026-07-04T03:00:00Z'); // JST 12:00
  assert.strictEqual(nowJstIso(now), '2026-07-04T12:00:00+09:00');
});

test('nowJstIso: 日付をまたぐケースでも正しい日付になる', () => {
  const now = new Date('2026-07-04T15:01:00Z'); // JST 2026-07-05 00:01
  assert.strictEqual(nowJstIso(now), '2026-07-05T00:01:00+09:00');
});

// --- サマリ -------------------------------------------------------------------

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) {
  process.exit(1);
}
