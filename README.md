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

ピンボードの大きさと列数は、登録点数に合わせて自動で調整されます。

## 公開ページを追加したとき
`sitemap.xml` にそのページの URL を追記してください（準備中のページは載せない）。
