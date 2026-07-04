// CNP TIMES 投稿ツール: バックグラウンドサービスワーカー（MV3）。
// 右クリックメニューの登録、選択テキストのpost.htmlへの受け渡し、
// ツールバーアイコンクリックでの投稿フォーム起動を担当する。

const MENU_ID = 'cnp-post-selection';
const POST_WINDOW_WIDTH = 480;
const POST_WINDOW_HEIGHT = 720;

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: MENU_ID,
    title: 'CNP TIMESに投稿',
    contexts: ['selection']
  });
});

// 選択テキストをstorage.sessionに一時保存してpost.htmlの小窓を開く。
// storage.session はService Workerの再起動やタブ切り替えをまたいでも読み出せるため、
// 起動直後のpost.js（DOMContentLoaded）から確実に受け取れる。
async function openPostWindow(selectionText) {
  await chrome.storage.session.set({ cnpPendingSelection: selectionText || '' });
  chrome.windows.create({
    url: chrome.runtime.getURL('post.html'),
    type: 'popup',
    width: POST_WINDOW_WIDTH,
    height: POST_WINDOW_HEIGHT
  });
}

chrome.contextMenus.onClicked.addListener((info) => {
  if (info.menuItemId !== MENU_ID) return;
  openPostWindow(info.selectionText || '');
});

// ツールバーアイコンクリック時は選択テキスト無しでフォームを開く
// （Discordアプリ版からコピペする運用向け）。
chrome.action.onClicked.addListener(() => {
  openPostWindow('');
});
