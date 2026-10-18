#!/usr/bin/env python3
"""全ページ共通の部品（フッター・ホームに戻るボタン）を各ページへ反映するスクリプト。

部品の元は tools/partials/ にあります。

  tools/partials/footer.html       … 共通フッター
  tools/partials/home-button.html  … 右上に固定する「ホームに戻る」ボタン

各ページの HTML には、部品を入れたい場所に目印（マーカー）を書いておきます。

  <!-- partial:footer -->
  （この間はスクリプトが上書きするので、直接編集しない）
  <!-- /partial:footer -->

使い方:
  python3 tools/apply_partials.py           # 部品の内容を全ページへ反映する
  python3 tools/apply_partials.py --check   # 反映漏れ・フッターのないページがないか確認だけする
                                            # （問題があれば終了コード 1。GitHub の自動チェックで使用）

部品の文言を変えるときは tools/partials/ のファイルを直してから、このスクリプトを実行してください。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARTIALS_DIR = ROOT / "tools" / "partials"
SKIP_DIRS = {".git", "node_modules", "tools", ".github"}
# 言語ごとのブログ（/en/blog/ など）は tools/build_blog.py が /blog/index.html から訳文入りで作るので対象外
# （共通部品を変えたら apply_partials.py → build_blog.py の順に実行する）
LANG_DIRS = {"en", "fr", "zh"}

# すべての公開ページに必ず入れる部品
REQUIRED = {"footer"}


def partials() -> dict[str, str]:
    return {p.stem: p.read_text(encoding="utf-8").strip("\n") for p in sorted(PARTIALS_DIR.glob("*.html"))}


def pages() -> list[Path]:
    return sorted(
        p for p in ROOT.rglob("*.html")
        if not any(part in SKIP_DIRS for part in p.relative_to(ROOT).parts)
        and p.relative_to(ROOT).parts[0] not in LANG_DIRS
    )


def marker_re(name: str) -> re.Pattern[str]:
    # 開始マーカーの行頭の字下げを部品にも付けて揃える
    return re.compile(
        rf"(?P<indent>[ \t]*)<!-- partial:{re.escape(name)} -->\n.*?(?P=indent)<!-- /partial:{re.escape(name)} -->",
        re.S,
    )


def render(name: str, body: str, indent: str) -> str:
    inner = "\n".join((indent + line) if line.strip() else "" for line in body.split("\n"))
    return f"{indent}<!-- partial:{name} -->\n{inner}\n{indent}<!-- /partial:{name} -->"


def apply(text: str, parts: dict[str, str]) -> str:
    for name, body in parts.items():
        text = marker_re(name).sub(lambda m: render(name, body, m.group("indent")), text)
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="反映はせず、問題がないか確認だけする")
    args = parser.parse_args()

    parts = partials()
    problems: list[str] = []
    for page in pages():
        rel = page.relative_to(ROOT)
        text = page.read_text(encoding="utf-8")
        for name in REQUIRED:
            if f"<!-- partial:{name} -->" not in text:
                problems.append(f"{rel}: 共通部品「{name}」の目印がありません")
        updated = apply(text, parts)
        if updated == text:
            continue
        if args.check:
            problems.append(f"{rel}: 共通部品が最新ではありません（python3 tools/apply_partials.py を実行してください）")
        else:
            page.write_text(updated, encoding="utf-8")
            print(f"反映: {rel}")

    for p in problems:
        print("⚠ " + p, file=sys.stderr)
    if args.check:
        print("確認OK" if not problems else f"{len(problems)} 件の問題があります")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
