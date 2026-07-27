# cnp-times-redirect

旧URL `https://ruku-practice.github.io/cnp-times/` に来た人を
`https://cnp.rukupractice.com/` へ転送するだけの公開リポジトリ。

2026-07-26に「勝手にCNP TIMES」をCloudflare（cnp.rukupractice.com）へ移設し、
本体のリポジトリを非公開にしたため、旧URLを生かすためだけに存在する。

GitHub Pagesの公開URLは**リポジトリ名がそのままパスになる**ため、旧URLを維持するには
このリポジトリの名前が `cnp-times` である必要がある。

## 転送先

| 旧URL | 転送先 |
|---|---|
| `/cnp-times/`, `/cnp-times/index.html` | `https://cnp.rukupractice.com/`（2026-07-26ルク決定: 旧URLから来た人は全員トップへ集める） |
| `/cnp-times/advanced.html` | `https://cnp.rukupractice.com/`（高機能版。2026-07-26にトップへ昇格） |
| それ以外 | `https://cnp.rukupractice.com/`（404.html） |

## 中身

転送用のHTMLだけ。**ソースコード・データ・内部文書は一切置かない**
（このリポジトリが公開である理由は旧URLの維持だけなので、読まれても何も漏れない状態を保つ）。

## セットアップ

Settings → Pages → Source: Deploy from a branch → `main` / `/ (root)`
