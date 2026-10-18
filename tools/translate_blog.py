#!/usr/bin/env python3
"""ブログ記事を英語・フランス語・中国語（簡体字）に自動で翻訳するスクリプト（Claude API を使用）。

  content/blog/<URL名>/index.md  →  content/blog/<URL名>/index.en.md / index.fr.md / index.zh.md

- 入稿のたび（.github/workflows/blog-intake.yml）に自動で動きます。手で動かす必要はありません。
- 翻訳するのは「公開」「予約」の記事だけです（下書きは翻訳しないので費用がかかりません）。
- 一度翻訳した記事は、原稿（タイトル・説明・タグ・本文）を直さない限り翻訳し直しません。
  原稿を直すと指紋（source_hash）が変わり、次の入稿・編集のときに翻訳し直します。
- 翻訳結果は、写真・URL・見出しの数が原文と同じかを確かめてから保存します。合わないときは保存せず、
  記事ページはその言語でも日本語を表示します（「日本語のみ」と注記）。
- API キー（環境変数 ANTHROPIC_API_KEY。GitHub の Secrets に登録）が無いときは何もしません。

使い方:
  python3 tools/translate_blog.py                 # 必要な記事だけ翻訳
  python3 tools/translate_blog.py --slug URL名    # その記事だけ
  python3 tools/translate_blog.py --summary FILE  # 結果（入稿ページへのコメント用の一文）を FILE に書く
環境変数:
  ANTHROPIC_API_KEY       … Claude API のキー（必須）
  BLOG_TRANSLATE_MODEL    … 使うモデル（省略時は DEFAULT_MODEL）
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_blog import CONTENT_DIR, IMG_LINE, JST, LANGS, URL_LINE, read_post, read_translation, source_hash  # noqa: E402

API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-5-5"
LANG_NAMES = {"en": "English", "fr": "French", "zh": "Simplified Chinese (简体中文)"}
LANG_LABELS = {"en": "英語", "fr": "フランス語", "zh": "中国語"}

SYSTEM = """You translate posts for a personal Japanese blog about Disney parks around the world, travel and photography.
Translate the Japanese post the user gives you into {lang}.

Rules:
- Translate faithfully and naturally, keeping the author's friendly first-person tone. Do not add, omit, summarize or comment.
- Use the official {lang} names of parks, lands, attractions, shows, characters and products when they exist
  (e.g. 東京ディズニーシー → Tokyo DisneySea, クラリス → Clarice).
- Keep the Markdown structure exactly: the same paragraphs, blank lines, headings (## / ###), lists, quotes (>) and horizontal rules, in the same order.
- Image lines look like ![caption](file-name.jpg). Keep the file name exactly; translate only the caption.
- A line that contains only a URL must stay exactly the same. In [text](URL) links translate the text and keep the URL.
- Keep **bold** markers around the corresponding translated words.
- Tags: translate each tag; keep the same number of tags in the same order.

Reply with exactly these four sections and nothing else:
<title>translated title</title>
<summary>translated summary (empty if the original summary is empty)</summary>
<tags>translated tags separated by " | " (empty if there are none)</tags>
<body>
translated body in Markdown
</body>"""


class TranslateError(Exception):
    pass


def call_claude(system: str, user: str, api_key: str, model: str) -> str:
    payload = json.dumps({
        "model": model,
        "max_tokens": 16000,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }).encode("utf-8")
    req = urllib.request.Request(API_URL, data=payload, method="POST", headers={
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    })
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                data = json.loads(r.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code in (429, 500, 502, 503, 529) and attempt < 2:
                time.sleep(20 * (attempt + 1))
                continue
            raise TranslateError(f"Claude API エラー（HTTP {e.code}）: {detail}") from None
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < 2:
                time.sleep(20 * (attempt + 1))
                continue
            raise TranslateError(f"Claude API に接続できませんでした: {e}") from None
    if data.get("stop_reason") == "max_tokens":
        raise TranslateError("記事が長すぎて翻訳が途中で切れました。")
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


def source_text(post: dict) -> str:
    return (f"<title>{post['title']}</title>\n<summary>{post.get('summary', '')}</summary>\n"
            f"<tags>{' | '.join(post.get('tags') or [])}</tags>\n<body>\n{post['body'].strip()}\n</body>")


def parse_reply(text: str) -> dict:
    out = {}
    for key in ("title", "summary", "tags", "body"):
        m = re.search(rf"<{key}>(.*?)</{key}>", text, re.S)
        if not m:
            raise TranslateError(f"翻訳結果に <{key}> がありません。")
        out[key] = m.group(1).strip()
    out["tags"] = [t.strip() for t in out["tags"].split("|") if t.strip()] if out["tags"] else []
    return out


def structure(body: str) -> dict:
    """原文と訳文で一致すべき骨組み（写真・URLの行・見出しの数・リンク先）。"""
    lines = [l.strip() for l in body.splitlines()]
    return {
        "images": [m.group(2) for l in lines if (m := IMG_LINE.match(l))],
        "url_lines": [l for l in lines if URL_LINE.match(l)],
        "h2": sum(1 for l in lines if l.startswith("## ")),
        "h3": sum(1 for l in lines if l.startswith("### ")),
        "links": sorted(re.findall(r"\]\((https?://[^)\s]+)\)", body)),
    }


def validate(post: dict, tr: dict) -> None:
    if not tr["title"] or not tr["body"]:
        raise TranslateError("タイトルか本文が空です。")
    if len(tr["tags"]) != len(post.get("tags") or []):
        raise TranslateError("タグの数が原文と違います。")
    a, b = structure(post["body"]), structure(tr["body"])
    for key, label in (("images", "写真"), ("url_lines", "URL の行"), ("h2", "見出し"), ("h3", "小見出し"), ("links", "リンク先")):
        if a[key] != b[key]:
            raise TranslateError(f"{label}が原文と一致しません。")
    if re.search(r"<\s*(script|iframe|style)", tr["body"], re.I):
        raise TranslateError("想定外のタグが含まれています。")


def translate_post(post: dict, lang: str, api_key: str, model: str, call=call_claude) -> dict:
    system = SYSTEM.format(lang=LANG_NAMES[lang])
    last = None
    for _ in range(2):  # 骨組みが合わなければ1回だけやり直す
        try:
            tr = parse_reply(call(system, source_text(post), api_key, model))
            validate(post, tr)
            return tr
        except TranslateError as e:
            last = e
            if "API" in str(e):
                break
    raise last  # type: ignore[misc]


def write_translation(post: dict, lang: str, tr: dict, model: str, now: dt.datetime) -> Path:
    path = post["dir"] / f"index.{lang}.md"
    front = [
        "---",
        f"# 自動翻訳（tools/translate_blog.py）。原文は index.md。直接編集しても、原稿を直すと上書きされます",
        f"title: {json.dumps(tr['title'], ensure_ascii=False)}",
        f"summary: {json.dumps(tr['summary'], ensure_ascii=False)}",
        f"tags: {json.dumps(tr['tags'], ensure_ascii=False)}",
        f"source_hash: {json.dumps(source_hash(post))}",
        f"translated_by: {json.dumps(model)}",
        f"translated_at: {now.isoformat(timespec='minutes')}",
        "---",
        "",
    ]
    path.write_text("\n".join(front) + tr["body"].strip() + "\n", encoding="utf-8")
    return path


def run(slug: str | None, api_key: str | None, model: str, now: dt.datetime, call=call_claude) -> dict:
    """戻り値: {"done": [(slug, lang)], "failed": [(slug, lang, 理由)], "skipped": 理由 or None}"""
    result: dict = {"done": [], "failed": [], "skipped": None}
    posts = [read_post(md) for md in sorted(CONTENT_DIR.glob("*/index.md"))]
    posts = [p for p in posts if p["status"] in ("published", "scheduled") and (slug is None or p["slug"] == slug)]
    todo = [(p, lang) for p in posts for lang in LANGS if read_translation(p, lang) is None]
    if not todo:
        return result
    if not api_key:
        result["skipped"] = "翻訳用の API キー（ANTHROPIC_API_KEY）が未設定のため、翻訳していません。"
        return result
    for post, lang in todo:
        try:
            tr = translate_post(post, lang, api_key, model, call)
            write_translation(post, lang, tr, model, now)
            result["done"].append((post["slug"], lang))
        except TranslateError as e:
            result["failed"].append((post["slug"], lang, str(e)))
    return result


def summary_line(result: dict) -> str:
    if result["skipped"]:
        return f"🌐 {result['skipped']}英語・フランス語・中国語では日本語の本文を表示します。"
    parts = []
    if result["done"]:
        langs = sorted({LANG_LABELS[l] for _, l in result["done"]}, key=list(LANG_LABELS.values()).index)
        parts.append(f"🌐 {'・'.join(langs)}に自動翻訳しました。")
    if result["failed"]:
        langs = "・".join(LANG_LABELS[l] for _, l, _ in result["failed"])
        reason = result["failed"][0][2].rstrip("。")
        parts.append(f"⚠️ {langs}の翻訳に失敗しました（{reason}）。その言語では日本語を表示します。"
                     "このページを「Edit」でそのまま保存し直すと、もう一度翻訳します。")
    return "\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--slug", help="この記事だけ翻訳する")
    parser.add_argument("--summary", help="結果の一文を書き出すファイル")
    args = parser.parse_args()
    model = os.environ.get("BLOG_TRANSLATE_MODEL") or DEFAULT_MODEL
    result = run(args.slug, os.environ.get("ANTHROPIC_API_KEY"), model, dt.datetime.now(JST))
    line = summary_line(result)
    if args.summary:
        Path(args.summary).write_text(line, encoding="utf-8")
    for s, l in result["done"]:
        print(f"翻訳: {s} → {l}")
    for s, l, why in result["failed"]:
        print(f"::warning::翻訳に失敗: {s} → {l}: {why}")
    if result["skipped"]:
        print(result["skipped"])
    return 0  # 翻訳に失敗しても記事の公開は止めない


if __name__ == "__main__":
    sys.exit(main())
