#!/usr/bin/env python3
"""ブログの入稿フォーム（GitHub Issue）の内容から、原稿ファイルを作るスクリプト。

GitHub Actions（.github/workflows/blog-intake.yml）から自動で呼ばれます。手で動かす必要はありません。

  入稿フォーム（Issue）  →  content/blog/<URL名>/index.md   … 原稿（項目欄＋本文）
                         →  images/blog-<URL名>-cover.jpg   … 見出し画像（元写真）
                         →  images/blog-<URL名>-01.jpg …    … 本文の写真（元写真）

- 写真は GitHub に添付されたもの（github.com/user-attachments など）だけをダウンロードします。
- 入力された文字はそのまま原稿に書き、HTML としては扱いません（記事ビルドで安全に変換します）。
- 同じ Issue を編集して保存すると、同じ記事を上書きします（URL 名は最初に決まったものを使い続けます）。

使い方（Actions 内）:
  python3 tools/blog_intake.py イベントのJSONファイル
  → 結果を JSON で標準出力に出す（{"slug": ..., "status": ..., "publish_at": ..., "url": ..., "errors": [...]}）
"""
from __future__ import annotations

import datetime as dt
import io
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
CONTENT_DIR = ROOT / "content" / "blog"
IMAGE_DIR = ROOT / "images"
SITE = "https://divaclarice321.com"
JST = dt.timezone(dt.timedelta(hours=9))

# 入稿を受け付ける人（Issue を作った人とリポジトリの関係）。それ以外は何もしない
ALLOWED_ASSOCIATIONS = {"OWNER", "COLLABORATOR", "MEMBER"}

# フォームの見出し → 項目名（.github/ISSUE_TEMPLATE/blog-post.yml の label と一致させる）
FIELDS = {
    "タイトル": "title",
    "公開のしかた": "publish",
    "公開日時（日本時間）": "datetime",
    "見出し画像": "cover",
    "本文": "body",
    "ひとこと説明（任意）": "summary",
    "タグ（任意）": "tags",
    "記事の URL 名（任意）": "slug",
    "その他": "options",
    "入稿の確認": "approval",
}
PUBLISH_NOW, PUBLISH_SCHEDULED, PUBLISH_DRAFT = "すぐに公開する", "日時を指定して公開する（予約投稿）", "下書きとして保存する（公開しない）"

# 写真をダウンロードしてよい場所（GitHub に添付された画像だけ）
ALLOWED_IMAGE_HOSTS = {"github.com", "user-images.githubusercontent.com", "private-user-images.githubusercontent.com"}
MAX_IMAGE_BYTES = 30 * 1024 * 1024

IMG_MD = re.compile(r"!\[([^\]]*)\]\((\S+?)\)")
IMG_HTML = re.compile(r"<img\b[^>]*>", re.I)
ATTR = re.compile(r'(\w+)\s*=\s*"([^"]*)"')
SLUG_OK = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")


class IntakeError(Exception):
    pass


# ---------------------------------------------------------------- フォームの読み取り
def parse_form(body: str) -> dict[str, str]:
    """Issue フォームの本文（### 見出し + 値 の並び）を項目ごとに分ける。"""
    values: dict[str, str] = {}
    current, buf = None, []
    for line in (body or "").replace("\r\n", "\n").split("\n"):
        m = re.match(r"^### (.+?)\s*$", line)
        if m and m.group(1) in FIELDS:
            if current:
                values[current] = "\n".join(buf).strip()
            current, buf = FIELDS[m.group(1)], []
        else:
            buf.append(line)
    if current:
        values[current] = "\n".join(buf).strip()
    for k, v in list(values.items()):
        if v == "_No response_":
            values[k] = ""
    return values


def checked(text: str) -> bool:
    return bool(re.search(r"^- \[[xX]\]", text or "", re.M))


def parse_datetime(text: str) -> dt.datetime | None:
    text = (text or "").strip().replace("／", "/").replace("：", ":")
    if not text:
        return None
    text = re.sub(r"[年月/.]", "-", text).replace("日", " ").strip()
    text = re.sub(r"\s+", " ", text)
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H時%M分", "%Y-%m-%d %H時", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(text, fmt).replace(tzinfo=JST)
        except ValueError:
            continue
    raise IntakeError(f"公開日時「{text}」を読み取れませんでした。2026-10-20 18:00 の形で入力してください。")


# ---------------------------------------------------------------- 写真
def _is_allowed_image_url(url: str) -> bool:
    u = urllib.parse.urlparse(url)
    if u.scheme != "https" or u.hostname not in ALLOWED_IMAGE_HOSTS:
        return False
    if u.hostname == "github.com":
        return u.path.startswith("/user-attachments/assets/") or "/assets/" in u.path
    return True


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # 自分で処理する（認証情報を他のサーバーに渡さないため）
        return None


def download(url: str, token: str | None) -> bytes:
    """GitHub の添付画像を取得する。リダイレクト先（保存サーバー）には認証情報を送らない。"""
    headers = {"User-Agent": "yu-s-dlife-blog-intake"}
    if token and urllib.parse.urlparse(url).hostname == "github.com":
        headers["Authorization"] = f"Bearer {token}"
    opener = urllib.request.build_opener(_NoRedirect)
    for _ in range(5):
        req = urllib.request.Request(url, headers=headers)
        try:
            with opener.open(req, timeout=60) as r:
                data = r.read(MAX_IMAGE_BYTES + 1)
                if len(data) > MAX_IMAGE_BYTES:
                    raise IntakeError("写真が大きすぎます（30MB まで）。")
                return data
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                url = urllib.parse.urljoin(url, e.headers["Location"])
                headers = {"User-Agent": headers["User-Agent"]}  # 認証情報は外す
                continue
            raise IntakeError(f"写真をダウンロードできませんでした（HTTP {e.code}）。") from None
    raise IntakeError("写真のダウンロードでリダイレクトが多すぎます。")


def save_image(data: bytes, dest_stem: Path) -> str:
    """写真の形式を確かめて images/ に保存し、ファイル名を返す。"""
    head = data[:16]
    if head.startswith(b"\xff\xd8"):
        path = dest_stem.with_suffix(".jpg")
        path.write_bytes(data)
    elif head.startswith(b"\x89PNG"):
        path = dest_stem.with_suffix(".png")
        path.write_bytes(data)
    elif head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        path = dest_stem.with_suffix(".png")  # WebP は劣化しない PNG に変えて元写真として保存
        Image.open(io.BytesIO(data)).save(path, "PNG")
    elif b"ftyp" in head[:12] and any(t in data[:32] for t in (b"heic", b"heix", b"mif1", b"heif")):
        raise IntakeError("HEIC 形式の写真には対応していません。iPhone の場合は「設定 → カメラ → フォーマット → 互換性優先」にするか、JPG に変えてから入れてください。")
    else:
        raise IntakeError("JPG・PNG 以外の形式の写真が含まれています。")
    Image.open(path).verify()  # 壊れた画像を弾く
    return path.name


def extract_images(text: str) -> list[tuple[str, str, str]]:
    """本文中の画像（Markdown 形式と <img> 形式）を (元の文字列, 説明, URL) で返す。"""
    found = [(m.group(0), m.group(1), m.group(2)) for m in IMG_MD.finditer(text)]
    for m in IMG_HTML.finditer(text):
        attrs = dict((k.lower(), v) for k, v in ATTR.findall(m.group(0)))
        if attrs.get("src"):
            found.append((m.group(0), attrs.get("alt", ""), attrs["src"]))
    return found


# ---------------------------------------------------------------- 原稿
def existing_slug_for_issue(issue_number: int) -> str | None:
    for md in CONTENT_DIR.glob("*/index.md"):
        if re.search(rf"^source_issue: {issue_number}\s*$", md.read_text(encoding="utf-8"), re.M):
            return md.parent.name
    return None


def yaml_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)  # JSON 文字列は YAML としても正しい


def remove_old_images(slug: str) -> None:
    for p in IMAGE_DIR.glob(f"blog-{slug}-*"):
        if p.is_file():
            p.unlink()
    for p in (IMAGE_DIR / "opt").glob(f"blog-{slug}-*"):
        p.unlink()


def run(event: dict, token: str | None, now: dt.datetime | None = None, fetch=download) -> dict:
    issue = event.get("issue") or {}
    if issue.get("author_association") not in ALLOWED_ASSOCIATIONS:
        return {"skipped": "入稿できるのはリポジトリの管理者だけです。"}
    form = parse_form(issue.get("body") or "")
    if "title" not in form or "publish" not in form:
        return {"skipped": "ブログの入稿フォームではありません。"}

    errors: list[str] = []
    number = int(issue["number"])
    now = now or dt.datetime.now(JST)
    title = form.get("title", "").strip()
    if not title:
        errors.append("タイトルが空です。")
    if not checked(form.get("approval", "")):
        errors.append("「入稿の確認」にチェックが入っていません。")

    publish = form.get("publish", PUBLISH_NOW).strip()
    try:
        when = parse_datetime(form.get("datetime", ""))
    except IntakeError as e:
        errors.append(str(e))
        when = None
    if publish == PUBLISH_SCHEDULED:
        if when is None:
            errors.append("予約投稿のときは「公開日時」を入力してください。")
        elif when <= now:
            errors.append("予約投稿の公開日時が過去になっています。今すぐ公開する場合は「すぐに公開する」を選んでください。")
        status = "scheduled"
    elif publish == PUBLISH_DRAFT:
        status = "draft"
    else:
        status = "published"
    # URL 名：編集のときは最初に決まったものを使い続ける
    slug = existing_slug_for_issue(number)
    # 編集で日時欄が空なら、最初の投稿日時をそのまま使う（編集した時刻に変わらないように）
    if when is None and slug:
        m = re.search(r"^date: (\S+)", (CONTENT_DIR / slug / "index.md").read_text(encoding="utf-8"), re.M)
        if m:
            when = dt.datetime.fromisoformat(m.group(1))
    publish_at = when or now
    wanted = form.get("slug", "").strip().lower()
    if not slug:
        if wanted:
            if not SLUG_OK.match(wanted):
                errors.append("記事の URL 名は、半角の英小文字・数字・ハイフンで2〜61文字にしてください。")
            elif (CONTENT_DIR / wanted).exists():
                errors.append(f"記事の URL 名「{wanted}」はすでに使われています。")
            slug = wanted
        else:
            slug = f"{publish_at:%Y%m%d}-{number}"
    elif wanted and wanted != slug:
        errors.append(f"記事の URL 名は公開後に変えられません（今の URL 名: {slug}）。")

    body = form.get("body", "").strip()
    if not body:
        errors.append("本文が空です。")
    if errors:
        return {"slug": slug, "status": "error", "errors": errors}

    # 写真をダウンロードして保存（編集時は作り直す）
    IMAGE_DIR.mkdir(exist_ok=True)
    remove_old_images(slug)
    cover_name = None
    cover_imgs = extract_images(form.get("cover", ""))
    try:
        if cover_imgs:
            if not _is_allowed_image_url(cover_imgs[0][2]):
                raise IntakeError("見出し画像は、フォームに直接ドラッグ＆ドロップした写真だけ使えます。")
            cover_name = save_image(fetch(cover_imgs[0][2], token), IMAGE_DIR / f"blog-{slug}-cover")
        n = 0
        for original, alt, url in extract_images(body):
            if not _is_allowed_image_url(url):
                raise IntakeError("本文の写真は、フォームに直接ドラッグ＆ドロップしたものだけ使えます。")
            n += 1
            name = save_image(fetch(url, token), IMAGE_DIR / f"blog-{slug}-{n:02d}")
            alt = re.sub(r"[\[\]\n]", " ", alt).strip()
            body = body.replace(original, f"\n\n![{alt}]({name})\n\n", 1)
    except IntakeError as e:
        remove_old_images(slug)
        return {"slug": slug, "status": "error", "errors": [str(e)]}

    tags = [t.strip() for t in re.split(r"[,、，]", form.get("tags", "")) if t.strip()][:10]
    folder = CONTENT_DIR / slug
    folder.mkdir(parents=True, exist_ok=True)
    front = [
        "---",
        f"title: {yaml_str(title)}",
        f"date: {publish_at.isoformat(timespec='minutes')}",
        f"status: {status}",
        f"cover: {yaml_str(cover_name or '')}",
        f"summary: {yaml_str(form.get('summary', '').strip())}",
        f"tags: {json.dumps(tags, ensure_ascii=False)}",
        f"ai_assisted: {'true' if checked(form.get('options', '')) else 'false'}",
        f"source_issue: {number}",
        "---",
        "",
    ]
    body = re.sub(r"\n{3,}", "\n\n", body).strip() + "\n"
    (folder / "index.md").write_text("\n".join(front) + body, encoding="utf-8")
    return {
        "slug": slug,
        "status": status,
        "publish_at": publish_at.isoformat(timespec="minutes"),
        "url": f"{SITE}/blog/{slug}/",
        "errors": [],
    }


def comment_for(result: dict) -> str:
    """入稿結果を、入稿ページ（Issue）に書き込むコメントの文章にする。"""
    if result.get("errors"):
        lines = ["⚠️ **入稿できませんでした。** 次の点を直して、このページを「Edit」で保存し直してください。", ""]
        lines += [f"- {e}" for e in result["errors"]]
        return "\n".join(lines)
    status = result.get("status")
    url = result.get("url", "")
    if status == "published":
        return (f"✅ **公開しました。** {url}\n\n"
                "サイトに反映されるまで数分かかることがあります。直したいときは、このページを「Edit」で保存し直すと記事も更新されます。"
                "\n非公開に戻すときは「公開のしかた」を「下書きとして保存する」に変えて保存してください。")
    if status == "scheduled":
        when = result.get("publish_at", "")[:16].replace("T", " ")
        return (f"🕒 **予約しました。** {when}（日本時間）に公開されます（最大1時間ほど遅れることがあります）。\n\n"
                f"公開後の URL: {url}\n公開されたら、このページに改めてお知らせして閉じます。")
    if status == "draft":
        return ("📝 **下書きとして保存しました（公開していません）。**\n\n"
                "公開するときは、このページを「Edit」で開き「公開のしかた」を変えて保存してください。\n"
                "※ 下書きの原稿は公開リポジトリ内に置かれるため、GitHub 上では誰でも読める状態です。")
    return ""


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "comment":
        print(comment_for(json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))))
        return 0
    event = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    result = run(event, os.environ.get("GITHUB_TOKEN"))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
