#!/usr/bin/env python3
"""ブログの記事ページを原稿から組み立てるスクリプト（記事ビルド）。

  content/blog/<URL名>/index.md   →  blog/<URL名>/index.html   … 記事ページ（固定のフィルム風テンプレート）
  content/blog/<URL名>/index.en.md →  en/blog/<URL名>/index.html … 翻訳版の記事ページ（fr・zh も同じ）
                                   →  blog/posts.json            … 一覧（フィルムのコマ）のデータ
                                   →  blog/feed.xml、en/blog/feed.xml … … RSS（言語ごと）
                                   →  en/blog/index.html …       … 言語ごとの一覧ページ
                                   →  sitemap.xml                … 公開記事の URL を反映

- 見た目は全記事共通。原稿に書けるのは文字・写真・URL だけで、HTML は文字として表示されます（安全対策）。
- status が published で、日時（date）が今より前の記事だけを公開します。
  scheduled（予約）は日時が来たら公開、draft（下書き）は公開しません。
- 記事ページのメニュー・言語切替などは blog/index.html から流用するので、一覧と常に同じになります。
- URL だけの行はリンクのカードになります（リンク先のタイトルを取得して原稿フォルダの cards.json に保存）。
- ジャンルは content/blog/genres.json で管理します。入稿フォームの選択肢もここから自動で書き換えます。
- 翻訳（tools/translate_blog.py が作る index.en.md など）があれば、言語ごとの URL に記事ページを作ります。
    日本語 /blog/<URL名>/、英語 /en/blog/<URL名>/、フランス語 /fr/blog/<URL名>/、中国語 /zh/blog/<URL名>/
  一覧・RSS も言語ごとに作り、検索エンジンには各言語版の関係（hreflang）とサイトマップで知らせます。
  原稿を直した後の古い翻訳は使わず、新しい翻訳ができるまでその言語のページは作りません。

使い方:
  python3 tools/build_blog.py            # 組み立て（公開中の記事に変化があればファイルを書き換える）
  python3 tools/build_blog.py --check    # 組み立て結果が最新か確認だけする（GitHub の自動チェック用）
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTENT_DIR = ROOT / "content" / "blog"
BLOG_DIR = ROOT / "blog"
SITE = "https://divaclarice321.com"
JST = dt.timezone(dt.timedelta(hours=9))
GENRES_FILE = CONTENT_DIR / "genres.json"
FORM_FILE = ROOT / ".github" / "ISSUE_TEMPLATE" / "blog-post.yml"
LANGS = ("en", "fr", "zh")  # 翻訳する言語（日本語が原文）

esc = lambda s: html.escape(str(s), quote=True)  # noqa: E731


# ======================================================================
# 原稿の読み込み
# ======================================================================
def read_post(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        raise ValueError(f"{path}: 先頭の項目欄（--- で囲まれた部分）がありません")
    meta: dict = {}
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, _, value = line.partition(":")
        value = value.split(" #")[0].strip() if not value.strip().startswith(('"', "[")) else value.strip()
        try:
            meta[key.strip()] = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            meta[key.strip()] = value
    meta["body"] = m.group(2)
    meta["slug"] = path.parent.name
    meta["dir"] = path.parent
    meta["date_obj"] = dt.datetime.fromisoformat(str(meta["date"]))
    if meta["date_obj"].tzinfo is None:
        meta["date_obj"] = meta["date_obj"].replace(tzinfo=JST)
    meta.setdefault("status", "draft")
    meta.setdefault("tags", [])
    meta.setdefault("genres", [])
    return meta


def source_hash(post: dict) -> str:
    """翻訳の対象（タイトル・説明・タグ・本文）の指紋。原稿を直すと変わり、古い翻訳を使わなくなる。"""
    data = json.dumps([post.get("title", ""), post.get("summary", ""), post.get("tags") or [], post["body"].strip()],
                      ensure_ascii=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:16]


def read_translation(post: dict, lang: str) -> dict | None:
    """原稿と指紋が一致する翻訳だけを返す（無い・古い場合は None）。"""
    path = post["dir"] / f"index.{lang}.md"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        return None
    meta: dict = {}
    for line in m.group(1).splitlines():
        if line.lstrip().startswith("#"):
            continue
        key, _, value = line.partition(":")
        try:
            meta[key.strip()] = json.loads(value.strip())
        except (json.JSONDecodeError, ValueError):
            meta[key.strip()] = value.strip()
    if meta.get("source_hash") != source_hash(post):
        return None
    tags = meta.get("tags") if isinstance(meta.get("tags"), list) else []
    if len(tags) != len(post.get("tags") or []):
        tags = list(post.get("tags") or [])
    return {**post, "title": str(meta.get("title") or post["title"]), "summary": str(meta.get("summary") or ""),
            "tags": [str(t) for t in tags], "body": m.group(2), "lang": lang}


# ======================================================================
# ジャンル
# ======================================================================
def load_genres() -> list[dict]:
    if not GENRES_FILE.exists():
        return []
    genres = json.loads(GENRES_FILE.read_text(encoding="utf-8")).get("genres", [])
    ids = [g["id"] for g in genres]
    for g in genres:
        if not re.match(r"^[a-z0-9-]{1,30}$", g["id"]):
            raise ValueError(f"genres.json: id「{g['id']}」は半角の英小文字・数字・ハイフンにしてください")
        if not g.get("label", {}).get("ja") or not g.get("name", {}).get("ja"):
            raise ValueError(f"genres.json: 「{g['id']}」の label.ja と name.ja は必須です")
    if len(ids) != len(set(ids)):
        raise ValueError("genres.json: id が重複しています")
    return genres


def genre_option(g: dict) -> str:
    """入稿フォームの選択肢の文字（例: TDL（東京ディズニーランド））。"""
    label, name = g["label"]["ja"], g["name"]["ja"]
    return label if label == name else f"{label}（{name}）"


def g_text(g: dict, field: str, lang: str) -> str:
    return g[field].get(lang) or g[field]["ja"]


def sync_form(form_text: str, genres: list[dict]) -> str:
    """入稿フォームの「ジャンル」の選択肢を genres.json に合わせる。"""
    pat = re.compile(r"(?P<indent>[ \t]*)# genres:start(?P<note>[^\n]*)\n.*?(?P=indent)# genres:end", re.S)
    m = pat.search(form_text)
    if not m:
        raise ValueError("入稿フォームに「# genres:start」の目印がありません")
    ind = m.group("indent")
    lines = [f"{ind}# genres:start{m.group('note')}"] + [f"{ind}- {json.dumps(genre_option(g), ensure_ascii=False)}" for g in genres] \
        + [f"{ind}# genres:end"]
    return form_text[:m.start()] + "\n".join(lines) + form_text[m.end():]


def is_public(post: dict, now: dt.datetime) -> bool:
    return post["status"] in ("published", "scheduled") and post["date_obj"] <= now


def opt_image(name: str, width: int) -> str:
    """元写真のファイル名 → 軽量版（tools/optimize_images.py が作る）の URL。"""
    stem = Path(name).stem.lstrip("_") or Path(name).stem
    return f"/images/opt/{stem}-{width}.webp"


# ======================================================================
# 本文（Markdown の一部）→ 安全な HTML
# ======================================================================
URL_LINE = re.compile(r"^https?://\S+$")
IMG_LINE = re.compile(r"^!\[([^\]]*)\]\(([^)\s]+)\)$")
BULLET = re.compile(r"^\s*[-*・]\s+")
NUMBERED = re.compile(r"^\s*\d+[.)．]\s+")
GENERIC_ALT = re.compile(r"^(image|img|photo|写真|画像|screenshot|スクリーンショット.*|IMG_?\d+.*|DSC.*|PXL_.*|\d+)$", re.I)


def inline(text: str) -> str:
    """段落の中の **太字**・[文字](URL)・URL を変換。それ以外の文字はすべてエスケープする。"""
    out, pos = [], 0
    pattern = re.compile(r"\*\*(.+?)\*\*|\[([^\]]+)\]\((https?://[^)\s]+)\)|(https?://[^\s<>()]+)")
    for m in pattern.finditer(text):
        out.append(esc(text[pos:m.start()]))
        if m.group(1) is not None:
            out.append(f"<strong>{esc(m.group(1))}</strong>")
        elif m.group(2) is not None:
            out.append(f'<a href="{esc(m.group(3))}" target="_blank" rel="noopener noreferrer">{esc(m.group(2))}</a>')
        else:
            url = m.group(4).rstrip(".,、。")
            out.append(f'<a href="{esc(url)}" target="_blank" rel="noopener noreferrer">{esc(url)}</a>')
            out.append(esc(m.group(4)[len(url):]))
        pos = m.end()
    out.append(esc(text[pos:]))
    return "".join(out)


def render_body(post: dict, cards: dict) -> tuple[str, list[tuple[str, str]], list[str]]:
    """本文を HTML にする。戻り値: (HTML, 目次 [(id, 見出し)], 本文の写真ファイル名)"""
    blocks = re.split(r"\n\s*\n", post["body"].replace("\r\n", "\n").strip())
    html_parts, toc, images = [], [], []
    for block in blocks:
        lines = [l.rstrip() for l in block.split("\n") if l.strip()]
        if not lines:
            continue
        first = lines[0].strip()
        if len(lines) == 1 and (m := IMG_LINE.match(first)):
            alt, src = m.group(1).strip(), m.group(2)
            if "/" in src or src.startswith(".") or not (post["dir"].parent.parent.parent / "images" / src).exists():
                continue  # 原稿フォルダ外・存在しない画像は出さない
            images.append(src)
            caption = "" if (not alt or GENERIC_ALT.match(alt)) else alt
            fig = (f'<figure class="article-figure"><img src="{esc(opt_image(src, 960))}" '
                   f'srcset="{esc(opt_image(src, 960))} 960w, {esc(opt_image(src, 1600))} 1600w" '
                   f'sizes="(max-width: 640px) 100vw, 640px" alt="{esc(caption)}" loading="lazy" decoding="async">')
            if caption:
                fig += f"<figcaption>{esc(caption)}</figcaption>"
            html_parts.append(fig + "</figure>")
        elif len(lines) == 1 and URL_LINE.match(first):
            info = cards.get(first, {})
            title = info.get("title") or first
            site = info.get("site") or urllib.parse.urlparse(first).hostname or ""
            html_parts.append(
                f'<a class="link-card" href="{esc(first)}" target="_blank" rel="noopener noreferrer">'
                f'<span class="link-card-title">{esc(title)}</span>'
                f'<span class="link-card-site">{esc(site)}</span></a>')
        elif first.startswith("#"):
            level = 3 if first.startswith("###") else 2
            text = first.lstrip("#").strip()
            if level == 2:
                anchor = f"s{len(toc) + 1}"
                toc.append((anchor, text))
                html_parts.append(f'<h2 id="{anchor}">{esc(text)}</h2>')
            else:
                html_parts.append(f"<h3>{esc(text)}</h3>")
            rest = lines[1:]
            if rest:
                html_parts.append("<p>" + "<br>".join(inline(l.strip()) for l in rest) + "</p>")
        elif all(l.lstrip().startswith(">") for l in lines):
            inner = "<br>".join(inline(l.lstrip()[1:].strip()) for l in lines)
            html_parts.append(f"<blockquote><p>{inner}</p></blockquote>")
        elif all(BULLET.match(l) for l in lines):
            items = "".join("<li>" + inline(BULLET.sub("", l)) + "</li>" for l in lines)
            html_parts.append(f"<ul>{items}</ul>")
        elif all(NUMBERED.match(l) for l in lines):
            items = "".join("<li>" + inline(NUMBERED.sub("", l)) + "</li>" for l in lines)
            html_parts.append(f"<ol>{items}</ol>")
        elif len(lines) == 1 and re.match(r"^(-{3,}|\*{3,}|_{3,})$", first):
            html_parts.append("<hr>")
        else:
            html_parts.append("<p>" + "<br>".join(inline(l.strip()) for l in lines) + "</p>")
    return "\n".join(html_parts), toc, images


# ======================================================================
# URL のカード（リンク先のタイトルを取得）
# ======================================================================
def fetch_card(url: str) -> dict:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; yu-s-dlife-blog/1.0)"})
        with urllib.request.urlopen(req, timeout=8) as r:
            if "html" not in (r.headers.get("Content-Type") or ""):
                return {}
            raw = r.read(600_000).decode(r.headers.get_content_charset() or "utf-8", "replace")
    except Exception:
        return {}

    def meta(prop: str) -> str:
        for pat in (rf'<meta[^>]+(?:property|name)=["\']{prop}["\'][^>]*content=["\']([^"\']*)["\']',
                    rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:property|name)=["\']{prop}["\']'):
            m = re.search(pat, raw, re.I)
            if m:
                return html.unescape(m.group(1)).strip()
        return ""

    title = meta("og:title")
    if not title and (m := re.search(r"<title[^>]*>(.*?)</title>", raw, re.I | re.S)):
        title = html.unescape(re.sub(r"\s+", " ", m.group(1))).strip()
    return {"title": title[:120], "site": meta("og:site_name")[:60]}


def load_cards(post: dict, allow_fetch: bool) -> dict:
    path = post["dir"] / "cards.json"
    cards = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    urls = [l.strip() for l in post["body"].splitlines() if URL_LINE.match(l.strip())]
    changed = False
    for url in urls:
        if url not in cards and allow_fetch:
            info = fetch_card(url)
            if info.get("title"):  # 取れなかったときは保存せず、次の組み立てでもう一度試す
                cards[url] = info
                changed = True
    if changed:
        path.write_text(json.dumps(cards, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return cards


# ======================================================================
# ページの組み立て
# ======================================================================
def date_stamp(d: dt.datetime) -> str:
    return f"'{d:%y %m %d}"


def summary_of(post: dict) -> str:
    if post.get("summary"):
        return post["summary"]
    for block in re.split(r"\n\s*\n", post["body"]):
        b = block.strip()
        if b and not b.startswith(("#", "!", ">", "http")):
            text = re.sub(r"\*\*|\[|\]\([^)]*\)", "", b).replace("\n", " ")
            return text[:100] + ("…" if len(text) > 100 else "")
    return post["title"]


def page_parts(index_html: str) -> tuple[str, str]:
    """blog/index.html を「main の前」と「main の後（フッター〜）」に分ける。"""
    a = index_html.index("<!-- blog:main -->")
    b = index_html.index("<!-- /blog:main -->") + len("<!-- /blog:main -->")
    return index_html[:a], index_html[b:]


def replace_region(text: str, name: str, new: str) -> str:
    pat = re.compile(rf"(?P<indent>[ \t]*)<!-- blog:{name} -->\n.*?(?P=indent)<!-- /blog:{name} -->", re.S)
    if not pat.search(text):
        raise ValueError(f"目印 <!-- blog:{name} --> が見つかりません")
    return pat.sub(lambda m: f"{m.group('indent')}<!-- blog:{name} -->\n{new}\n{m.group('indent')}<!-- /blog:{name} -->", text, count=1)


# ======================================================================
# 言語ごとの URL・表記
# ======================================================================
HREFLANG = {"ja": "ja", "en": "en", "fr": "fr", "zh": "zh-Hans"}
OG_LOCALE = {"ja": "ja_JP", "en": "en_US", "fr": "fr_FR", "zh": "zh_CN"}
LIST_TEXT = {  # 一覧ページの名前と説明（検索結果・SNS 共有に出る）
    "ja": ("Blog | Yu's DLife", "旅とカメラの記録。Yu's DLife のブログ。"),
    "en": ("Blog | Yu's DLife", "Notes on Disney parks around the world, travel and photography. The blog of Yu's DLife."),
    "fr": ("Blog | Yu's DLife", "Carnet sur les parcs Disney du monde entier, les voyages et la photographie. Le blog de Yu's DLife."),
    "zh": ("博客 | Yu's DLife", "世界各地迪士尼乐园、旅行与摄影的记录。Yu's DLife 的博客。"),
}
FEED_DESC = {"ja": "旅とカメラの記録", "en": "Notes on travel and photography",
             "fr": "Carnet de voyages et de photographie", "zh": "旅行与摄影的记录"}


def lang_root(lang: str) -> Path:
    return BLOG_DIR if lang == "ja" else ROOT / lang / "blog"


def list_url(lang: str) -> str:
    return "/blog/" if lang == "ja" else f"/{lang}/blog/"


def post_url(slug: str, lang: str) -> str:
    return f"{list_url(lang)}{slug}/"


def alternate_links(paths: dict[str, str]) -> list[str]:
    """同じ内容の各言語版を検索エンジンに知らせる（hreflang）。日本語版を既定（x-default）にする。"""
    lines = [f'    <link rel="alternate" hreflang="{HREFLANG[lang]}" href="{SITE}{path}">' for lang, path in paths.items()]
    if "ja" in paths and len(paths) > 1:
        lines.append(f'    <link rel="alternate" hreflang="x-default" href="{SITE}{paths["ja"]}">')
    return lines if len(paths) > 1 else []


def localize_html(page: str, lang: str) -> str:
    """日本語のページを、言語ボタンの訳（data-en など）を使って最初からその言語で書かれたページにする。
    検索エンジンは JavaScript で切り替わる前の文字を読むため、言語ごとの URL では文字そのものを書き換えておく。"""
    if lang == "ja":
        return page
    page = re.sub(r'<html lang="ja"', f'<html lang="{HREFLANG[lang]}"', page, count=1)
    # 子要素を持たない要素の文字を data-<言語> の訳に置き換える
    el = re.compile(rf'(<(?P<tag>[a-zA-Z0-9]+)\b[^<>]*?\bdata-{lang}="(?P<val>[^"]*)"[^<>]*>)[^<]*(</(?P=tag)>)')
    page = el.sub(lambda m: m.group(1) + m.group("val") + m.group(4), page)
    # メニューのリンク先（data-url-<言語>）
    page = re.sub(rf'(<a\b[^<>]*?)\bhref="[^"]*"([^<>]*?\bdata-url-{lang}="(?P<u>[^"]*)")',
                  lambda m: f'{m.group(1)}href="{m.group("u")}"{m.group(2)}', page)
    page = re.sub(rf'(<a\b[^<>]*?\bdata-url-{lang}="(?P<u>[^"]*)"[^<>]*?)\bhref="[^"]*"',
                  lambda m: f'{m.group(1)}href="{m.group("u")}"', page)
    # 言語ボタンの選択状態
    page = page.replace('class="lang-btn active" data-lang="ja"', 'class="lang-btn" data-lang="ja"')
    page = page.replace(f'class="lang-btn" data-lang="{lang}"', f'class="lang-btn active" data-lang="{lang}"')
    return page


# ======================================================================
# ページの組み立て
# ======================================================================
def toc_block(toc: list[tuple[str, str]]) -> str:
    if len(toc) < 2:
        return ""
    items = "".join(f'<li><a href="#{a}">{esc(t)}</a></li>' for a, t in toc)
    return (f'<nav class="article-toc" aria-label="目次"><p class="article-toc-title" data-ja="目次" '
            f'data-en="Contents" data-fr="Sommaire" data-zh="目录">目次</p><ol>{items}</ol></nav>')


MT_NOTE = ('<p class="article-note article-mt" data-ja="" '
           'data-en="This article was translated from Japanese by AI (machine translation). The Japanese version is the original." '
           'data-fr="Cet article a été traduit du japonais par une IA (traduction automatique). La version japonaise fait foi." '
           'data-zh="本文由AI从日语自动翻译而来。以日语原文为准。"></p>')
JA_ONLY_NOTE = ('<p class="article-note article-ja-only" hidden data-ja="" '
                'data-en="This article is currently available in Japanese only." '
                'data-fr="Cet article n\'est pour l\'instant disponible qu\'en japonais." '
                'data-zh="本文目前仅提供日语版本。"></p>')
AI_NOTE = ('<p class="article-note" data-ja="この記事は AI の支援を受けて作成し、運営者が内容を確認しています。" '
           'data-en="This article was written with AI assistance and reviewed by the site owner." '
           'data-fr="Cet article a été rédigé avec l\'aide d\'une IA et vérifié par l\'auteur du site." '
           'data-zh="本文在AI辅助下撰写，并由运营者确认内容。">この記事は AI の支援を受けて作成し、運営者が内容を確認しています。</p>')


def build_post_page(post: dict, lang: str, number: int, index_html: str, cards: dict,
                    versions: dict[str, dict], genres: list[dict] | None = None) -> str:
    """1つの言語版の記事ページ。post はその言語の内容（翻訳なら翻訳文）、versions は存在する全言語版。"""
    genre_map = {g["id"]: g for g in genres or []}
    ja = versions["ja"]
    body_html, toc, images = render_body(post, cards)
    cover = ja.get("cover") or (images[0] if images else "")
    path = post_url(post["slug"], lang)
    desc = summary_of(post)
    d = post["date_obj"]
    paths = {lg: post_url(post["slug"], lg) for lg in versions}
    head = "\n".join([
        f"    <title>{esc(post['title'])} | Yu's DLife</title>",
        f'    <meta name="description" content="{esc(desc)}">',
        f'    <link rel="canonical" href="{SITE}{esc(path)}">',
        *alternate_links(paths),
        '    <meta property="og:type" content="article">',
        "    <meta property=\"og:site_name\" content=\"Yu's DLife\">",
        f'    <meta property="og:title" content="{esc(post["title"])}">',
        f'    <meta property="og:description" content="{esc(desc)}">',
        f'    <meta property="og:url" content="{SITE}{esc(path)}">',
        f'    <meta property="og:image" content="{esc(SITE + (opt_image(cover, 1600) if cover else "/assets/ogp.jpg"))}">',
        f'    <meta property="og:locale" content="{OG_LOCALE[lang]}">',
        *[f'    <meta property="og:locale:alternate" content="{OG_LOCALE[lg]}">' for lg in versions if lg != lang],
        f'    <meta property="article:published_time" content="{d.isoformat()}">',
        '    <meta name="twitter:card" content="summary_large_image">',
    ])
    frame_img = (f'<img src="{esc(opt_image(cover, 1600))}" alt="" decoding="async">' if cover else "")
    # ジャンルとタグ（押すと、その言語の一覧がその記事だけに絞り込まれる）
    chips = []
    for gid in ja.get("genres") or []:
        g = genre_map.get(gid)
        if g:
            chips.append(f'<li><a class="article-genre" href="{list_url(lang)}?genre={esc(gid)}" '
                         f'title="{esc(g_text(g, "name", lang))}">{esc(g_text(g, "label", lang))}</a></li>')
    for key, label in zip(ja.get("tags") or [], post.get("tags") or []):
        chips.append(f'<li><a href="{list_url(lang)}?tag={esc(urllib.parse.quote(key))}">#{esc(label)}</a></li>')
    tags_html = f'<ul class="article-tags">{"".join(chips)}</ul>' if chips else ""
    note = MT_NOTE if lang != "ja" else JA_ONLY_NOTE
    main = f"""    <!-- 記事ページ（tools/build_blog.py が content/blog/{esc(post['slug'])}/ の原稿から自動で作成。直接編集しない） -->
    <main>
        <div class="film is-single">
            <ol class="film-frames">
                <li>
                    <span class="edge-print frame-number" aria-hidden="true"><span>{number}</span></span>
                    <div class="frame{'' if cover else ' is-unexposed'}">
                        {frame_img}
                        <div class="frame-caption">
                            <p class="frame-title">{esc(post['title'])}</p>
                            <time class="date-stamp" datetime="{d.isoformat()}">{date_stamp(d)}</time>
                        </div>
                    </div>
                </li>
            </ol>
        </div>

        <article class="article">
            <h1 class="article-title">{esc(post['title'])}</h1>
            <time class="article-date" datetime="{d.isoformat()}">{d:%Y.%m.%d}</time>
            {note}
            {toc_block(toc)}
            <div class="article-body">
{body_html}
            </div>
            {tags_html}
            {AI_NOTE if ja.get("ai_assisted") is True else ""}
            <a href="{list_url(lang)}" class="article-back" data-ja="← ブログの一覧に戻る" data-en="← Back to the blog" data-fr="← Retour au blog" data-zh="← 返回博客列表">← ブログの一覧に戻る</a>
        </article>
    </main>"""
    before, after = page_parts(index_html)
    before = replace_region(before, "head", head)
    return localize_html(before + main + after, lang)


def build_list_page(index_html: str, lang: str, has_posts: bool, list_langs: list[str]) -> str:
    """一覧ページ（/blog/、/en/blog/ など）。記事の並びは /assets/blog.js が posts.json から作る。"""
    title, desc = LIST_TEXT[lang]
    head = "\n".join([
        f"    <title>{html.escape(title, quote=False)}</title>",
        f'    <meta name="description" content="{esc(desc)}">',
        *([f'    <link rel="canonical" href="{SITE}{list_url(lang)}">'] if has_posts else []),
        *alternate_links({lg: list_url(lg) for lg in list_langs} if has_posts else {}),
    ])
    robots = ('    <!-- 公開中の記事がまだ無い間は検索結果に出さない（tools/build_blog.py が自動で切り替える） -->\n'
              '    <meta name="robots" content="noindex">') if not has_posts else \
        f'    <link rel="alternate" type="application/rss+xml" title="Yu\'s DLife Blog" href="{list_url(lang)}feed.xml">'
    page = replace_region(replace_region(index_html, "head", head), "robots", robots)
    if lang != "ja":
        page = page.replace("<!-- ブログ：", f"<!-- 自動で作成（tools/build_blog.py が /blog/index.html から {lang} 版を作る。直接編集しない）。ブログ：", 1)
    return localize_html(page, lang)


def build_feed(items_: list[tuple[dict, str]], lang: str) -> str:
    items = []
    for p, path in items_[:20]:
        url = f"{SITE}{path}"
        items.append(
            "  <item>\n"
            f"    <title>{esc(p['title'])}</title>\n"
            f"    <link>{url}</link>\n"
            f"    <guid isPermaLink=\"true\">{url}</guid>\n"
            f"    <pubDate>{p['date_obj'].strftime('%a, %d %b %Y %H:%M:%S %z')}</pubDate>\n"
            f"    <description>{esc(summary_of(p))}</description>\n"
            "  </item>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0">\n<channel>\n'
            "  <title>Yu's DLife Blog</title>\n"
            f"  <link>{SITE}{list_url(lang)}</link>\n"
            f"  <description>{FEED_DESC[lang]}</description>\n"
            f"  <language>{HREFLANG[lang]}</language>\n"
            + ("\n".join(items) + "\n" if items else "")
            + "</channel>\n</rss>\n")


def sitemap_entry(paths: dict[str, str], lastmod: dt.datetime) -> list[str]:
    """各言語版を1件ずつ載せ、互いの言語版を xhtml:link で示す。"""
    alts = "".join(f'\n    <xhtml:link rel="alternate" hreflang="{HREFLANG[lg]}" href="{SITE}{p}"/>' for lg, p in paths.items()) \
        if len(paths) > 1 else ""
    return [f"  <url>\n    <loc>{SITE}{p}</loc>\n    <lastmod>{lastmod:%Y-%m-%d}</lastmod>{alts}\n  </url>" for p in paths.values()]


def build(now: dt.datetime, allow_fetch: bool) -> dict[Path, str | None]:
    """書き出す内容を {ファイル: 中身（None は削除）} で返す。"""
    posts = []
    for md in sorted(CONTENT_DIR.glob("*/index.md")):
        posts.append(read_post(md))
    public = sorted([p for p in posts if is_public(p, now)], key=lambda p: p["date_obj"], reverse=True)

    genres = load_genres()
    known = {g["id"] for g in genres}
    for p in posts:
        unknown = [g for g in p.get("genres") or [] if g not in known]
        if unknown:
            raise ValueError(f"{p['slug']}: genres.json に無いジャンル {unknown} が指定されています")

    index_path = BLOG_DIR / "index.html"
    index_html = index_path.read_text(encoding="utf-8")
    out: dict[Path, str | None] = {}
    if FORM_FILE.exists():
        out[FORM_FILE] = sync_form(FORM_FILE.read_text(encoding="utf-8"), genres)
    # 記事ごとの言語版（日本語＋原稿と一致する翻訳）
    versions = {p["slug"]: {"ja": p, **{lang: t for lang in LANGS if (t := read_translation(p, lang))}} for p in public}
    per_lang = {lang: [p for p in public if lang in versions[p["slug"]]] for lang in ("ja",) + LANGS}
    list_langs = [lang for lang in ("ja",) + LANGS if per_lang[lang]]

    # 一覧ページ（言語ごと。記事が1本も無い言語は検索に出さない）
    for lang in ("ja",) + LANGS:
        out[lang_root(lang) / "index.html"] = build_list_page(index_html, lang, bool(per_lang[lang]), list_langs)
    ja_index = out[index_path]

    # 記事ページ（番号は古い記事から 1, 2, 3 …。フィルムのコマ番号。言語が違っても同じ番号）
    numbers = {p["slug"]: i for i, p in enumerate(reversed(public), 1)}
    wanted: set[Path] = set()
    for p in public:
        cards = load_cards(p, allow_fetch)
        for lang, v in versions[p["slug"]].items():
            path = lang_root(lang) / p["slug"] / "index.html"
            out[path] = build_post_page(v, lang, numbers[p["slug"]], ja_index, cards, versions[p["slug"]], genres)
            wanted.add(path)
    # 公開をやめた記事・下書きに戻した記事・使わなくなった翻訳のページは消す
    for lang in ("ja",) + LANGS:
        root = lang_root(lang)
        if not root.exists():
            continue
        for d in root.iterdir():
            page = d / "index.html"
            if d.is_dir() and page.exists() and page not in wanted \
                    and "tools/build_blog.py" in page.read_text(encoding="utf-8"):
                out[page] = None

    # 一覧データ（フィルムのコマ）。翻訳がある言語は、その言語のタイトル・タグ・URL を持つ
    listing = []
    for p in public:
        _, _, images = render_body(p, {})
        cover = p.get("cover") or (images[0] if images else "")
        item = {
            "Id": p["slug"],
            "Date": p["date_obj"].isoformat(timespec="minutes"),
            "Title": p["title"],
            "Image": f"/images/{cover}" if cover else "",
            "Url": post_url(p["slug"], "ja"),
            "Number": numbers[p["slug"]],
            "Genres": list(p.get("genres") or []),
            "Tags": list(p.get("tags") or []),
        }
        for lang, t in versions[p["slug"]].items():
            if lang != "ja":
                item[lang] = {"Title": t["title"], "Tags": t["tags"], "Url": post_url(p["slug"], lang)}
        listing.append(item)
    out[BLOG_DIR / "posts.json"] = json.dumps(listing, ensure_ascii=False, indent=2) + "\n"
    # 一覧の絞り込みボタン用のジャンル一覧（記事数つき。0件のジャンルはボタンを出さない）
    counts = {g["id"]: sum(g["id"] in (p.get("genres") or []) for p in public) for g in genres}
    out[BLOG_DIR / "genres.json"] = json.dumps(
        [{"Id": g["id"], "Count": counts[g["id"]],
          **{lang: {"Label": g_text(g, "label", lang), "Name": g_text(g, "name", lang)} for lang in ("ja",) + LANGS}}
         for g in genres], ensure_ascii=False, indent=2) + "\n"
    # RSS（言語ごと）
    for lang in ("ja",) + LANGS:
        out[lang_root(lang) / "feed.xml"] = build_feed(
            [(versions[p["slug"]][lang], post_url(p["slug"], lang)) for p in per_lang[lang]], lang)

    # サイトマップ
    sm_path = ROOT / "sitemap.xml"
    sm = sm_path.read_text(encoding="utf-8")
    entries: list[str] = []
    if public:
        entries += sitemap_entry({lg: list_url(lg) for lg in list_langs}, public[0]["date_obj"])
        for p in public:
            entries += sitemap_entry({lg: post_url(p["slug"], lg) for lg in versions[p["slug"]]}, p["date_obj"])
    urls = "\n".join(entries)
    out[sm_path] = re.sub(r"(  <!-- blog:urls -->\n).*?(  <!-- /blog:urls -->)",
                          lambda m: m.group(1) + (urls + "\n" if urls else "") + m.group(2), sm, flags=re.S)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="書き換えず、組み立て結果が最新か確認だけする")
    parser.add_argument("--now", help="現在時刻を指定（確認用。例: 2026-10-20T18:00+09:00）")
    parser.add_argument("--no-fetch", action="store_true", help="リンク先のタイトルを取得しない")
    parser.add_argument("--report", help="今回あらたに公開された記事の一覧を JSON で書き出すファイル（自動公開の通知用）")
    args = parser.parse_args()
    now = dt.datetime.fromisoformat(args.now) if args.now else dt.datetime.now(JST)

    out = build(now, allow_fetch=not (args.check or args.no_fetch))
    changed = []
    newly_public = []
    for path, content in out.items():
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current is None and content is not None and path.name == "index.html" and path.parent.parent == BLOG_DIR:
            src = CONTENT_DIR / path.parent.name / "index.md"
            if src.exists():
                post = read_post(src)
                newly_public.append({"slug": post["slug"], "title": post.get("title", ""),
                                     "source_issue": post.get("source_issue"),
                                     "url": f"{SITE}/blog/{post['slug']}/"})
        if current == content:
            continue
        changed.append(path.relative_to(ROOT))
        if args.check:
            continue
        if content is None:
            path.unlink()
            try:
                path.parent.rmdir()
            except OSError:
                pass
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    if args.check:
        for c in changed:
            print(f"⚠ 組み立て結果が最新ではありません: {c}（python3 tools/build_blog.py を実行してください）", file=sys.stderr)
        print("確認OK" if not changed else f"{len(changed)} 件の問題があります")
        return 1 if changed else 0
    if args.report:
        Path(args.report).write_text(json.dumps(newly_public, ensure_ascii=False), encoding="utf-8")
    for c in changed:
        print(f"更新: {c}")
    if not changed:
        print("変更はありません")
    return 0


if __name__ == "__main__":
    sys.exit(main())
