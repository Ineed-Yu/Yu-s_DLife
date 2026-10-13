#!/usr/bin/env python3
"""サイト用の軽量画像（WebP）を作るスクリプト。

images/ にある写真（JPG / PNG）から、表示サイズ別の軽量版を images/opt/ に作ります。

  images/clarice_hkdl_002.jpg  →  images/opt/clarice_hkdl_002-160.webp
                                   images/opt/clarice_hkdl_002-480.webp
                                   images/opt/clarice_hkdl_002-960.webp
                                   images/opt/clarice_hkdl_002-1600.webp

- 数字は横幅(px)。元画像より大きくはしません（小さい写真はそのままの大きさ）。
- 撮影日時・機種・位置情報などのメタデータはすべて取り除きます。
- カメラの向き情報（縦撮り）を反映してから保存するので、見た目の向きは元と同じです。
- 作成済みで元画像が更新されていないものはスキップします。
- 元の写真（JPG）に位置情報が入っていたら、画質を変えずに位置情報だけを削除します。

使い方:
  python3 tools/optimize_images.py           # 足りない軽量版を作る
  python3 tools/optimize_images.py --check   # 作り忘れ・位置情報入りの写真がないか確認だけする
                                             # （問題があれば終了コード 1。GitHub の自動チェックで使用）

必要なもの: Python 3.9 以上、Pillow（pip install Pillow）
"""
from __future__ import annotations

import argparse
import os
import struct
import sys
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "images"
OUT_DIR = SRC_DIR / "opt"

# 作る横幅の種類（用途の目安）
#   160  : X / Instagram 風カードの丸アイコン（表示 40px）
#   480  : プロフィールアイコン、縦長写真のカード、ピンバッジ一覧
#   960  : 横長写真のカード、ピン詳細
#   1600 : ページやセクションの背景
WIDTHS = (160, 480, 960, 1600)
QUALITY = 80
SOURCE_EXT = {".jpg", ".jpeg", ".png"}
GPS_TAG = 0x8825


def out_name(src: Path, width: int) -> Path:
    # 先頭の "_" は付けない（公開時に除外される仕組みがあるため）
    stem = src.stem.lstrip("_") or src.stem
    return OUT_DIR / f"{stem}-{width}.webp"


def sources() -> list[Path]:
    return sorted(p for p in SRC_DIR.iterdir() if p.is_file() and p.suffix.lower() in SOURCE_EXT)


def has_gps(path: Path) -> bool:
    try:
        gps = Image.open(path).getexif().get_ifd(GPS_TAG)
    except Exception:
        return False
    return 2 in gps or 4 in gps  # 緯度または経度がある


def strip_gps_jpeg(path: Path) -> bool:
    """JPEG の位置情報だけを取り除く（画像データは再圧縮しないので画質は変わらない）。"""
    data = path.read_bytes()
    if data[:2] != b"\xff\xd8":
        return False
    out = bytearray(data[:2])
    i, changed = 2, False
    while i < len(data):
        if data[i] != 0xFF:
            return False  # 想定外の形式なので触らない
        marker = data[i + 1]
        if marker == 0xDA:  # 画像データ本体以降はそのままコピー
            out += data[i:]
            break
        length = struct.unpack(">H", data[i + 2:i + 4])[0]
        segment = data[i:i + 2 + length]
        if marker == 0xE1 and segment[4:10] == b"Exif\x00\x00" and not changed:
            exif = Image.Exif()
            exif.load(segment[4:])
            if GPS_TAG in exif:
                del exif[GPS_TAG]
                body = exif.tobytes()
                if not body.startswith(b"Exif"):
                    body = b"Exif\x00\x00" + body
                segment = b"\xff\xe1" + struct.pack(">H", len(body) + 2) + body
                changed = True
        out += segment
        i += 2 + length
    if changed:
        stat = path.stat()
        path.write_bytes(bytes(out))
        os.utime(path, (stat.st_atime, stat.st_mtime))  # 軽量版を作り直さないよう日時は維持
    return changed


def is_stale(src: Path, dst: Path) -> bool:
    return not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime


def build(src: Path) -> list[Path]:
    made = []
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)  # 縦撮りの向きを反映
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
        for w in WIDTHS:
            dst = out_name(src, w)
            if not is_stale(src, dst):
                continue
            target_w = min(w, im.width)
            target_h = round(im.height * target_w / im.width)
            resized = im if target_w == im.width else im.resize((target_w, target_h), Image.LANCZOS)
            # exif などは渡さない → メタデータなしで保存される
            resized.save(dst, "WEBP", quality=QUALITY, method=6)
            made.append(dst)
    return made


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="作成はせず、問題がないか確認だけする")
    args = parser.parse_args()

    OUT_DIR.mkdir(exist_ok=True)
    problems: list[str] = []

    for src in sources():
        rel = src.relative_to(ROOT)
        if has_gps(src):
            if not args.check and src.suffix.lower() in {".jpg", ".jpeg"} and strip_gps_jpeg(src):
                print(f"位置情報を削除: {rel}")
            else:
                problems.append(f"位置情報(GPS)が入っています: {rel}（python3 tools/optimize_images.py で削除できます）")
        missing = [out_name(src, w).name for w in WIDTHS if not out_name(src, w).exists()]
        if args.check:
            if missing:
                problems.append(f"軽量版が未作成です: {rel}（python3 tools/optimize_images.py を実行してください）")
            continue
        made = build(src)
        if made:
            print(f"作成: {rel} → {', '.join(p.name for p in made)}")

    # 元画像が無くなった軽量版（消し忘れ）を知らせる
    expected = {out_name(s, w).name for s in sources() for w in WIDTHS}
    for orphan in sorted(p for p in OUT_DIR.glob("*.webp") if p.name not in expected):
        problems.append(f"元画像のない軽量版があります（削除してよいか確認）: {orphan.relative_to(ROOT)}")

    for p in problems:
        print("⚠ " + p, file=sys.stderr)
    if args.check:
        print("確認OK" if not problems else f"{len(problems)} 件の問題があります")
        return 1 if problems else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
