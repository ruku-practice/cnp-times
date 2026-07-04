// CNP TIMES 投稿ツール: バックグラウンドサービスワーカー（MV3）。
// 右クリックメニューの登録、選択テキストのpost.htmlへの受け渡し、
// ツールバーアイコンクリックでの投稿フォーム起動を担当する。

importScripts('log.js');

const MENU_ID = 'cnp-post-selection';
const POST_WINDOW_WIDTH = 480;
const POST_WINDOW_HEIGHT = 720;

cnpLog('background.js 起動（Service Worker開始）');

chrome.runtime.onInstalled.addListener((details) => {
  cnpLog('onInstalled', { reason: details.reason, previousVersion: details.previousVersion });
  chrome.contextMenus.create({
    id: MENU_ID,
    title: 'CNP TIMESに投稿',
    contexts: ['selection']
  });
  cnpLog('右クリックメニューを登録しました', { menuId: MENU_ID });
});

// 選択テキストをstorage.sessionに一時保存してpost.htmlの小窓を開く。
// storage.session はService Workerの再起動やタブ切り替えをまたいでも読み出せるため、
// 起動直後のpost.js（DOMContentLoaded）から確実に受け取れる。
async function openPostWindow(selectionText) {
  const text = selectionText || '';
  cnpLog('投稿フォームを開きます', { selectionLength: text.length });
  try {
    await chrome.storage.session.set({ cnpPendingSelection: text });
    cnpLog('選択テキストをstorage.sessionに保存しました', { selectionLength: text.length });
    chrome.windows.create({
      url: chrome.runtime.getURL('post.html'),
      type: 'popup',
      width: POST_WINDOW_WIDTH,
      height: POST_WINDOW_HEIGHT
    });
    cnpLog('post.html の小窓を開きました');
  } catch (err) {
    cnpLogError('投稿フォームを開く処理で例外が発生しました', err && (err.stack || err.message || err));
  }
}

chrome.contextMenus.onClicked.addListener((info) => {
  if (info.menuItemId !== MENU_ID) return;
  cnpLog('右クリックメニュー「CNP TIMESに投稿」がクリックされました');
  openPostWindow(info.selectionText || '');
});

// ツールバーアイコンクリック時は選択テキスト無しでフォームを開く
// （Discordアプリ版からコピペする運用向け）。
chrome.action.onClicked.addListener(() => {
  cnpLog('ツールバーアイコンがクリックされました');
  openPostWindow('');
});
