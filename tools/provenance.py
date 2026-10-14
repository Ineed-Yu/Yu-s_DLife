#!/usr/bin/env python3
"""撮影者の証拠を写真データの中に残すためのスクリプト（ページには何も表示されません）。

3つの仕組みを組み合わせます。

1. 情報欄（メタデータ）への記入
   画像ファイルの情報欄（EXIF の Artist / Copyright、XMP の dc:creator / dc:rights）に
   撮影者名と著作権表記を書き込みます。元写真は画質を変えずに追記、表示用の軽量版にも入れます。
   → 画像を保存した人がファイルの情報を見れば分かる。ただし SNS 等では消されることがある。

2. 見えない透かし（表示用の軽量版のみ）
   画素の明るさをごくわずか（最大でも 0〜255 のうち数段階）だけ、決まった模様に沿って変えます。
   目では分かりませんが、このスクリプトで調べると「透かしあり」と判定できます。
   情報欄を消されても、縮小・再圧縮・スクリーンショットされても検出できるように作っています。
   （大きく切り抜かれた場合は検出できないことがあります）

3. 指紋（ハッシュ値）の記録
   写真ファイルごとの SHA-256 ハッシュ値を provenance/ の一覧に記録します。
   一覧を GitHub の Pull Request で残すと、その日時に運営者がこの写真を持っていた記録になります。
   一覧ファイル全体のハッシュ値を X に投稿しておくと、第三者の日時の記録にもなります。

使い方:
  python3 tools/provenance.py check 画像ファイル...   # 情報欄・透かし・記録の有無を調べる
  python3 tools/provenance.py manifest                # 未記録の写真の指紋を provenance/ に記録する
  （情報欄の記入と透かしは tools/optimize_images.py が自動で行います）

必要なもの: Python 3、Pillow、numpy
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import os
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps, PngImagePlugin

ROOT = Path(__file__).resolve().parent.parent

# ---- 設定（管理者の決定: 2026-10-14） ----
CREATOR = "Yu (@DivaClarice321)"
WATERMARK_SEED = "Yu (@DivaClarice321) / divaclarice321.com"

# 透かしの設定（変えると過去の画像の透かしを検出できなくなるので、変えないこと）
GRID = 128              # 模様のマス目（画像の大きさに合わせて引き伸ばす）
STRENGTH_BASE = 1.5     # 平らな部分（空など）での変化量（0〜255 の段階）
STRENGTH_TEXTURE = 3.0  # 細かい模様の部分で追加する変化量（目立ちにくいので少し強く）
DETECT_THRESHOLD = 5.0  # これ以上なら「透かしあり」（透かしの無い写真はおよそ -2〜+2）

EXIF_ARTIST = 0x013B
EXIF_COPYRIGHT = 0x8298
EXIF_IFD = 0x8769
EXIF_DATETIME_ORIGINAL = 0x9003
EXIF_DATETIME = 0x0132

MANIFEST_DIR = ROOT / "provenance"
IMAGE_DIR = ROOT / "images"
SOURCE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".tif", ".tiff"}


# ======================================================================
# 1. 情報欄（メタデータ）
# ======================================================================
def capture_year(im: Image.Image) -> int:
    """写真の撮影年（分からなければ今年）。著作権表記の年に使う。"""
    try:
        exif = im.getexif()
        for value in (exif.get_ifd(EXIF_IFD).get(EXIF_DATETIME_ORIGINAL), exif.get(EXIF_DATETIME)):
            if value and str(value)[:4].isdigit():
                return int(str(value)[:4])
    except Exception:
        pass
    return dt.date.today().year


def copyright_text(year: int) -> str:
    # EXIF の文字欄は英数字しか入らないため、© ではなく Copyright と書く（写真の世界で一般的な表記）
    return f"Copyright {year} {CREATOR}. All rights reserved."


def exif_bytes(year: int) -> bytes:
    exif = Image.Exif()
    exif[EXIF_ARTIST] = CREATOR
    exif[EXIF_COPYRIGHT] = copyright_text(year)
    return exif.tobytes()


def xmp_bytes(year: int) -> bytes:
    def esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (
        '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:xmpRights="http://ns.adobe.com/xap/1.0/rights/">'
        f'<dc:creator><rdf:Seq><rdf:li>{esc(CREATOR)}</rdf:li></rdf:Seq></dc:creator>'
        f'<dc:rights><rdf:Alt><rdf:li xml:lang="x-default">{esc(copyright_text(year))}</rdf:li></rdf:Alt></dc:rights>'
        '<xmpRights:Marked>True</xmpRights:Marked>'
        '</rdf:Description></rdf:RDF></x:xmpmeta><?xpacket end="w"?>'
    ).encode("utf-8")


def read_credit(path: Path) -> tuple[str | None, str | None]:
    """画像の情報欄から（撮影者名, 著作権表記）を読む。"""
    with Image.open(path) as im:
        exif = im.getexif()
        artist, rights = exif.get(EXIF_ARTIST), exif.get(EXIF_COPYRIGHT)
        if artist is None and im.format == "PNG":
            artist, rights = im.info.get("Author"), im.info.get("Copyright")
    return artist, rights


def tag_jpeg_original(path: Path) -> bool:
    """元写真（JPEG）の情報欄に撮影者名・著作権表記を追記する。
    画像データは再圧縮しないので画質は変わらない。撮影日時・機種・シリアル番号などはそのまま残す。"""
    data = path.read_bytes()
    if data[:2] != b"\xff\xd8":
        return False
    out = bytearray(data[:2])
    i, found_exif, changed = 2, False, False

    def build_segment(exif: Image.Exif) -> bytes:
        body = exif.tobytes()
        if not body.startswith(b"Exif"):
            body = b"Exif\x00\x00" + body
        return b"\xff\xe1" + struct.pack(">H", len(body) + 2) + body

    with Image.open(path) as im:
        year = capture_year(im)

    while i < len(data):
        if data[i] != 0xFF:
            return False  # 想定外の形式なので触らない
        marker = data[i + 1]
        if marker == 0xDA:
            if not found_exif:  # EXIF が無い写真には新しく作る
                exif = Image.Exif()
                exif[EXIF_ARTIST] = CREATOR
                exif[EXIF_COPYRIGHT] = copyright_text(year)
                out += build_segment(exif)
                changed = True
            out += data[i:]
            break
        length = struct.unpack(">H", data[i + 2:i + 4])[0]
        segment = data[i:i + 2 + length]
        if marker == 0xE1 and segment[4:10] == b"Exif\x00\x00" and not found_exif:
            found_exif = True
            exif = Image.Exif()
            exif.load(segment[4:])
            if exif.get(EXIF_ARTIST) != CREATOR or exif.get(EXIF_COPYRIGHT) != copyright_text(year):
                exif[EXIF_ARTIST] = CREATOR
                exif[EXIF_COPYRIGHT] = copyright_text(year)
                segment = build_segment(exif)
                changed = True
        out += segment
        i += 2 + length
    if changed:
        stat = path.stat()
        path.write_bytes(bytes(out))
        os.utime(path, (stat.st_atime, stat.st_mtime))
    return changed


def tag_png_original(path: Path) -> bool:
    """元写真（PNG）に撮影者名・著作権表記を追記する（PNG は劣化しない形式なので画素は同じ）。"""
    with Image.open(path) as im:
        year = capture_year(im)
        if im.info.get("Author") == CREATOR and im.info.get("Copyright") == copyright_text(year):
            return False
        info = PngImagePlugin.PngInfo()
        for k, v in im.info.items():
            if isinstance(v, str) and k not in ("Author", "Copyright"):
                info.add_text(k, v)
        info.add_text("Author", CREATOR)
        info.add_text("Copyright", copyright_text(year))
        im.load()
        exif = im.getexif()
        exif[EXIF_ARTIST] = CREATOR
        exif[EXIF_COPYRIGHT] = copyright_text(year)
        stat = path.stat()
        im.save(path, "PNG", pnginfo=info, exif=exif.tobytes(), optimize=True)
    os.utime(path, (stat.st_atime, stat.st_mtime))
    return True


def tag_original(path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return tag_jpeg_original(path)
    if suffix == ".png":
        return tag_png_original(path)
    return False  # HEIC などは触らない


# ======================================================================
# 2. 見えない透かし
# ======================================================================
def _gaussian_blur(a: np.ndarray, sigma: float) -> np.ndarray:
    radius = max(1, int(round(sigma * 3)))
    x = np.arange(-radius, radius + 1)
    k = np.exp(-(x ** 2) / (2 * sigma ** 2))
    k /= k.sum()
    pad = np.pad(a, radius, mode="reflect")
    tmp = np.apply_along_axis(lambda r: np.convolve(r, k, mode="valid"), 1, pad)
    return np.apply_along_axis(lambda c: np.convolve(c, k, mode="valid"), 0, tmp)


def _highpass(a: np.ndarray, sigma: float = 1.2) -> np.ndarray:
    return a - _gaussian_blur(a, sigma)


def _pattern() -> np.ndarray:
    seed = int.from_bytes(hashlib.sha256(WATERMARK_SEED.encode("utf-8")).digest()[:8], "big")
    rng = np.random.default_rng(seed)
    return rng.choice(np.array([-1.0, 1.0]), size=(GRID, GRID))


def _luma(rgb: np.ndarray) -> np.ndarray:
    return rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114


def embed_watermark(im: Image.Image) -> Image.Image:
    """表示用の画像に見えない透かしを入れる（RGB / RGBA）。"""
    has_alpha = im.mode == "RGBA"
    rgb = np.asarray(im.convert("RGB"), dtype=np.float64)
    h, w = rgb.shape[:2]
    pat = Image.fromarray(_pattern().astype(np.float32), mode="F").resize((w, h), Image.BILINEAR)
    pat = np.asarray(pat, dtype=np.float64)

    # 細かい模様のある所は変化が目立たないので少し強く、平らな所は弱く
    y = _luma(rgb)
    activity = _gaussian_blur(np.abs(_highpass(y, 1.5)), 3.0)
    activity = np.clip(activity / 12.0, 0, 1)
    strength = STRENGTH_BASE + STRENGTH_TEXTURE * activity

    delta = (strength * pat)[..., None]
    out = np.clip(rgb + delta, 0, 255).round().astype(np.uint8)
    result = Image.fromarray(out, "RGB")
    if has_alpha:
        result.putalpha(im.getchannel("A"))
    return result


def detect_watermark(im: Image.Image) -> float:
    """透かしの強さ（z 値）を返す。DETECT_THRESHOLD 以上なら透かしあり。"""
    rgb = im.convert("RGB")
    y = np.asarray(rgb, dtype=np.float64)
    y = Image.fromarray(_luma(y).astype(np.float32), mode="F").resize((GRID, GRID), Image.BOX)
    y = _highpass(np.asarray(y, dtype=np.float64))
    # 写真の輪郭など強い模様の影響を抑える（場所ごとの揺れの大きさで割ってならす）
    local = np.sqrt(_gaussian_blur(y ** 2, 2.0)) + 0.5
    y = y / local
    p = _highpass(_pattern())
    denom = np.sqrt((y ** 2).sum() * (p ** 2).sum())
    if denom == 0:
        return 0.0
    return float((y * p).sum() / denom * GRID)


# ======================================================================
# 3. 指紋（ハッシュ値）の記録
# ======================================================================
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def recorded_hashes() -> dict[str, str]:
    known: dict[str, str] = {}
    for m in sorted(MANIFEST_DIR.glob("manifest-*.txt")):
        for line in m.read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#"):
                digest, _, name = line.partition("  ")
                known[digest] = f"{m.name}: {name}"
    return known


def write_manifest(folder: Path, out_dir: Path, include_all: bool) -> Path | None:
    out_dir.mkdir(parents=True, exist_ok=True)
    known = recorded_hashes() if out_dir == MANIFEST_DIR else {}
    files = sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in SOURCE_EXT
                   and "opt" not in p.relative_to(folder).parts)
    rows = []
    for p in files:
        digest = sha256_file(p)
        if include_all or digest not in known:
            rows.append(f"{digest}  {p.relative_to(folder).as_posix()}")
    if not rows:
        print("新しく記録する写真はありません。")
        return None
    today = dt.date.today().isoformat()
    out = out_dir / f"manifest-{today}.txt"
    n = 2
    while out.exists():
        out = out_dir / f"manifest-{today}-{n}.txt"
        n += 1
    header = [
        "# 写真の指紋（SHA-256 ハッシュ値）の一覧",
        f"# 撮影者: {CREATOR}",
        f"# 作成日: {today}",
        f"# 対象フォルダ: {folder.name}/（{len(rows)} 件）",
        "# 形式: ハッシュ値␣␣ファイル名",
    ]
    out.write_text("\n".join(header + rows) + "\n", encoding="utf-8")
    print(f"記録しました: {out}（{len(rows)} 件）")
    print(f"この一覧ファイル自体の指紋（X などに投稿しておくと日時の証拠になります）:\n  {sha256_file(out)}")
    return out


# ======================================================================
# コマンド
# ======================================================================
def cmd_check(paths: list[str]) -> int:
    known = recorded_hashes()
    for name in paths:
        path = Path(name)
        print(f"■ {path}")
        try:
            artist, rights = read_credit(path)
            print(f"  情報欄の撮影者: {artist or '（なし）'}")
            print(f"  情報欄の著作権: {rights or '（なし）'}")
        except Exception as e:  # HEIC など Pillow で開けない形式
            print(f"  情報欄: 読めませんでした（{e.__class__.__name__}）")
        try:
            with Image.open(path) as im:
                z = detect_watermark(ImageOps.exif_transpose(im))
            verdict = "あり" if z >= DETECT_THRESHOLD else "なし"
            print(f"  見えない透かし: {verdict}（強さ {z:.1f}、{DETECT_THRESHOLD} 以上で「あり」）")
        except Exception:
            print("  見えない透かし: 調べられませんでした")
        rec = known.get(sha256_file(path))
        print(f"  指紋の記録: {rec if rec else '一覧にありません'}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="画像の情報欄・透かし・記録の有無を調べる")
    c.add_argument("files", nargs="+")
    m = sub.add_parser("manifest", help="写真の指紋を一覧に記録する")
    m.add_argument("--dir", default=str(IMAGE_DIR), help="対象フォルダ（既定: images/。手元の RAW フォルダも指定可）")
    m.add_argument("--out", default=str(MANIFEST_DIR), help="一覧の保存先（既定: provenance/）")
    m.add_argument("--all", action="store_true", help="記録済みの写真も含めて全部書く")
    args = parser.parse_args()
    if args.cmd == "check":
        return cmd_check(args.files)
    write_manifest(Path(args.dir).resolve(), Path(args.out).resolve(), args.all)
    return 0


if __name__ == "__main__":
    sys.exit(main())
