# 作業の記録

作業を終えたら、いちばん上に1〜3行で追記します（日付・名前・やったこと・PR や Issue の番号）。

## 2026-11-16
- Claude：BOARD を確認。管理者の了承を受けて、取得元から Reddit を外した（PR #63）。PR #60 はマージ済み。Muse の掲載 #61・#62 を確認し、見出しの長さについて BOARD で連絡。
- Muse：Reddit の取得元除外について、管理者の了承を BOARD で Claude へ伝えた（Claude の管理者への質問への回答）。
- Muse：候補箱 第2回の2件（THREEPPY のクラリス冬グッズ #61／Seria 大型コラボ全8アイテムまとめ #62）を Issue で追加し、サイトへの掲載を確認（手動掲載リスト13件）。管理者が両方掲載を承認。
- Claude：定期確認。ブログの予約公開・自動収集は成功。Disney Magical Kingdom Blog の過去分が進んでいなかったため、配信から取り込む方法に切り替える PR #60 を作成（マージ待ち）。Reddit の取得失敗（403）が継続。

## 2026-11-15
- Claude：日本語ドメインの掲載元の表示を「ツムツム.jp」に修正（PR #59）。PR #58（取得元の追加を Muse の Issue でも）がマージされた。
- Muse：Claude の更新を確認（PR #58 マージ完了・取得元の書き方を確認）。BOARD の連絡2点のうち #56 のリンク先を検証し、トゥーンタウン記事そのものである旨を回答。#55 の掲載元は管理者の判断待ち。Claude の更新を定期確認する運用の開始を管理者に提案。
- Claude：共有スペースを読み、Muse の掲載9件（#48〜#56）を確認。取得元の追加を Muse の Issue でも動くようにする PR #58 を作成（マージ待ち）。BOARD に Muse への連絡2点と、管理者への質問を追記。
- Muse：Issue #49〜#56 の本文を `acorn-issue-format.md` の形式で入れて保存し直し、候補9件（#48 を含む）すべてが Acorn Club に掲載された（手動掲載リスト11件・ニュース230件）。BOARD.md の Muse 欄を記入し、POLICY.md にアクセス解析（Cloudflare Web Analytics 採用）の決定を追記。
- Claude：エージェントの共有スペース（`.github/agents/`）を作成。Acorn の手動追加を、題名に「[Acorn]」が無い Issue（Muse が作成）でも動くようにし、Issue が続けて作られても取りこぼさないよう修正。
- Claude：クラリス年表を Notion から取り込む仕組みを追加し、接続を確認（PR #47）。年表に種類の絞り込みを追加。

## 2026-11-14
- Claude：同じ商品の記事をまとめる指定（`content/acorn/groups.json`）、Reddit の記事の削除（PR #46）。
- Claude：RSS の無いサイトを、サイトマップと検索結果のページから取り込む仕組み（PR #45）。
- Claude：「（手動で追加）」の表示を削除（PR #44）。画像の中の「Clarice」を読む仕組み（PR #43）。
- Claude：取得元に Trading Card Journal を追加（PR #41）。
