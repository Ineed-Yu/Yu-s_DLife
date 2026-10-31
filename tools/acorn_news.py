#!/usr/bin/env python3
"""Acorn Club のタイムライン（クラリスの新着グッズ情報）を作るスクリプト。

  content/acorn/sources.json   … 取得元（RSS / Atom）
  content/acorn/collected.json … 自動で集めた情報（取得元の配信から消えても残す）
  content/acorn/manual.json    … 入力フォームから手動で追加した情報（SNS の投稿など）
  content/acorn/exclude.json   … 表示しない情報（URL・言葉）
  content/acorn/x_state.json   … X の検索の続きの位置と、今月読んだ件数（従量課金の上限管理）
        ↓
  acorn-club/news.json         … ページに表示するタイムライン（新しい順）

- 取り込むのは「タイトル・リンク・掲載元・日付」と、掲載元が共有用に指定した画像の「場所（URL）」だけ。
  記事の本文は取り込まず、画像もこのサイトには保存しない（ページでは掲載元にある画像をそのまま表示する）。
- 「クラリス / Clarice」と、ディズニーの話題であること、グッズ（ピンバッジ・ぬいぐるみ等）または登場情報
  （グリーティング・ショー・パレード・イベント）の話題であることの3つがそろう情報だけを残す。
  同じ名前の別作品（『カリオストロの城』のクラリス、『羊たちの沈黙』のクラリス など）は除く。
- リンクは http / https だけ。

使い方:
  python3 tools/acorn_news.py collect             # 取得元から集めて、タイムラインを作り直す（自動実行用）
  python3 tools/acorn_news.py collect --dry-run   # 書き換えずに、取得元ごとの結果を表示（PR での確認用）
  python3 tools/acorn_news.py backfill            # 過去の記事を期間ごとに探して取り込む（手動で1回）
  python3 tools/acorn_news.py images --dry-run    # 書き換えずに、記事の画像が見つかるかを試す（PR での確認用）
  python3 tools/acorn_news.py build               # 集めた情報からタイムラインだけ作り直す
  python3 tools/acorn_news.py build --check       # タイムラインが最新か・クラリス年表の書き方が正しいか確認する（CI 用）
  python3 tools/acorn_news.py add イベントのJSON   # 入力フォームの内容を手動の情報として追加（自動実行用）
  python3 tools/acorn_news.py comment 結果のJSON  # 入力フォームへのコメント文を作る
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import email.utils
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "content" / "acorn"
OUT_FILE = ROOT / "acorn-club" / "news.json"
JST = dt.timezone(dt.timedelta(hours=9))

MAX_ITEMS = 1000              # タイムラインに残す最大件数（年ごとに選んで見られるよう、過去の分も残す）
MAX_AGE_DAYS = 3650           # これより古い情報は載せない（約10年）
MAX_FEED_BYTES = 3 * 1024 * 1024
USER_AGENT = "AcornClubTimeline/1.0 (+https://divaclarice321.com/acorn-club/; unofficial fan page)"

# ---------------------------------------------------------------- 絞り込みの条件
CLARICE = re.compile(r"クラリス|clarice|克拉莉丝|克拉丽丝|克拉莉絲|克拉麗絲", re.I)
DISNEY = re.compile(r"ディズニー|disney|チップ|デール|chip\s*(?:'n'|n'|and|&)?\s*dale|ＴＤＲ|TDR|TDL|TDS|"
                    r"東京ディズニー|ショップディズニー|ディズニーストア|shopdisney|disneyland|epcot|magic kingdom|"
                    r"迪士尼|奇奇|蒂蒂|HKDL|SHDL|DLP", re.I)
OTHER_CLARICE = re.compile(r"カリオストロ|ルパン|lupin|cagliostro|starling|スターリング|羊たちの沈黙|silence of the lambs|"
                           r"hannibal|ハンニバル|lispector|リスペクトル|鲁邦|魯邦|卡里奥斯特罗|卡里奧斯特羅|沉默的羔羊|"
                           r"沉默的羔羊|史达琳|史達琳|silence des agneaux", re.I)
PIN = re.compile(r"ピンバッ?ジ|ピン(?:トレ|セット|バッチ)|\bpins?\b|pin trading|lanyard|徽章|胸针|胸針|pin's", re.I)
PLUSH = re.compile(r"ぬいぐるみ|ぬいば|ぬいバッジ|ツムツム|plush|tsum\s*tsum|stuffed|nuimos|毛绒|毛絨|公仔|玩偶|peluche", re.I)
GOODS = re.compile(r"グッズ|新商品|新作|発売|販売|新登場|コレクション|ストア|ショップ|キーチェーン|ストラップ|カチューシャ|"
                   r"ポーチ|バッグ|マグ|タオル|ステッカー|フィギュア|お菓子|スーベニア|"
                   r"merch|merchandise|collection|release|\bears\b|loungefly|\bmugs?\b|apparel|figure|ornament|"
                   r"spirit jersey|keychain|souvenir|shopdisney|new arrivals?|now available|coming soon|"
                   r"周边|周邊|商品|新品|上市|发售|發售|限定|精品|产品|產品|"
                   r"produits?|boutique|nouveaut[ée]s?|collection|en vente|sortie", re.I)
# 登場情報（グリーティング・ショー・パレード・イベント）
GREETING = re.compile(r"グリーティング|ミート|meet[\s-]*(?:and|&|'n'|n)?[\s-]*greet|greeting|character dining|"
                      r"キャラクターダイニング|キャラダイ|见面|見面|合影|rencontre", re.I)
PARADE = re.compile(r"パレード|parade|巡游|巡遊|défilé|cavalcade", re.I)
SHOW = re.compile(r"ショー|\bshows?\b|spectacle|表演|演出|ステージ|\bstage\b|花火|fireworks|ナイトタイム", re.I)
EVENT = re.compile(r"イベント|\bevents?\b|ハロウィ[ー]?ン|クリスマス|お正月|イースター|七夕|halloween|christmas|easter|"
                   r"周年|anniversary|万圣|萬聖|圣诞|聖誕|新年|初登場|登場|出演|衣装|コスチューム|costume|debut|デビュー|"
                   r"appear(?:s|ance)?|returns?", re.I)

GOODS_CATEGORIES = ("pin", "plush", "goods", "other")           # グッズ・新商品のタイムライン
APPEAR_CATEGORIES = ("greeting", "show", "parade", "event")     # 「パーク」のタイムライン
CATEGORIES = GOODS_CATEGORIES + APPEAR_CATEGORIES


def category_of(text: str, topic: str | None = None) -> str | None:
    """種類を返す。グッズの話題を優先（pin / plush / goods）、次に登場情報（greeting / parade / show / event）。"""
    if PIN.search(text) or topic == "pin":
        return "pin"
    if PLUSH.search(text):
        return "plush"
    if GOODS.search(text):
        return "goods"
    if GREETING.search(text):
        return "greeting"
    if PARADE.search(text):
        return "parade"
    if SHOW.search(text):
        return "show"
    if EVENT.search(text):
        return "event"
    return None


def is_relevant(title: str, summary: str, topic: str | None = None, require_disney: bool = True) -> str | None:
    """タイムラインに載せる情報か判定し、載せるなら種類を返す。"""
    text = f"{title}\n{summary}"
    if not CLARICE.search(text) or OTHER_CLARICE.search(text):
        return None
    if require_disney and not DISNEY.search(text) and topic != "pin":
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
            head = re.sub(r"\s+", " ", TAG.sub(" ", text[:2000])).strip()[:60]
            raise ValueError(f"RSS / Atom ではない応答でした（ページやブロック画面の可能性。冒頭: {head}）") from None
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
            cname = {"source": "source", "pubdate": "pubDate"}.get(cname.lower(), cname)  # Bing は News:Source
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


def unwrap_link(url: str) -> str:
    """Bing ニュースのリンク（bing.com/news/apiclick.aspx?url=元の記事）から元の記事の URL を取り出す。"""
    p = urllib.parse.urlparse(url)
    if (p.hostname or "").endswith("bing.com"):
        target = urllib.parse.parse_qs(p.query).get("url", [""])[0]
        if target.startswith(("http://", "https://")):
            return target
    return url


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
        url = safe_url(unwrap_link(e["url"] or ""))
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


# ---------------------------------------------------------------- 記事の画像（1件に1枚）
# 掲載元が「共有されたときに表示する画像」として指定している画像（og:image / twitter:image）の場所だけを記録し、
# ページではその場所のまま表示する（画像をこのサイトに保存・複製しない）。見つからなければ画像なしで表示する。
# Google ニュース経由の情報は、先に元の記事の URL を調べる（調べた URL はリンク先にも使い、元の記事へ直接飛べるようにする）。
IMAGE_TRIES_PER_RUN = 30       # 1回の収集で画像を探す件数の上限（掲載元への負担と実行時間を抑える）
MAX_PAGE_BYTES = 1_500_000
NO_IMAGE_HOSTS = ("x.com", "twitter.com", "instagram.com", "threads.net", "tiktok.com", "facebook.com")
GNEWS_ARTICLE = re.compile(r"^https://news\.google\.com/(?:rss/)?articles/([A-Za-z0-9_-]+)")
META_TAG = re.compile(r"<meta\b[^>]*>", re.I)
META_ATTR = re.compile(r"""([a-zA-Z:_-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
IMAGE_KEYS = ("og:image:secure_url", "og:image", "twitter:image", "twitter:image:src")


def http_get(url: str) -> tuple[str, str]:
    """ページを取得して（最終的な URL, HTML の文字列）を返す。"""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = r.read(MAX_PAGE_BYTES)
        final = r.geturl()
        charset = r.headers.get_content_charset() or "utf-8"
    return final, data.decode(charset, "replace")


def http_post_form(url: str, body: str) -> str:
    req = urllib.request.Request(url, data=body.encode("utf-8"), method="POST", headers={
        "User-Agent": USER_AGENT, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read(MAX_PAGE_BYTES).decode("utf-8", "replace")


def decode_gnews(url: str, get=http_get, post=http_post_form) -> str | None:
    """Google ニュースの記事 URL から、元の記事の URL を調べる。調べられなければ None。"""
    m = GNEWS_ARTICLE.match(url)
    if not m:
        return None
    gid = m.group(1)
    try:
        raw = base64.urlsafe_b64decode(gid + "=" * (-len(gid) % 4))
    except (ValueError, TypeError):
        raw = b""
    if raw and b"AU_yqL" not in raw:  # 古い形式：URL がそのまま入っている
        found = re.search(rb"https?://[\x21-\x7e]+", raw)
        return safe_url(found.group(0).decode("ascii")) if found else None
    _, page = get(f"https://news.google.com/rss/articles/{gid}")
    sig = re.search(r'data-n-a-sg="([^"]+)"', page)
    ts = re.search(r'data-n-a-ts="([^"]+)"', page)
    if not sig or not ts:
        return None
    req = ["Fbv4je", '["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,null,null,0,1],'
           f'"X","X",1,[1,1,1],1,1,null,0,0,null,0],"{gid}",{int(ts.group(1))},"{sig.group(1)}"]']
    text = post("https://news.google.com/_/DotsSplashUi/data/batchexecute",
                "f.req=" + urllib.parse.quote(json.dumps([[req]])))
    for line in text.splitlines():
        if line.startswith("[["):
            for row in json.loads(line):
                if isinstance(row, list) and len(row) > 2 and row[1] == "Fbv4je" and row[2]:
                    inner = json.loads(row[2])
                    if isinstance(inner, list) and len(inner) > 1 and inner[0] == "garturlres":
                        return safe_url(inner[1])
    return None


def find_share_image(page: str, base: str) -> str | None:
    """記事の HTML から、掲載元が指定した共有用の画像（https のもの）を探す。"""
    found: dict[str, str] = {}
    for tag in META_TAG.findall(page[:400_000]):
        attrs = {k.lower(): (v1 if v1 or not v2 else v2) for k, v1, v2 in META_ATTR.findall(tag)}
        key = (attrs.get("property") or attrs.get("name") or "").lower()
        if key in IMAGE_KEYS and attrs.get("content") and key not in found:
            found[key] = html.unescape(attrs["content"].strip())
    for key in IMAGE_KEYS:
        if key in found:
            url = urllib.parse.urljoin(base, found[key])
            if url.startswith("https://") and len(url) <= 1000 and safe_url(url):
                return url
    return None


def add_image(item: dict, get=http_get, post=http_post_form) -> str:
    """1件分の元記事と画像を調べて item に書き込む。戻り値は結果の説明（試し取得の表示用）。"""
    url = item["url"]
    article = url
    if GNEWS_ARTICLE.match(url):
        article = decode_gnews(url, get, post)
        if not article:
            item["image"] = ""
            return "元の記事を特定できませんでした"
        item["article"] = article
        time.sleep(0.5)
    host = (urllib.parse.urlparse(article).hostname or "").removeprefix("www.")
    if any(host == h or host.endswith("." + h) for h in NO_IMAGE_HOSTS):
        item["image"] = ""
        return "SNS のため画像は探しません"
    final, page = get(article)
    image = find_share_image(page, final)
    item["image"] = image or ""
    return image or "共有用の画像が指定されていません"


def add_images(items: list[dict], limit: int, dry_run: bool, get=http_get, post=http_post_form) -> int:
    """まだ画像を調べていない情報を、新しい順に最大 limit 件調べる。戻り値は調べた件数。"""
    tried = 0
    for item in sorted(items, key=lambda x: x.get("date", ""), reverse=True):
        if tried >= limit:
            break
        if "image" in item or item.get("origin") == "x" or item.get("tweet"):
            continue
        tried += 1
        target = dict(item) if dry_run else item
        try:
            note = add_image(target, get, post)
        except Exception as e:  # 1件失敗しても続ける。失敗したものは次回もう一度調べる（3回失敗したらあきらめる）
            target.pop("image", None)
            target["image_tries"] = int(target.get("image_tries") or 0) + 1
            if target["image_tries"] >= 3:
                target["image"] = ""
            note = f"取得できませんでした（{type(e).__name__}）"
        if dry_run:
            print(f"::notice title=画像::{item['title'][:30]} → {note[:120]}")
    return tried


# ---------------------------------------------------------------- X（旧 Twitter）の投稿
# 有料の X API（読んだ投稿の件数に応じた従量課金）を使う。キー（Secrets の X_BEARER_TOKEN）が無ければ何もしない。
# - 検索は「最近の投稿の検索」。前回の続きから読む（since_id）。1回に読むのは取得元ごとに最大 50 件
# - 月に読む件数の上限（Variables の X_MONTHLY_POST_LIMIT。既定 1300 件 ≒ 約1,000円）を超えないよう止める
# - 保存するのは投稿の ID・日付・言語・種類だけ（本文・画像・投稿者情報は保存しない）。表示は X の公式の埋め込み
X_SEARCH_URL = "https://api.x.com/2/tweets/search/recent"
X_STATE_FILE = DATA_DIR / "x_state.json"
X_DEFAULT_MONTHLY_LIMIT = 1300
X_LANGS = {"ja": "ja", "en": "en", "fr": "fr", "zh": "zh", "zh-cn": "zh", "zh-tw": "zh"}


def x_search(query: str, token: str, since_id: str | None, max_results: int) -> dict:
    params = {"query": query, "max_results": str(max_results), "tweet.fields": "created_at,lang"}
    if since_id:
        params["since_id"] = since_id
    req = urllib.request.Request(f"{X_SEARCH_URL}?{urllib.parse.urlencode(params)}",
                                 headers={"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read(MAX_FEED_BYTES).decode("utf-8"))


def collect_x(src: dict, token: str, state: dict, limit: int, now: dt.datetime, search=x_search) -> tuple[list[dict], int]:
    """X の検索結果から載せる投稿を取り出す。state（月・読んだ件数・前回の位置）を更新する。"""
    month = now.strftime("%Y-%m")
    if state.get("month") != month:
        state["month"], state["reads"] = month, 0
    remaining = limit - state.get("reads", 0)
    if remaining < 10:
        raise RuntimeError(f"今月の上限（{limit} 件）に達したため停止中です")
    since = (state.setdefault("since", {})).get(src["id"])
    res = search(src["query"], token, since, max(10, min(50, remaining)))
    tweets = res.get("data") or []
    state["reads"] = state.get("reads", 0) + len(tweets)
    newest = (res.get("meta") or {}).get("newest_id")
    if newest:
        state["since"][src["id"]] = newest
    out = []
    for t in tweets:
        tid = str(t.get("id", ""))
        if not tid.isdigit():
            continue
        cat = is_relevant(t.get("text", ""), "", src.get("topic"), require_disney=False)
        if not cat:
            continue
        date = parse_date(t.get("created_at")) or now
        url = f"https://x.com/i/status/{tid}"
        out.append({
            "id": item_id(url), "title": "", "url": url, "source": "X", "via": src["id"],
            "lang": X_LANGS.get((t.get("lang") or "").lower(), "other"), "category": cat, "official": False,
            "date": date.isoformat(timespec="minutes"), "origin": "x", "tweet": tid,
        })
    return out, len(tweets)


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
        if n["id"] in by_id or (n["title"] and key in titles):  # 見出しの無いもの（X の投稿）は ID だけで比べる
            continue
        by_id[n["id"]] = n
        if n["title"]:
            titles.add(key)
    return list(by_id.values())


def build_timeline(collected: list[dict], manual: list[dict], exclude: dict, now: dt.datetime) -> list[dict]:
    urls = set(exclude.get("urls") or [])
    words = [w.casefold() for w in exclude.get("keywords") or [] if w]
    oldest = now - dt.timedelta(days=MAX_AGE_DAYS)
    items = []
    for it in list(manual) + list(collected):
        if it.get("hidden") or it["url"] in urls or it.get("article") in urls or any(w in it["title"].casefold() for w in words):
            continue
        d = dt.datetime.fromisoformat(it["date"])
        if d < oldest and it.get("origin") != "manual":
            continue
        item = {k: it[k] for k in ("id", "title", "url", "source", "lang", "category", "official", "date", "origin")}
        if it.get("tweet"):
            item["tweet"] = it["tweet"]
        if safe_url(it.get("article")):
            item["url"] = it["article"]  # Google ニュース経由のものは、元の記事へ直接リンクする
        if (it.get("image") or "").startswith("https://"):
            item["image"] = it["image"]
        items.append(item)
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


HISTORY_FILE = ROOT / "acorn-club" / "history.json"
HISTORY_PARKS = {"film", "tdl", "tds", "dl", "wdw", "dlp", "shdl", "hkdl", "aulani"}
HISTORY_KINDS = {"work", "show", "parade", "greeting", "event"}


def check_history(data: dict) -> list[str]:
    """クラリス年表（acorn-club/history.json）の書き方を確かめる。問題の一覧を返す（空なら OK）。"""
    problems = []
    for n, e in enumerate(data.get("entries") or [], 1):
        where = f"{n}件目（{(e.get('title') or {}).get('ja', '')}）"
        if not re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?", str(e.get("date", ""))):
            problems.append(f"{where}: date は YYYY / YYYY-MM / YYYY-MM-DD で書いてください")
        if e.get("park") not in HISTORY_PARKS:
            problems.append(f"{where}: park が不明です（{e.get('park')}）")
        if e.get("kind") not in HISTORY_KINDS:
            problems.append(f"{where}: kind が不明です（{e.get('kind')}）")
        if not (e.get("title") or {}).get("ja") or not (e.get("title") or {}).get("en"):
            problems.append(f"{where}: title は ja と en の両方が必要です")
        src = e.get("source") or {}
        if not src.get("name") or not (src.get("url") or "").startswith("https://"):
            problems.append(f"{where}: 出典（source の name と https の url）が必要です")
    for src in (data.get("profile") or {}).get("sources") or []:
        if not (src.get("url") or "").startswith("https://"):
            problems.append("プロフィールの出典の url は https で書いてください")
    return problems


def write_if_changed(path: Path, text: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def collect(dry_run: bool, now: dt.datetime, fetcher=fetch, x_search_fn=x_search) -> int:
    sources = load_json(DATA_DIR / "sources.json", {}).get("sources", [])
    found: list[dict] = []
    ok = 0
    x_token = os.environ.get("X_BEARER_TOKEN", "").strip()
    try:
        x_limit = int(os.environ.get("X_MONTHLY_POST_LIMIT") or X_DEFAULT_MONTHLY_LIMIT)
    except ValueError:
        x_limit = X_DEFAULT_MONTHLY_LIMIT
    x_state = load_json(X_STATE_FILE, {})
    notes: list[str] = []   # 取得元ごとの結果（GitHub の注記は1ステップ10件までしか出ないため、最後に要約を先頭にして出す）
    tally: list[str] = []
    for src in sources:
        if src.get("type") == "x":
            if not x_token:
                notes.append(f"::notice title={src['id']}::{src['name']}: X のキー（X_BEARER_TOKEN）が未登録のため停止中")
                continue
            if dry_run:  # 試し取得では課金されないよう、X は読まない
                notes.append(f"::notice title={src['id']}::{src['name']}: 試し取得では X を読みません（費用がかかるため）")
                continue
            try:
                items, total = collect_x(src, x_token, x_state, x_limit, now, x_search_fn)
                ok += 1
                found += items
                notes.append(f"::notice title={src['id']}::{src['name']}: 投稿 {total} 件 → 掲載 {len(items)} 件（今月 {x_state.get('reads', 0)}/{x_limit} 件）")
            except Exception as e:
                notes.append(f"::warning title={src['id']}::{src['name']}: 取得できませんでした（{type(e).__name__}: {str(e)[:120]}）")
                tally.append(f"{src['id']} ×")
            continue
        try:
            items, total = items_from_source(src, fetcher(src["url"]), now)
            ok += 1
            found += items
            tally.append(f"{src['id']} {len(items)}/{total}")
            notes.append(f"::notice title={src['id']}::{src['name']}: 配信 {total} 件 → 掲載候補 {len(items)} 件"
                  + "".join(f" / {i['title'][:40]}" for i in items[:3]))
        except Exception as e:  # 1つの取得元が失敗しても他は続ける
            notes.append(f"::warning title={src['id']}::{src['name']}: 取得できませんでした（{type(e).__name__}: {str(e)[:120]}）")
            tally.append(f"{src['id']} ×")
    print(f"::notice title=まとめ::取得元 {ok}/{len(sources)} 件・候補 {len(found)} 件（取得元 候補/配信）: " + "、".join(tally))
    for line in notes:
        print(line)
    if dry_run:
        print(f"試し取得：{ok}/{len(sources)} 件の取得元から {len(found)} 件の候補（ファイルは書き換えていません）")
        return 0
    collected = merge_collected(load_json(DATA_DIR / "collected.json", []), found)
    collected.sort(key=lambda x: x["date"], reverse=True)
    collected = collected[: MAX_ITEMS * 2]
    manual = load_json(DATA_DIR / "manual.json", [])
    tried = add_images(manual, IMAGE_TRIES_PER_RUN, False)
    tried += add_images(collected, IMAGE_TRIES_PER_RUN - tried, False)
    if tried:
        print(f"記事の画像を {tried} 件調べました")
    changed = write_if_changed(DATA_DIR / "collected.json", dump(collected))
    if manual:
        changed |= write_if_changed(DATA_DIR / "manual.json", dump(manual))
    if x_state:
        changed |= write_if_changed(X_STATE_FILE, dump(x_state))
    changed |= write_if_changed(OUT_FILE, timeline_json(now))
    print(f"取得元 {ok}/{len(sources)} 件、新しい候補 {len(found)} 件、{'更新しました' if changed else '変更なし'}")
    return 0 if ok or not sources else 1


# ---------------------------------------------------------------- 過去分の取り込み（backfill）
# Google ニュースの検索は新しい順の上位しか返さないため、期間（after: / before:）を区切って過去の記事を探す。
# 手動の実行（Actions の「Acorn Club の自動収集」で backfill を選ぶ）で1回だけ動かす想定。
BACKFILL_SINCE = 2016
BACKFILL_MONTHS = 3            # 1回の検索で区切る期間（月）


def backfill_windows(now: dt.datetime, since: int = BACKFILL_SINCE, months: int = BACKFILL_MONTHS) -> list[tuple[str, str]]:
    out, y, m = [], since, 1
    while dt.date(y, m, 1) <= now.date():
        start = dt.date(y, m, 1)
        m2, y2 = m + months, y
        while m2 > 12:
            m2, y2 = m2 - 12, y2 + 1
        out.append((start.isoformat(), dt.date(y2, m2, 1).isoformat()))
        y, m = y2, m2
    return out


def windowed_url(url: str, after: str, before: str) -> str:
    p = urllib.parse.urlparse(url)
    q = urllib.parse.parse_qs(p.query)
    q["q"] = [f"{q.get('q', [''])[0]} after:{after} before:{before}"]
    return urllib.parse.urlunparse(p._replace(query=urllib.parse.urlencode({k: v[0] for k, v in q.items()})))


def backfill(dry_run: bool, now: dt.datetime, windows: int | None = None, fetcher=fetch, pause: float = 1.0) -> int:
    sources = [s for s in load_json(DATA_DIR / "sources.json", {}).get("sources", [])
               if s.get("backfill") and "news.google.com/rss/search" in s.get("url", "")]
    spans = backfill_windows(now)
    if windows:
        spans = spans[-windows:]
    found: list[dict] = []
    fails = 0
    per_source: dict[str, int] = {}
    for src in sources:
        for after, before in spans:
            try:
                items, _ = items_from_source(src, fetcher(windowed_url(src["url"], after, before)), now)
                found += items
                per_source[src["id"]] = per_source.get(src["id"], 0) + len(items)
            except Exception as e:
                fails += 1
                print(f"{src['id']} {after}〜{before}: 取得できませんでした（{type(e).__name__}）")
            time.sleep(pause)
    summary = "、".join(f"{k} {v}" for k, v in per_source.items())
    print(f"::notice title=過去分::{len(sources)} 件の検索 × {len(spans)} 期間 → 候補 {len(found)} 件（失敗 {fails} 回）: {summary}")
    for it in sorted(found, key=lambda x: x["date"])[:8]:
        print(f"::notice title=過去分の例::{it['date'][:10]} {it['title'][:50]}")
    if dry_run:
        return 0
    collected = merge_collected(load_json(DATA_DIR / "collected.json", []), found)
    collected.sort(key=lambda x: x["date"], reverse=True)
    collected = collected[: MAX_ITEMS * 2]
    changed = write_if_changed(DATA_DIR / "collected.json", dump(collected))
    changed |= write_if_changed(OUT_FILE, timeline_json(now))
    print("更新しました" if changed else "変更なし")
    return 0


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
CATEGORY_LABELS = {"ピンバッジ": "pin", "ぬいぐるみ": "plush", "グッズ": "goods", "その他（グッズ）": "other", "その他": "other",
                   "グリーティング": "greeting", "ショー": "show", "パレード": "parade", "特別イベント": "event",
                   "イベント・その他の登場": "event"}
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
    bf = sub.add_parser("backfill")
    bf.add_argument("--dry-run", action="store_true")
    bf.add_argument("--windows", type=int, help="新しい方から、この数の期間だけ調べる（試し用）")
    im = sub.add_parser("images")
    im.add_argument("--dry-run", action="store_true")
    im.add_argument("--limit", type=int, default=8)
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
    if args.cmd == "backfill":
        return backfill(args.dry_run, now, args.windows)
    if args.cmd == "images":
        # 試し：まだ画像を調べていない情報のうち新しいものを、ファイルを書き換えずに調べて結果を表示する
        items = load_json(DATA_DIR / "manual.json", []) + load_json(DATA_DIR / "collected.json", [])
        tried = add_images(items, args.limit, True)
        print(f"試し：{tried} 件の記事の画像を調べました（ファイルは書き換えていません）")
        return 0
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
            problems = check_history(load_json(HISTORY_FILE, {}))
            for msg in problems:
                print(f"::error title=クラリス年表::{msg}")
            return 0 if ok and not problems else 1
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
