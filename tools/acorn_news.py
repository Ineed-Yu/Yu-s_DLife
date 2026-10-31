#!/usr/bin/env python3
"""Acorn Club のタイムライン（クラリスの新着グッズ情報）を作るスクリプト。

  content/acorn/sources.json   … 取得元（RSS / Atom）
  content/acorn/collected.json … 自動で集めた情報（取得元の配信から消えても残す）
  content/acorn/manual.json    … 入力フォームから手動で追加した情報（SNS の投稿など）
  content/acorn/exclude.json   … 表示しない情報（URL・言葉）
        ↓
  acorn-club/news.json         … ページに表示するタイムライン（新しい順）

- 取り込むのは「タイトル・リンク・掲載元・日付」だけ。記事の本文や写真は保存も表示もしない（著作権への配慮）。
- 「クラリス / Clarice」と、ディズニーの話題であること、グッズの話題であることの3つがそろう情報だけを残す。
  同じ名前の別作品（『カリオストロの城』のクラリス、『羊たちの沈黙』のクラリス など）は除く。
- リンクは http / https だけ。

使い方:
  python3 tools/acorn_news.py collect             # 取得元から集めて、タイムラインを作り直す（自動実行用）
  python3 tools/acorn_news.py collect --dry-run   # 書き換えずに、取得元ごとの結果を表示（PR での確認用）
  python3 tools/acorn_news.py build               # 集めた情報からタイムラインだけ作り直す
  python3 tools/acorn_news.py build --check       # タイムラインが最新か確認する（CI 用）
  python3 tools/acorn_news.py add イベントのJSON   # 入力フォームの内容を手動の情報として追加（自動実行用）
  python3 tools/acorn_news.py comment 結果のJSON  # 入力フォームへのコメント文を作る
"""
from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import hashlib
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "content" / "acorn"
OUT_FILE = ROOT / "acorn-club" / "news.json"
JST = dt.timezone(dt.timedelta(hours=9))

MAX_ITEMS = 300               # タイムラインに残す最大件数
MAX_AGE_DAYS = 730            # これより古い情報は載せない（約2年）
MAX_FEED_BYTES = 3 * 1024 * 1024
USER_AGENT = "AcornClubTimeline/1.0 (+https://divaclarice321.com/acorn-club/; unofficial fan page)"

# ---------------------------------------------------------------- 絞り込みの条件
CLARICE = re.compile(r"クラリス|clarice", re.I)
DISNEY = re.compile(r"ディズニー|disney|チップ|デール|chip\s*(?:'n'|n'|and|&)?\s*dale|ＴＤＲ|TDR|TDL|TDS|"
                    r"東京ディズニー|ショップディズニー|ディズニーストア|shopdisney|disneyland|epcot|magic kingdom", re.I)
OTHER_CLARICE = re.compile(r"カリオストロ|ルパン|lupin|cagliostro|starling|スターリング|羊たちの沈黙|silence of the lambs|"
                           r"hannibal|ハンニバル|lispector|リスペクトル", re.I)
PIN = re.compile(r"ピンバッ?ジ|ピン(?:トレ|セット|バッチ)|\bpins?\b|pin trading|lanyard", re.I)
PLUSH = re.compile(r"ぬいぐるみ|ぬいば|ぬいバッジ|ツムツム|plush|tsum\s*tsum|stuffed|nuimos", re.I)
GOODS = re.compile(r"グッズ|新商品|新作|発売|販売|登場|コレクション|ストア|ショップ|キーチェーン|ストラップ|カチューシャ|"
                   r"ポーチ|バッグ|マグ|タオル|ステッカー|フィギュア|お菓子|スーベニア|"
                   r"merch|merchandise|collection|release|ears|loungefly|mug|apparel|figure|ornament|"
                   r"spirit jersey|keychain|souvenir|shopdisney|new arrivals?|now available|coming soon", re.I)
CATEGORIES = ("pin", "plush", "goods", "other")


def category_of(text: str, topic: str | None = None) -> str | None:
    """グッズの話題なら種類（pin / plush / goods）、そうでなければ None。"""
    if PIN.search(text) or topic == "pin":
        return "pin"
    if PLUSH.search(text):
        return "plush"
    if GOODS.search(text):
        return "goods"
    return None


def is_relevant(title: str, summary: str, topic: str | None = None) -> str | None:
    """タイムラインに載せる情報か判定し、載せるなら種類を返す。"""
    text = f"{title}\n{summary}"
    if not CLARICE.search(text) or OTHER_CLARICE.search(text):
        return None
    if not DISNEY.search(text) and topic != "pin":
        return None
    return category_of(text, topic)


# ---------------------------------------------------------------- 文字の整え
TAG = re.compile(r"<[^>]+>")


def clean_text(s: str | None, limit: int = 200) -> str:
    s = html.unescape(TAG.sub(" ", s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit] + ("…" if len(s) > limit else "")


def safe_url(u: str | None) -> str | None:
    u = (u or "").strip()
    p = urllib.parse.urlparse(u)
    if p.scheme not in ("http", "https") or not p.netloc:
        return None
    return u


def item_id(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def parse_date(s: str | None) -> dt.datetime | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        d = email.utils.parsedate_to_datetime(s)
    except (TypeError, ValueError):
        d = None
    if d is None:
        try:
            d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(JST)


def source_from_host(url: str) -> str:
    host = (urllib.parse.urlparse(url).hostname or "").removeprefix("www.")
    return {"x.com": "X", "twitter.com": "X", "instagram.com": "Instagram", "threads.net": "Threads",
            "youtube.com": "YouTube", "youtu.be": "YouTube", "tiktok.com": "TikTok"}.get(host, host)


# ---------------------------------------------------------------- 配信（RSS / Atom）の読み取り
def strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


XML_ENTITIES = {"amp", "lt", "gt", "quot", "apos"}
BAD_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def repair_xml(text: str) -> str:
    """配信によくある崩れ（&nbsp; などの HTML の文字参照、単独の &、制御文字）を直す。"""
    def entity(m: re.Match) -> str:
        name = m.group(1)
        if name in XML_ENTITIES or name.startswith("#"):
            return m.group(0)
        ch = html.unescape(m.group(0))
        return f"&#{ord(ch)};" if len(ch) == 1 else "&amp;" + name + ";"
    text = BAD_CHARS.sub("", text)
    text = re.sub(r"&(#?[A-Za-z0-9]+);", entity, text)
    return re.sub(r"&(?!(?:#[0-9]+|#x[0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9]*);)", "&amp;", text)


def parse_feed(data: bytes) -> list[dict]:
    """RSS 2.0 / Atom を読み、{title, url, date, summary, source} の一覧を返す。"""
    try:
        root = ET.fromstring(data)  # 外部実体は標準ライブラリの既定で展開されない
    except ET.ParseError:
        text = data.decode("utf-8", "replace").lstrip("\ufeff \r\n\t")
        if not text.startswith("<?xml") and not re.match(r"<(rss|feed|rdf:RDF)\b", text):
            raise ValueError("RSS / Atom ではない応答でした（ページやブロック画面の可能性）") from None
        root = ET.fromstring(repair_xml(text).encode("utf-8"))
    if strip_ns(root.tag) not in ("rss", "feed", "RDF"):
        raise ValueError(f"RSS / Atom ではない応答でした（<{strip_ns(root.tag)}>）")
    entries = []
    for el in root.iter():
        name = strip_ns(el.tag)
        if name not in ("item", "entry"):
            continue
        fields: dict[str, str] = {}
        link = None
        for child in el:
            cname = strip_ns(child.tag)
            if cname == "link":
                href = child.get("href")
                if href and child.get("rel", "alternate") == "alternate":
                    link = link or href
                elif child.text and child.text.strip():
                    link = link or child.text.strip()
            elif cname in ("title", "pubDate", "published", "updated", "date", "description", "summary", "source"):
                fields.setdefault(cname, "".join(child.itertext()))
        entries.append({
            "title": fields.get("title", ""),
            "url": link,
            "date": fields.get("pubDate") or fields.get("published") or fields.get("date") or fields.get("updated"),
            "summary": fields.get("description") or fields.get("summary") or "",
            "source": fields.get("source", ""),
        })
    return entries


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"})
    with urllib.request.urlopen(req, timeout=25) as r:
        data = r.read(MAX_FEED_BYTES + 1)
    if len(data) > MAX_FEED_BYTES:
        raise ValueError("配信が大きすぎます")
    return data


def items_from_source(src: dict, data: bytes, now: dt.datetime) -> tuple[list[dict], int]:
    """1つの取得元の配信から、載せる情報を取り出す。戻り値: (情報, 配信の全件数)"""
    entries = parse_feed(data)
    out = []
    for e in entries:
        title = clean_text(e["title"])
        source = clean_text(e["source"], 60)
        # Google ニュースはタイトルの末尾に「 - 掲載元」が付く
        if src.get("aggregator") and source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3].strip()
        url = safe_url(e["url"])
        if not title or not url:
            continue
        cat = is_relevant(title, clean_text(e["summary"], 600), src.get("topic"))
        if not cat:
            continue
        date = parse_date(e["date"]) or now
        if date > now + dt.timedelta(days=1):
            date = now
        out.append({
            "id": item_id(url),
            "title": title,
            "url": url,
            "source": source if (src.get("aggregator") and source) else src["name"],
            "via": src["id"],
            "lang": src.get("lang", "ja"),
            "category": cat,
            "official": bool(src.get("official")),
            "date": date.isoformat(timespec="minutes"),
            "origin": "auto",
        })
    return out, len(entries)


# ---------------------------------------------------------------- 保存とタイムラインの組み立て
def load_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"


def merge_collected(collected: list[dict], new: list[dict]) -> list[dict]:
    """前回までの情報に新しい情報を足す（同じ URL・同じタイトルは1件にまとめ、最初に見つけた日付を残す）。"""
    by_id = {c["id"]: c for c in collected}
    titles = {(c["title"].casefold(), c["lang"]) for c in collected}
    for n in new:
        key = (n["title"].casefold(), n["lang"])
        if n["id"] in by_id or key in titles:
            continue
        by_id[n["id"]] = n
        titles.add(key)
    return list(by_id.values())


def build_timeline(collected: list[dict], manual: list[dict], exclude: dict, now: dt.datetime) -> list[dict]:
    urls = set(exclude.get("urls") or [])
    words = [w.casefold() for w in exclude.get("keywords") or [] if w]
    oldest = now - dt.timedelta(days=MAX_AGE_DAYS)
    items = []
    for it in list(manual) + list(collected):
        if it.get("hidden") or it["url"] in urls or any(w in it["title"].casefold() for w in words):
            continue
        d = dt.datetime.fromisoformat(it["date"])
        if d < oldest and it.get("origin") != "manual":
            continue
        items.append({k: it[k] for k in ("id", "title", "url", "source", "lang", "category", "official", "date", "origin")})
    seen, unique = set(), []
    for it in sorted(items, key=lambda x: x["date"], reverse=True):
        if it["id"] in seen:
            continue
        seen.add(it["id"])
        unique.append(it)
    return unique[:MAX_ITEMS]


def timeline_json(now: dt.datetime) -> str:
    collected = load_json(DATA_DIR / "collected.json", [])
    manual = load_json(DATA_DIR / "manual.json", [])
    exclude = load_json(DATA_DIR / "exclude.json", {})
    links = load_json(DATA_DIR / "links.json", {}).get("links", [])
    items = build_timeline(collected, manual, exclude, now)
    return dump({"items": items, "links": links})


def write_if_changed(path: Path, text: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def collect(dry_run: bool, now: dt.datetime, fetcher=fetch) -> int:
    sources = load_json(DATA_DIR / "sources.json", {}).get("sources", [])
    found: list[dict] = []
    ok = 0
    for src in sources:
        try:
            items, total = items_from_source(src, fetcher(src["url"]), now)
            ok += 1
            found += items
            print(f"::notice title={src['id']}::{src['name']}: 配信 {total} 件 → 掲載候補 {len(items)} 件"
                  + "".join(f" / {i['title'][:40]}" for i in items[:3]))
        except Exception as e:  # 1つの取得元が失敗しても他は続ける
            print(f"::warning title={src['id']}::{src['name']}: 取得できませんでした（{type(e).__name__}: {str(e)[:120]}）")
    if dry_run:
        print(f"試し取得：{ok}/{len(sources)} 件の取得元から {len(found)} 件の候補（ファイルは書き換えていません）")
        return 0
    collected = merge_collected(load_json(DATA_DIR / "collected.json", []), found)
    collected.sort(key=lambda x: x["date"], reverse=True)
    collected = collected[: MAX_ITEMS * 2]
    changed = write_if_changed(DATA_DIR / "collected.json", dump(collected))
    changed |= write_if_changed(OUT_FILE, timeline_json(now))
    print(f"取得元 {ok}/{len(sources)} 件、新しい候補 {len(found)} 件、{'更新しました' if changed else '変更なし'}")
    return 0 if ok or not sources else 1


# ---------------------------------------------------------------- 入力フォーム（手動で追加）
FORM_FIELDS = {
    "リンク（URL）": "url",
    "ひとこと（タイトル）": "title",
    "種類": "category",
    "日付（任意）": "date",
    "言語": "lang",
    "掲載をやめる": "hide",
    "入稿の確認": "approval",
}
CATEGORY_LABELS = {"ピンバッジ": "pin", "ぬいぐるみ": "plush", "グッズ": "goods", "その他": "other"}
LANG_LABELS = {"日本語": "ja", "English": "en"}
ALLOWED_ASSOCIATIONS = {"OWNER", "COLLABORATOR", "MEMBER"}


def parse_form(body: str) -> dict[str, str]:
    values: dict[str, str] = {}
    current, buf = None, []
    for line in (body or "").replace("\r\n", "\n").split("\n"):
        m = re.match(r"^### (.+?)\s*$", line)
        if m and m.group(1) in FORM_FIELDS:
            if current:
                values[current] = "\n".join(buf).strip()
            current, buf = FORM_FIELDS[m.group(1)], []
        else:
            buf.append(line)
    if current:
        values[current] = "\n".join(buf).strip()
    return {k: ("" if v == "_No response_" else v) for k, v in values.items()}


def checked(text: str) -> bool:
    return bool(re.search(r"^- \[[xX]\]", text or "", re.M))


def add_manual(event: dict, now: dt.datetime) -> dict:
    issue = event.get("issue") or {}
    if issue.get("author_association") not in ALLOWED_ASSOCIATIONS:
        return {"skipped": "追加できるのはリポジトリの管理者だけです。"}
    form = parse_form(issue.get("body") or "")
    if "url" not in form:
        return {"skipped": "Acorn Club の入力フォームではありません。"}
    errors = []
    url = safe_url(form.get("url", "").split()[0] if form.get("url") else "")
    if not url:
        errors.append("リンク（URL）は https:// から始まる URL を1つ入れてください。")
    title = clean_text(form.get("title", ""), 200)
    if not title:
        errors.append("ひとこと（タイトル）を入れてください。")
    if not checked(form.get("approval", "")):
        errors.append("「入稿の確認」にチェックが入っていません。")
    date = now
    if form.get("date"):
        t = re.sub(r"[年月/.]", "-", form["date"].strip()).replace("日", "").strip()
        try:
            date = dt.datetime.strptime(t[:10], "%Y-%m-%d").replace(hour=12, tzinfo=JST)
        except ValueError:
            errors.append(f"日付「{form['date']}」を読み取れませんでした。2026-10-31 の形で入れてください。")
    if errors:
        return {"status": "error", "errors": errors}
    number = int(issue["number"])
    manual = [m for m in load_json(DATA_DIR / "manual.json", []) if m.get("issue") != number]
    hidden = checked(form.get("hide", ""))
    manual.append({
        "id": item_id(url),
        "title": title,
        "url": url,
        "source": source_from_host(url),
        "lang": LANG_LABELS.get(form.get("lang", "").strip(), "ja"),
        "category": CATEGORY_LABELS.get(form.get("category", "").strip(), "other"),
        "official": False,
        "date": date.isoformat(timespec="minutes"),
        "origin": "manual",
        "issue": number,
        "hidden": hidden,
    })
    manual.sort(key=lambda x: x["date"], reverse=True)
    write_if_changed(DATA_DIR / "manual.json", dump(manual))
    write_if_changed(OUT_FILE, timeline_json(now))
    return {"status": "hidden" if hidden else "added", "title": title, "url": url, "errors": []}


def comment_for(result: dict) -> str:
    if result.get("errors"):
        return "⚠️ **追加できませんでした。** 次の点を直して、このページを「Edit」で保存し直してください。\n\n" + \
            "\n".join(f"- {e}" for e in result["errors"])
    if result.get("status") == "hidden":
        return "🙈 **タイムラインから外しました。** もう一度載せるときは「掲載をやめる」のチェックを外して保存してください。"
    if result.get("status") == "added":
        return ("✅ **Acorn Club のタイムラインに追加しました。** 数分でサイトに反映されます。\n\n"
                "直したいときはこのページを「Edit」で保存し直してください。外したいときは「掲載をやめる」にチェックして保存します。")
    return ""


# ---------------------------------------------------------------- 入口
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--dry-run", action="store_true")
    b = sub.add_parser("build")
    b.add_argument("--check", action="store_true")
    a = sub.add_parser("add")
    a.add_argument("event")
    m = sub.add_parser("comment")
    m.add_argument("result")
    args = parser.parse_args()
    now = dt.datetime.now(JST)
    if args.cmd == "collect":
        return collect(args.dry_run, now)
    if args.cmd == "build":
        text = timeline_json(now)
        if args.check:
            current = OUT_FILE.read_text(encoding="utf-8") if OUT_FILE.exists() else None
            # 古い情報が時間の経過で外れる分は確認の対象にしない（日付の境目で CI が落ちないように）
            fresh = json.loads(text)
            saved = json.loads(current) if current else None
            ok = saved is not None and saved["links"] == fresh["links"] and \
                {i["id"] for i in fresh["items"]} <= {i["id"] for i in saved["items"]}
            print("確認OK" if ok else "⚠ acorn-club/news.json が最新ではありません（python3 tools/acorn_news.py build を実行してください）")
            return 0 if ok else 1
        print("更新しました" if write_if_changed(OUT_FILE, text) else "変更はありません")
        return 0
    if args.cmd == "add":
        result = add_manual(json.loads(Path(args.event).read_text(encoding="utf-8")), now)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if args.cmd == "comment":
        print(comment_for(json.loads(Path(args.result).read_text(encoding="utf-8"))))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
