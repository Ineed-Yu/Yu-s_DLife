#!/usr/bin/env python3
"""クラリス年表を、管理者の Notion のデータベースから取り込む。

  Notion「クラリス年表管理」→「クラリス年表」データベースのうち、公開状態が「公開」の項目だけを読み、
  acorn-club/history.json の entries を置き換える（プロフィールはこのファイルに手で書いたものをそのまま残す）。

  python3 tools/acorn_history.py            # 取り込んで history.json を更新（自動実行用）
  python3 tools/acorn_history.py --dry-run  # 書き換えずに結果だけ表示

- 連携用のキー（GitHub の Secrets の NOTION_TOKEN）が未登録なら何もしない。
- 読むだけ（Notion には書き込まない）。写真・動画（メディアのデータベース）はまだ取り込まない。
- 安全のため、Notion から読めなかったとき・「公開」が0件のときは history.json を変えない。
- データベースの場所は Variables の NOTION_HISTORY_DB で変えられる（既定は下の ID）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import acorn_news as core  # noqa: E402

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
DEFAULT_DB = "8b5d8f1e7d7d82fd8eb50135ec034c61"   # Notion「クラリス年表」データベース（ID だけでは読めない。キーが必要）
MAX_PAGES = 30   # 100件 × 30 = 3000件まで

# Notion の「パーク」→ サイトの区分（park）と、表示する場所の名前
PARKS = {
    "東京ディズニーランド": ("tdl", None),
    "東京ディズニーシー": ("tds", None),
    "ディズニーランド": ("dl", {"ja": "ディズニーランド", "en": "Disneyland Park"}),
    "ディズニー・カリフォルニア・アドベンチャー": ("dl", {"ja": "ディズニー・カリフォルニア・アドベンチャー", "en": "Disney California Adventure"}),
    "マジックキングダム": ("wdw", {"ja": "マジックキングダム", "en": "Magic Kingdom"}),
    "エプコット": ("wdw", {"ja": "エプコット", "en": "EPCOT"}),
    "ディズニーランド・パーク（パリ）": ("dlp", {"ja": "ディズニーランド・パーク", "en": "Disneyland Park"}),
    "ウォルト・ディズニー・スタジオ・パーク": ("dlp", {"ja": "ウォルト・ディズニー・スタジオ・パーク", "en": "Walt Disney Studios Park"}),
    "香港ディズニーランド": ("hkdl", None),
    "上海ディズニーランド": ("shdl", None),
}
# 「パーク」が空のときは「リゾート・施設」から
RESORTS = {
    "東京ディズニーリゾート": "tdl",
    "ディズニーランド・リゾート": "dl",
    "ウォルト・ディズニー・ワールド": "wdw",
    "ディズニーランド・パリ": "dlp",
    "香港ディズニーランド": "hkdl",
    "上海ディズニーランド": "shdl",
}
KINDS = {"ショー": "show", "パレード": "parade", "グリーティング": "greeting", "その他": "event"}


def notion_query(db: str, token: str, opener=urllib.request.urlopen) -> list[dict]:
    """データベースの「公開」の項目をすべて読む。"""
    rows, cursor = [], None
    for _ in range(MAX_PAGES):
        body = {"page_size": 100, "filter": {"property": "公開状態", "select": {"equals": "公開"}}}
        if cursor:
            body["start_cursor"] = cursor
        req = urllib.request.Request(
            f"{NOTION_API}/databases/{urllib.parse.quote(db)}/query", data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION, "Content-Type": "application/json"},
            method="POST")
        with opener(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
        rows += data.get("results", [])
        cursor = data.get("next_cursor")
        if not data.get("has_more") or not cursor:
            break
    return rows


def _text(prop: dict | None) -> str:
    if not prop:
        return ""
    parts = prop.get("title") or prop.get("rich_text") or []
    return core.clean_text("".join(p.get("plain_text", "") for p in parts), 600)


def _select(prop: dict | None) -> str:
    return ((prop or {}).get("select") or {}).get("name") or ""


def _date(props: dict, day: str, year: str) -> str:
    """「開始日」があればその日付、無ければ「開始年」の年。"""
    start = (((props.get(day) or {}).get("date") or {}).get("start") or "")[:10]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", start):
        return start
    n = (props.get(year) or {}).get("number")
    return str(int(n)) if isinstance(n, (int, float)) and 1900 <= n <= 2100 else ""


def to_entry(row: dict) -> tuple[dict | None, str]:
    """Notion の1項目 → 年表の1件。載せられないときは (None, 理由)。"""
    p = row.get("properties") or {}
    work = _text(p.get("作品名"))
    title = _text(p.get("年表項目")) or work
    if not title:
        return None, "年表項目（タイトル）が空"
    date = _date(p, "開始日", "開始年")
    if not date:
        return None, f"「{title}」: 開始日か開始年が必要"
    entry: dict = {"date": date, "title": {"ja": title}, "origin": "notion"}
    end = _date(p, "終了日", "終了年")
    if end and end > date:
        entry["end"] = end
    if _select(p.get("大区分")) == "作品":
        entry["park"], entry["kind"] = "film", "work"
    else:
        park = _select(p.get("パーク"))
        if park in PARKS:
            entry["park"], place = PARKS[park]
            if place:
                entry["place"] = place
        elif _select(p.get("リゾート・施設")) in RESORTS:
            entry["park"] = RESORTS[_select(p.get("リゾート・施設"))]
        else:
            return None, f"「{title}」: パーク（またはリゾート・施設）が必要"
        entry["kind"] = KINDS.get(_select(p.get("内容区分")), "event")
    details = []
    if work and work != title:
        details.append(work)
    if _text(p.get("版・衣装")):
        details.append(_text(p.get("版・衣装")))
    if details:
        entry["edition"] = {"ja": "／".join(details)}
    if _text(p.get("概要・注記")):
        entry["note"] = {"ja": _text(p.get("概要・注記"))}
    url = core.safe_url((p.get("出典URL") or {}).get("url") or "")
    if url and core.is_safe_url(url):
        entry["source"] = {"name": core.source_from_host(url), "url": url}
    return entry, ""


def run(dry_run: bool, opener=urllib.request.urlopen) -> int:
    token = os.environ.get("NOTION_TOKEN", "").strip()
    if not token:
        print("::notice title=クラリス年表::Notion の連携用キー（NOTION_TOKEN）が未登録のため、取り込みは停止中")
        return 0
    db = re.sub(r"[^0-9a-fA-F]", "", os.environ.get("NOTION_HISTORY_DB", "") or DEFAULT_DB)
    try:
        rows = notion_query(db, token, opener)
    except Exception as e:   # 読めなかったときは、今の年表をそのまま残す
        print(f"::warning title=クラリス年表::Notion から読めませんでした（{type(e).__name__}: {str(e)[:120]}）。年表は変えていません")
        return 0
    entries, skipped = [], []
    for row in rows:
        entry, why = to_entry(row)
        if entry:
            entries.append(entry)
        else:
            skipped.append(why)
    for why in skipped[:8]:
        print(f"::warning title=クラリス年表（載せられない項目）::{why}")
    if not entries:
        print("::notice title=クラリス年表::Notion に「公開」の項目がまだ無いため、年表は変えていません")
        return 0
    entries.sort(key=lambda e: (e["date"], e["title"]["ja"]))
    data = core.load_json(core.HISTORY_FILE, {})
    data["entries"] = entries
    problems = core.check_history(data)
    if problems:
        for line in problems[:8]:
            print(f"::warning title=クラリス年表::{line}")
        print("::warning title=クラリス年表::書き方に問題があるため、年表は変えていません")
        return 0
    years = f"{entries[0]['date'][:4]}〜{entries[-1]['date'][:4]}年"
    print(f"::notice title=クラリス年表::Notion の「公開」{len(entries)} 件（{years}）を取り込み" + (f"・載せられない項目 {len(skipped)} 件" if skipped else ""))
    if dry_run:
        return 0
    changed = core.write_if_changed(core.HISTORY_FILE, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print("更新しました" if changed else "変更なし")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    sys.exit(run(ap.parse_args().dry_run))
