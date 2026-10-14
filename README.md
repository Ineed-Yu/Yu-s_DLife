# Yu-s_DLife
My hobby account site.（https://divaclarice321.com）

## 写真を追加・差し替えるとき
1. 写真を `images/` に入れる（JPG または PNG）
2. 次を実行して、表示用の軽量版（`images/opt/`）を作る
   ```
   python3 tools/optimize_images.py
   ```
   - 表示サイズ別（横幅 160 / 480 / 960 / 1600px）の WebP を作ります
   - 位置情報などのメタデータは軽量版に残りません。元写真に位置情報があれば、画質を変えずに削除します
   - 必要なもの: Python 3 と Pillow（`pip install Pillow`）
3. ページからは `images/opt/<元のファイル名>-<横幅>.webp` を参照する

PR を作ると、軽量版の作り忘れや位置情報入りの写真がないかを GitHub が自動でチェックします（「画像チェック」）。

## ピンバッジを追加するとき
1. ピンの写真を `images/` に入れ、上の手順で軽量版を作る
2. `pins/data.json` に1件追加する（`Image` には元写真のパスを書けば、ページ側で自動的に軽量版を使います）
3. `"Draft": true` を付けたピンはサイトに表示されません（下書き・仮データ用）。公開するときは `false` にするか行ごと消す

ピンボードの大きさと列数は、登録点数に合わせて自動で調整されます。表示するピンが0点のときは「準備中」と表示されます。

**最初のピンを公開するとき**は、`pins/pins.html` の `<meta name="robots" content="noindex">` の行を削除し、`sitemap.xml` にピンボードの URL を戻してください（準備中の間は検索結果に出さない設定にしています）。

## フッター・「ホームに戻る」ボタン（全ページ共通の部品）を変えるとき
1. `tools/partials/footer.html`（フッター）または `tools/partials/home-button.html`（右上のボタン）を編集する
2. 次を実行して全ページへ反映する
   ```
   python3 tools/apply_partials.py
   ```
- 見た目（色・位置）は `assets/common.css` で変えられます
- 各ページの `<!-- partial:footer -->` 〜 `<!-- /partial:footer -->` の間は自動で上書きされるので、直接編集しないでください
- 新しいページを作るときは、`<head>` に `<link rel="stylesheet" href="/assets/common.css">` を入れ、`</body>` の前に次の2行を入れてから上のスクリプトを実行してください
  ```
  <!-- partial:footer -->
  <!-- /partial:footer -->
  ```
- PR を作ると、反映漏れがないかを GitHub が自動でチェックします（「共通部品チェック」）

## 公開ページを追加したとき
`sitemap.xml` にそのページの URL を追記してください（準備中のページは載せない）。
