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
  python3 tools/acorn_news.py source イベントのJSON  # 取得元の入力フォームから、取得元を追加（自動実行用）
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
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "content" / "acorn"
OUT_FILE = ROOT / "acorn-club" / "news.json"
JST = dt.timezone(dt.timedelta(hours=9))

MAX_ITEMS = 1000              # タイムラインに残す最大件数（年ごとに選んで見られるよう、過去の分も残す）
MAX_AGE_DAYS = 365 * 30       # これより古い情報は載せない（約30年。クラリスのパーク登場の歴史をさかのぼれるように）
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
# プライズ：くじ・ゲームセンター（クレーンゲーム）の景品・カプセルトイなど、買うのではなく「当てる・取る」もの
PRIZE = re.compile(r"プライズ|くじ|クジ|ゲームセンター|ゲーセン|クレーンゲーム|UFOキャッチャー|景品|セガプライズ|タイトー|"
                   r"バンプレスト|ナムコ|ガチャ|カプセルトイ|\bprizes?\b|claw machine|arcade|lottery|kuji|抽奖|扭蛋|娃娃机", re.I)
# その他の「物」（グッズ・お土産・食べ物・飾り・客室など）。パークで会える情報ではないものは、すべてグッズ側に入れる
GOODS = re.compile(r"グッズ|新商品|新作|発売|販売|新登場|コレクション|ストア|ショップ|キーチェーン|ストラップ|カチューシャ|"
                   r"ポーチ|バッグ|マグ|タオル|ステッカー|フィギュア|お菓子|スーベニア|カンバッジ|缶バッジ|バッジ|アクリル|"
                   r"メニュー|フード|スイーツ|ケーキ|ドリンク|カクテル|ランチ|ディナーセット|スペシャルセット|おみやげ|お土産|"
                   r"デコレーション|装飾|客室|ルーム|ポストカード|文具|雑貨|アパレル|Tシャツ|コスチューム|福袋|コラボ|"
                   r"スリッパ|パズル|ジグソー|パスケース|ショルダー|プラッシー|ダイソー|出店|ポップアップ|ケース|ブランケット|"
                   r"ショーツ|マット|きっぷ|切符|フリーきっぷ|スナップフォト|"
                   r"merch|merchandise|collection|release|\bears\b|loungefly|\bmugs?\b|apparel|figure|ornament|"
                   r"spirit jersey|keychain|souvenir|shopdisney|new arrivals?|now available|coming soon|snacks?|treats?|menu|"
                   r"周边|周邊|商品|新品|上市|发售|發售|精品|产品|產品|美食|"
                   r"produits?|boutique|nouveaut[ée]s?|collection|en vente|sortie", re.I)
# パーク：クラリスに「会う・見る」ための情報だけ（ショー・パレード・グリーティング・貸切や特別営業などでの登場）
GREETING = re.compile(r"グリーティング|ミート|会える|会おう|会いに|会う方法|meet[\s-]*(?:and|&|'n'|n)?[\s-]*greet|greeting|character dining|"
                      r"キャラクターダイニング|キャラダイ|见面|見面|合影|rencontre", re.I)
PARADE = re.compile(r"パレード|parade|巡游|巡遊|défilé|cavalcade", re.I)
SHOW = re.compile(r"ショー(?![ツトケ])|\bshows?\b|spectacle|表演|ステージ|\bstage\b|花火|fireworks|ナイトタイム", re.I)
EVENT = re.compile(r"貸切|貸し切り|特別営業|プライベート・?イブニング|アフター6|スペシャルナイト|ナイトパーティ|パーティ|"
                   r"\bpart(?:y|ies)\b|after hours|celebration|セレブレーション|fan ?daze|D23|ファンイベント|"
                   r"エンターテイメントプログラム|イベント|\bevents?\b|活动|活動", re.I)
APPEAR_WORD = re.compile(r"登場|出演|デビュー|debut|appear(?:s|ance)?|会え", re.I)   # 弱い言葉（グッズの見出しにもよく使われる）
# パークの話題であることの手がかり。特別イベント・「登場」はこれがあるときだけパーク側にする
PARK_CONTEXT = re.compile(r"ディズニーランド|ディズニーシー|ディズニーリゾート|ＴＤＲ|TDR|TDL|TDS|パーク|トゥーンタウン|"
                          r"Disneyland|DisneySea|Disney World|Magic Kingdom|Epcot|Hollywood Studios|Animal Kingdom|"
                          r"California Adventure|\bparks?\b|\bresort\b|乐园|樂園|度假区|度假區|parc|"
                          r"グリズリー・?ガルチ|Grizzly Gulch|トゥモローランド|ファンタジーランド|アドベンチャーランド|"
                          r"ウエスタンランド|クリッターカントリー|メインストリート|ワールドバザール|メディテレーニアンハーバー|"
                          r"アメリカンウォーターフロント|ポートディスカバリー|ロストリバーデルタ|マーメイドラグーン|"
                          r"アラビアンコースト|ミステリアスアイランド|ファンタジースプリングス|Main Street|Toontown|Adventureland|"
                          r"上海|香港|舞浜", re.I)
# パークでもグッズでもない話題（映画・配信・書籍の紹介など）
NOT_PARK = re.compile(r"作品紹介|映画|streaming|tv show|DVD|Blu-ray|小説|絵本|ゲームアプリ", re.I)

GOODS_CATEGORIES = ("plush", "pin", "prize", "other", "goods")  # グッズのタイムライン（goods は古い分類。表示は「その他」）
APPEAR_CATEGORIES = ("show", "parade", "greeting", "event")     # 「パーク」のタイムライン
CATEGORIES = GOODS_CATEGORIES + APPEAR_CATEGORIES


def category_of(text: str, topic: str | None = None) -> str | None:
    """種類を返す。「物」の話題（プライズ・ピンバッジ・ぬいぐるみ・その他）を優先し、
    物の話題が無いときだけパーク（グリーティング・パレード・ショー・特別イベント）にする。"""
    if PRIZE.search(text):
        return "prize"
    if PIN.search(text) or topic == "pin":
        return "pin"
    if PLUSH.search(text):
        return "plush"
    if GOODS.search(text):
        return "other"
    park = PARK_CONTEXT.search(text)
    if NOT_PARK.search(text) and not park:
        return None
    if GREETING.search(text):
        return "greeting"
    if PARADE.search(text):
        return "parade"
    if SHOW.search(text):
        return "show"
    if EVENT.search(text) or APPEAR_WORD.search(text):
        # パークの手がかりがあれば特別イベント。無ければ「物」の紹介（〇〇も登場！など）とみなしてグッズの「その他」
        return "event" if park else "other"
    return None


# 記事ではないページ（写真ギャラリーの1枚ごとのページなど）
NOISE_TITLE = re.compile(r"画像・写真\s*[|｜]|\d+\s*枚目|写真\s*\d+\s*/\s*\d+|photo gallery \d+", re.I)


def is_relevant(title: str, summary: str, topic: str | None = None, require_disney: bool = True,
                require_clarice: bool = True) -> str | None:
    """タイムラインに載せる情報か判定し、載せるなら種類を返す。
    require_clarice=False は「クラリス」でのサイト内検索の結果など、本文にクラリスが出てくることが確かな取得元用。"""
    text = f"{title}\n{summary}"
    if NOISE_TITLE.search(title):
        return None
    if OTHER_CLARICE.search(text) or (require_clarice and not CLARICE.search(text)):
        return None
    if require_disney and not DISNEY.search(text) and topic != "pin":
        return None
    return pick_category(category_of(title, topic), category_of(text, topic))


def pick_category(by_title: str | None, by_text: str | None) -> str | None:
    """見出しで種類が決まるときは見出しを優先する（要約に関連記事の言葉が混ざって種類がずれるのを防ぐ）。
    ただし見出しの「登場」などの弱い言葉だけで特別イベントにはせず、グッズの話題なら全体の判定を使う。
    見出しが「グッズ」で全体がピンバッジ・ぬいぐるみなら、より詳しい方を使う。"""
    if not by_title:
        return by_text
    if by_title == "other" and by_text in ("pin", "plush", "prize"):
        return by_text
    return by_title


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


# 安全の確認：セキュリティ上問題のありそうなリンクは載せない（ニュース以外の取得元を広げたため、すべての情報に行う）
# - https だけ（通信が暗号化されていないページは載せない）
# - IP アドレスだけの URL、ログイン情報入りの URL、標準以外のポート番号、国際化ドメイン（見た目をまねた偽サイトに使われやすい）は除く
# - 短縮 URL（行き先が見えない）、ファイル配布・ダウンロードのリンク、悪用が多いトップレベルドメインは除く
RISKY_TLDS = {"zip", "mov", "top", "xyz", "click", "gq", "tk", "ml", "cf", "ga", "work", "loan", "men", "country",
              "kim", "science", "party", "gdn", "racing", "review", "stream", "download", "cam", "rest", "icu", "bid"}
BLOCKED_HOSTS = {"bit.ly", "t.co", "tinyurl.com", "goo.gl", "ow.ly", "is.gd", "buff.ly", "cutt.ly", "rebrand.ly", "shorturl.at",
                 "lnkd.in", "amzn.to", "amzn.asia", "x.gd", "rb.gy", "t.ly", "mega.nz", "mediafire.com", "4shared.com",
                 "drive.google.com", "dropbox.com", "wetransfer.com"}
RISKY_EXT = re.compile(r"\.(exe|msi|apk|dmg|pkg|bat|cmd|scr|js|vbs|jar|zip|rar|7z|iso|torrent)$", re.I)


def is_safe_url(url: str | None) -> bool:
    try:
        p = urllib.parse.urlparse(url or "")
        port = p.port
    except ValueError:
        return False
    host = (p.hostname or "").lower().rstrip(".")
    if p.scheme != "https" or not host or p.username or p.password or (port not in (None, 443)):
        return False
    if re.fullmatch(r"[\d.]+", host) or ":" in host or "xn--" in host:
        return False
    if host.rsplit(".", 1)[-1] in RISKY_TLDS:
        return False
    if any(host == h or host.endswith("." + h) for h in BLOCKED_HOSTS):
        return False
    return not RISKY_EXT.search(p.path)


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
            elif cname in ("encoded", "content"):  # 本文（content:encoded / Atom の content）。クラリスが本文に出てくるかの確認だけに使う
                fields.setdefault("content", "".join(child.itertext())[:200_000])
        entries.append({
            "title": fields.get("title", ""),
            "url": link,
            "date": fields.get("pubDate") or fields.get("published") or fields.get("date") or fields.get("updated"),
            "summary": fields.get("description") or fields.get("summary") or "",
            "source": fields.get("source", ""),
            "content": fields.get("content", ""),
        })
    return entries


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"})
    with urllib.request.urlopen(req, timeout=25) as r:
        data = r.read(MAX_FEED_BYTES + 1)
    if len(data) > MAX_FEED_BYTES:
        raise ValueError("配信が大きすぎます")
    return data


HEADING_OR_CAPTION = re.compile(r"<h[1-4][^>]*>(.*?)</h[1-4]>|<figcaption[^>]*>(.*?)</figcaption>|\balt=\"([^\"]*)\"", re.I | re.S)


def clarice_is_featured(content_html: str) -> bool:
    """本文（HTML）の中で、クラリスが主な話題のひとつか（小見出し・画像の説明に出てくる）。"""
    if not content_html:
        return False
    content_html = re.sub(r"<a\b[^>]*>.*?</a>", " ", content_html[:300_000], flags=re.I | re.S)  # 関連記事などのリンクは数えない
    if OTHER_CLARICE.search(clean_text(content_html, 200_000)):
        return False
    # 本文での出現回数は数えない（サイドバーや定型文に名前が出るだけの記事が混ざったため）
    return any(CLARICE.search(" ".join(g for g in m if g)) for m in HEADING_OR_CAPTION.findall(content_html[:200_000]))


ANCHOR = re.compile(r"<a\b[^>]*?href=(?:\"([^\"]+)\"|'([^']+)')[^>]*>(.*?)</a>", re.I | re.S)


def page_items(src: dict, final_url: str, page: str, now: dt.datetime) -> tuple[list[dict], int]:
    """RSS の無いサイトの検索結果・一覧のページから、リンクの文字に「クラリス」を含む記事を拾う（同じサイト内のリンクだけ）。
    日付は分からないため、初めて見つけた日時にする。"""
    host = (urllib.parse.urlparse(final_url).hostname or "").removeprefix("www.")
    out, seen, total = [], set(), 0
    for h1, h2, inner in ANCHOR.findall(page[:2_000_000]):
        url = urllib.parse.urljoin(final_url, html.unescape(h1 or h2))
        title = clean_text(inner, 200)
        if not title or len(title) < 8 or url in seen:
            continue
        uhost = (urllib.parse.urlparse(url).hostname or "").removeprefix("www.")
        if uhost != host or not is_safe_url(url) or urllib.parse.urlparse(url).path in ("", "/"):
            continue
        seen.add(url)
        total += 1
        cat = is_relevant(title, "", src.get("topic"), require_disney=not src.get("disney_site"))
        if not cat:
            continue
        item = {"id": item_id(url), "title": title, "url": url, "source": src["name"], "via": src["id"],
                "lang": src.get("lang", "ja"), "category": cat, "official": bool(src.get("official")),
                "date": now.isoformat(timespec="minutes"), "origin": "auto"}
        m = re.search(r"/(20\d\d)[/-](\d{1,2})(?:[/-](\d{1,2}))?/", url)
        if m:
            item["date"] = dt.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3) or 1), 12, tzinfo=JST).isoformat(timespec="minutes")
        else:
            item["date_unknown"] = True   # 記事のページを開いたとき（画像を調べるとき）に公開日を読む
        out.append(item)
    return out, total


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
        if url and not is_safe_url(url) and not GNEWS_ARTICLE.match(url):
            url = None  # 安全の確認に通らないリンクは載せない
        if not title or not url:
            continue
        # ディズニー専門のサイト（disney_site）は「ディズニー」の語を、クラリスでのサイト内検索（clarice_search）は
        # 見出しの「クラリス」を求めない（見出しに出てこない記事の取りこぼしを防ぐ）
        summary = clean_text(e["summary"], 600)
        # クラリスでのサイト内検索：見出しにクラリスが無くても、本文で「主な話題のひとつ」として扱われている記事は載せる
        # （小見出し・画像の説明に出てくる）。本文が配信に無いときは緩めない
        relaxed = bool(src.get("clarice_search")) and clarice_is_featured(e.get("content", ""))
        cat = is_relevant(title, summary, src.get("topic"),
                          require_disney=not src.get("disney_site"), require_clarice=not relaxed)
        if not cat:
            continue
        date = parse_date(e["date"]) or now
        if date > now + dt.timedelta(days=1):
            date = now
        out.append({
            "id": item_id(url),
            "title": title,
            "url": url,
            # 検索（ブログ・個人サイトなど幅広い）の取得元は、掲載元としてサイトの名前（ドメイン）を出す
            "source": source if (src.get("aggregator") and source) else (source_from_host(url) if src.get("kind") == "search" else src["name"]),
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
            if len(url) <= 1000 and is_safe_url(url):
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
        if not is_safe_url(article):
            item["image"] = ""
            return "元の記事が安全の確認に通りませんでした（載せません）"
        item["article"] = article
        time.sleep(0.5)
    host = (urllib.parse.urlparse(article).hostname or "").removeprefix("www.")
    if any(host == h or host.endswith("." + h) for h in NO_IMAGE_HOSTS):
        item["image"] = ""
        return "SNS のため画像は探しません"
    final, page = get(article)
    if item.pop("date_unknown", None):
        m = re.search(r'(?:article:published_time|datePublished)["\']?\s*(?:content=|:)\s*["\']([0-9]{4}-[0-9]{2}-[0-9]{2}[^"\']*)', page)
        d = parse_date(m.group(1)) if m else None
        if d:
            item["date"] = d.isoformat(timespec="minutes")
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
        if NOISE_TITLE.search(it.get("title", "")):
            continue
        link = it.get("article") or it["url"]
        if it.get("origin") == "auto" and not (is_safe_url(link) or GNEWS_ARTICLE.match(link)):
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


# ---------------------------------------------------------------- 同じ商品の記事をまとめる（グッズのみ）
# 別の媒体が同じ商品を取り上げた記事（プレスリリースの転載など）は、いちばん新しい記事だけを表示する。
# 判定：媒体が違う・日付が30日以内・見出しの特徴的な言葉が重なる（ありふれた言葉は除く）
DEDUPE_DAYS = 30
DEDUPE_STOP = set("""クラリス チップ デール チップとデール ディズニー disney 新発売 発売 登場 新登場 グッズ 新作 公式 限定 発売中
先行販売 予約 開始 情報 ニュース 東京ディズニーリゾート 東京ディズニーランド 東京ディズニーシー ミッキー ミニー フレンズ
キャラクター デザイン かわいい 可愛い 人気 シリーズ コレクション アイテム 種類 東京 土産 お土産 新作スイーツ 新作グッズ
展開 開催 ショップ ストア clarice chip dale and the new collection disney's are now of in for it is to with full list
coming available arrives today japan store""".split())
DEDUPE_TOKEN = re.compile(r"[一-龥々ァ-ヴーa-z0-9]+")


def title_tokens(title: str) -> set[str]:
    t = unicodedata.normalize("NFKC", title).lower()
    t = re.sub(r"[＆&・/／\-—–~～!！?？「」『』“”\"'’【】\[\]（）()<>＜＞、。,.:：♪☆★…|｜×]", " ", t)
    return {w for w in DEDUPE_TOKEN.findall(t) if len(w) >= 2 and w not in DEDUPE_STOP}


def same_product(a: dict, b: dict) -> bool:
    if a.get("source") == b.get("source"):
        return False   # 同じ媒体の別記事は、別の商品として残す
    try:
        if abs((dt.datetime.fromisoformat(a["date"]) - dt.datetime.fromisoformat(b["date"])).days) > DEDUPE_DAYS:
            return False
    except ValueError:
        return False
    ta, tb = title_tokens(a.get("title", "")), title_tokens(b.get("title", ""))
    if not ta or not tb:
        return False
    shared = ta & tb
    if len(shared) >= 2 and len(shared) / min(len(ta), len(tb)) >= 0.5:
        return True
    ga = {x[k:k + 3] for x in ["".join(sorted(ta))] for k in range(len(x) - 2)}
    gb = {x[k:k + 3] for x in ["".join(sorted(tb))] for k in range(len(x) - 2)}
    return bool(ga and gb) and 2 * len(ga & gb) / (len(ga) + len(gb)) >= 0.5


def dedupe_goods(items: list[dict]) -> list[dict]:
    """新しい順の items から、同じ商品の記事をまとめ、いちばん新しい記事に「ほか n 件」を付けて残す。"""
    goods = [i for i in items if i.get("category") in GOODS_CATEGORIES and i.get("title") and i.get("origin") != "manual"]
    parent = {id(i): id(i) for i in goods}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    sources = {id(i): {i.get("source")} for i in goods}   # まとまりごとの媒体（同じ媒体が2つ入らないようにする）
    for n, a in enumerate(goods):
        for b in goods[n + 1:]:
            ra, rb = find(id(a)), find(id(b))
            if ra != rb and not (sources[ra] & sources[rb]) and same_product(a, b):
                parent[rb] = ra
                sources[ra] |= sources.pop(rb)
    groups: dict[int, list[dict]] = {}
    for i in goods:
        groups.setdefault(find(id(i)), []).append(i)
    drop = set()
    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda x: x["date"], reverse=True)
        members[0]["others"] = len(members) - 1
        # 一覧から読む記事を選べるように、まとめた記事の見出し・リンク・掲載元・日付を添える
        members[0]["dupes"] = [{k: m[k] for k in ("title", "url", "source", "date")} for m in members[1:]]
        drop.update(id(m) for m in members[1:])
    return [i for i in items if id(i) not in drop]


def timeline_json(now: dt.datetime) -> str:
    collected = load_json(DATA_DIR / "collected.json", [])
    manual = load_json(DATA_DIR / "manual.json", [])
    exclude = load_json(DATA_DIR / "exclude.json", {})
    links = load_json(DATA_DIR / "links.json", {}).get("links", [])
    items = dedupe_goods(build_timeline(collected, manual, exclude, now))
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
            if src.get("type") == "page":
                final, page = http_get(src["url"])
                items, total = page_items(src, final, page, now)
            else:
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
# 2時間ごとの自動収集のたびに少しずつ（1回4分まで）進め、どこまで調べたかを残して続きから調べる。
BACKFILL_SINCE = 2004         # 東京ディズニーランドにクラリスが登場した 2005 年の前年から
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


BACKFILL_STATE = DATA_DIR / "backfill_state.json"
BACKFILL_MAX_PAGES = 40


def backfill(dry_run: bool, now: dt.datetime, windows: int | None = None, fetcher=fetch, pause: float = 1.0,
             budget: float = 240.0, reset: bool = False, clock=time.monotonic) -> int:
    """過去分を少しずつ取り込む。1回の実行は budget 秒まで。どこまで調べたかを backfill_state.json に残し、
    次の実行（2時間ごとの自動収集）で続きから調べる。取得元が増えたときも、その取得元の過去分を自動で調べる。
    windows を指定したとき（PR の試し取得）は、直近の期間だけを状態に関係なく調べる。"""
    all_sources = load_json(DATA_DIR / "sources.json", {}).get("sources", [])
    gnews = [s for s in all_sources if s.get("backfill") and "news.google.com/rss/search" in s.get("url", "")]
    site_search = [s for s in all_sources if s.get("clarice_search") and "feed=rss2" in s.get("url", "")]
    spans = backfill_windows(now)
    trial = bool(windows)
    if trial:
        spans = spans[-windows:]
    state = {} if (reset or trial) else load_json(BACKFILL_STATE, {})
    state.setdefault("windows", {})   # Google ニュース：取得元ごとに、調べ終えた期間の数（古い順）
    state.setdefault("pages", {})     # サイト内検索：取得元ごとに、読み終えたページ数（"done" なら最後まで）
    start = clock()
    found: list[dict] = []
    per_source: dict[str, int] = {}
    fails = 0
    out_of_time = False

    def time_left() -> bool:
        return trial or clock() - start < budget

    # 件数の多いサイト内検索（ページをさかのぼる）を先に、Google ニュースの期間ごとの検索を後に
    for src in site_search:
        done = state["pages"].get(src["id"], 0)
        if done == "done" and not trial:
            continue
        page = 1 if trial else int(done) + 1
        last = 3 if trial else BACKFILL_MAX_PAGES
        while page <= last and time_left():
            try:
                items, total = items_from_source(src, fetcher(paged_url(src["url"], page)), now)
            except Exception:
                total, items = 0, []   # ページの終わり（404 など）
            if not total:
                page = None
                break
            found += items
            per_source[src["id"]] = per_source.get(src["id"], 0) + len(items)
            page += 1
            time.sleep(pause)
        if not trial:
            state["pages"][src["id"]] = "done" if page is None or page > last else page - 1
        out_of_time |= page is not None and page <= last
    for src in gnews:
        i = 0 if trial else int(state["windows"].get(src["id"], 0))
        while i < len(spans) and time_left():
            after, before = spans[i]
            try:
                items, _ = items_from_source(src, fetcher(windowed_url(src["url"], after, before)), now)
                found += items
                per_source[src["id"]] = per_source.get(src["id"], 0) + len(items)
            except Exception as e:
                fails += 1
                print(f"{src['id']} {after}〜{before}: 取得できませんでした（{type(e).__name__}）")
            i += 1
            time.sleep(pause)
        if not trial:
            state["windows"][src["id"]] = i
        out_of_time |= i < len(spans)
    complete = not out_of_time
    summary = "、".join(f"{k} {v}" for k, v in per_source.items())
    print(f"::notice title=過去分::候補 {len(found)} 件（失敗 {fails} 回）{'・すべて調べ終えました' if complete else '・続きは次回'}: {summary}")
    for it in sorted(found, key=lambda x: x["date"])[:5]:
        print(f"::notice title=過去分の例::{it['date'][:10]} {it['title'][:50]}")
    if dry_run:
        return 0
    if not trial:
        write_if_changed(BACKFILL_STATE, dump(state))
    collected = merge_collected(load_json(DATA_DIR / "collected.json", []), found)
    collected.sort(key=lambda x: x["date"], reverse=True)
    collected = collected[: MAX_ITEMS * 2]
    changed = write_if_changed(DATA_DIR / "collected.json", dump(collected))
    changed |= write_if_changed(OUT_FILE, timeline_json(now))
    print("更新しました" if changed else "変更なし")
    return 0


def paged_url(url: str, page: int) -> str:
    return url if page == 1 else f"{url}{'&' if '?' in url else '?'}paged={page}"


# ---------------------------------------------------------------- 入力フォーム（手動で追加）
FORM_FIELDS = {
    "サイト名": "name",
    "サイトの URL": "site",
    "検索語（任意）": "search",
    "情報の言語": "srclang",
    "追加の確認": "srcapproval",
    "リンク（URL）": "url",
    "ひとこと（タイトル）": "title",
    "種類": "category",
    "日付（任意）": "date",
    "言語": "lang",
    "掲載をやめる": "hide",
    "入稿の確認": "approval",
}
CATEGORY_LABELS = {"ピンバッジ": "pin", "ぬいぐるみ": "plush", "プライズ": "prize", "グッズ": "other", "その他（グッズ）": "other", "その他": "other",
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


# ---------------------------------------------------------------- 取得元の手動追加（入力フォーム）
# 管理者がフォームでサイトを指定 → 配信（RSS / Atom）を探す → 安全の確認と試し取得 → 取得元に追加（送信＝承認）
SRC_LANGS = {"日本語": "ja", "English": "en", "中文": "zh", "Français": "fr"}
FEED_LINK = re.compile(r"<link\b[^>]*>", re.I)


def find_feed(site: str, search: str, fetcher=fetch, getter=http_get) -> tuple[str, bytes]:
    """サイトの URL から配信を探す。戻り値: (配信の URL, 中身)。見つからなければ ValueError。"""
    candidates = []
    try:
        data = fetcher(site)
        parse_feed(data)
        return site, data            # URL がそのまま配信だった
    except Exception:
        pass
    final, page = getter(site)
    wordpress = "wp-content" in page or "wordpress" in page.lower()
    if search and wordpress:
        root = f"{urllib.parse.urlparse(final).scheme}://{urllib.parse.urlparse(final).netloc}"
        candidates.append(f"{root}/?s={urllib.parse.quote(search)}&feed=rss2")
    for tag in FEED_LINK.findall(page[:300_000]):
        attrs = {k.lower(): (v1 or v2) for k, v1, v2 in META_ATTR.findall(tag)}
        if "alternate" in attrs.get("rel", "").lower() and re.search(r"(rss|atom)\+xml", attrs.get("type", "")) and attrs.get("href"):
            candidates.append(urllib.parse.urljoin(final, html.unescape(attrs["href"])))
    root = f"{urllib.parse.urlparse(final).scheme}://{urllib.parse.urlparse(final).netloc}"
    candidates += [f"{root}/feed/", f"{root}/rss", f"{root}/index.xml"]
    for url in dict.fromkeys(candidates):
        if not is_safe_url(url):
            continue
        try:
            data = fetcher(url)
            if parse_feed(data):
                return url, data
        except Exception:
            continue
    raise ValueError("RSS / Atom の配信が見つかりませんでした")


def add_source(event: dict, now: dt.datetime, fetcher=fetch, getter=http_get) -> dict:
    issue = event.get("issue") or {}
    if issue.get("author_association") not in ALLOWED_ASSOCIATIONS:
        return {"skipped": "追加できるのはリポジトリの管理者だけです。"}
    form = parse_form(issue.get("body") or "")
    if "site" not in form:
        return {"skipped": "取得元の入力フォームではありません。"}
    errors = []
    site = (form.get("site") or "").split()[0] if form.get("site") else ""
    name = clean_text(form.get("name", ""), 60)
    search = clean_text(form.get("search", ""), 60)
    lang = SRC_LANGS.get(form.get("srclang", "").strip(), "ja")
    if not name:
        errors.append("サイト名を入れてください。")
    if not is_safe_url(site):
        errors.append("サイトの URL は https:// から始まる、安全の確認に通る URL にしてください"
                      "（短縮 URL・IP アドレス・ファイル配布のリンクなどは使えません）。")
    if not checked(form.get("srcapproval", "")):
        errors.append("「追加の確認」にチェックが入っていません。")
    if errors:
        return {"status": "error", "errors": errors}
    host = (urllib.parse.urlparse(site).hostname or "").removeprefix("www.")
    kind, via_bing = "blog", False
    try:
        feed_url, data = find_feed(site, search, fetcher, getter)
    except Exception:
        # 配信（RSS）の無いサイトは、Bing のサイト内検索（site:）で「クラリス」を含むページを探す
        mkt = {"ja": "ja-JP", "en": "en-US", "fr": "fr-FR", "zh": "zh-CN"}[lang]
        feed_url = ("https://www.bing.com/search?q=" + urllib.parse.quote_plus(f"site:{host} {search or ('クラリス' if lang == 'ja' else 'Clarice')}")
                    + f"&format=rss&mkt={mkt}")
        kind, via_bing = "search", True
        try:
            data = fetcher(feed_url)
            parse_feed(data)
        except Exception as e:
            return {"status": "error", "errors": [f"このサイトの配信（RSS / Atom）が見つからず、サイト内検索もできませんでした（{str(e)[:100]}）。"
                                                  "RSS の URL が分かれば、それを「サイトの URL」に入れてください。"]}
    src = {"id": "user-" + re.sub(r"[^a-z0-9]+", "-", host.lower()).strip("-"),
           "name": name, "lang": lang, "url": feed_url, "kind": kind, "disney_site": True, "added_by_issue": int(issue["number"])}
    if via_bing:
        src["site"] = host
    elif search and "feed=rss2" in feed_url and "?s=" in feed_url:
        src["clarice_search"] = True
    items, total = items_from_source(src, data, now)
    data_all = load_json(DATA_DIR / "sources.json", {})
    sources = data_all.get("sources", [])
    others = [s for s in sources if s.get("added_by_issue") != src["added_by_issue"]]
    if any(s.get("url") == feed_url for s in others):
        return {"status": "exists", "feed": feed_url, "total": total, "matched": len(items), "errors": []}
    while any(s["id"] == src["id"] for s in others):
        src["id"] += "-2"
    data_all["sources"] = others + [src]
    write_if_changed(DATA_DIR / "sources.json", dump(data_all))
    return {"status": "added", "feed": feed_url, "via_bing": via_bing, "name": name, "total": total, "matched": len(items),
            "examples": [i["title"][:60] for i in items[:3]], "errors": []}


def source_comment(result: dict) -> str:
    if result.get("errors"):
        return "⚠️ **取得元に追加できませんでした。** 次の点を直して、このページを「Edit」で保存し直してください。\n\n" + \
            "\n".join(f"- {e}" for e in result["errors"])
    if result.get("status") == "exists":
        return f"ℹ️ この配信（{result['feed']}）はすでに取得元に入っています。"
    lines = [f"✅ **取得元に追加しました。** 次の自動収集（2時間ごと）から、このサイトの新しい情報も集めます。",
             "", f"- 配信: {result['feed']}" + ("（RSS が無いため、Bing のサイト内検索で探します）" if result.get("via_bing") else ""),
             f"- 試し取得: 配信 {result['total']} 件のうち、条件（クラリス・ディズニー・グッズ／パーク）に合う情報 {result['matched']} 件"]
    lines += [f"  - {t}" for t in result.get("examples", [])]
    if not result["matched"]:
        lines += ["", "今は条件に合う情報がありませんが、新しい記事が出たときに拾います。"]
    lines += ["", "取得元から外すときは、開発エージェントに伝えてください。"]
    return "\n".join(lines)


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
    bf.add_argument("--budget", type=float, default=240.0, help="1回に使う時間（秒）。続きは次回")
    bf.add_argument("--reset", action="store_true", help="どこまで調べたかを消して、最初から調べ直す")
    im = sub.add_parser("images")
    im.add_argument("--dry-run", action="store_true")
    im.add_argument("--limit", type=int, default=8)
    b = sub.add_parser("build")
    b.add_argument("--check", action="store_true")
    a = sub.add_parser("add")
    a.add_argument("event")
    so = sub.add_parser("source")
    so.add_argument("event")
    sc = sub.add_parser("source-comment")
    sc.add_argument("result")
    m = sub.add_parser("comment")
    m.add_argument("result")
    args = parser.parse_args()
    now = dt.datetime.now(JST)
    if args.cmd == "collect":
        return collect(args.dry_run, now)
    if args.cmd == "backfill":
        return backfill(args.dry_run, now, args.windows, budget=args.budget, reset=args.reset)
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
    if args.cmd == "source":
        print(json.dumps(add_source(json.loads(Path(args.event).read_text(encoding="utf-8")), now), ensure_ascii=False))
        return 0
    if args.cmd == "source-comment":
        print(source_comment(json.loads(Path(args.result).read_text(encoding="utf-8"))))
        return 0
    if args.cmd == "comment":
        print(comment_for(json.loads(Path(args.result).read_text(encoding="utf-8"))))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
