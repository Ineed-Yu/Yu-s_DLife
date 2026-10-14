#!/usr/bin/env python3
"""ピンボードの質感素材（コルク・木枠）を作るスクリプト。

外部の素材サイトを使わず、乱数から質感を描いて assets/textures/ に保存します。
どれも上下左右につなぎ目なく並べられる（タイル状に敷き詰められる）画像です。

  assets/textures/cork.webp        … コルク（粒の大きさ・色むら・すき間の影）
  assets/textures/wood-h.webp      … 木枠の上下用（木目が横向き）
  assets/textures/wood-v.webp      … 木枠の左右用（木目が縦向き）

使い方:  python3 tools/make_textures.py
（乱数の種を固定しているので、何度実行しても同じ画像になります）
必要なもの: Python 3、Pillow、numpy、scipy
"""
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.spatial import cKDTree

OUT = Path(__file__).resolve().parent.parent / "assets" / "textures"
rng = np.random.default_rng(321)


def periodic_noise(size, scale, seed, stretch=1.0):
    """周期的な（つなぎ目のない）なめらかなノイズ。scale が大きいほど大きなむら。
    stretch > 1 にすると横方向に長く伸びたむらになる（木目用）。"""
    r = np.random.default_rng(seed)
    white = r.standard_normal((size, size))
    f = np.fft.fftfreq(size)
    fx, fy = np.meshgrid(f, f)
    radius = np.sqrt((fx * stretch) ** 2 + fy ** 2)
    spectrum = np.fft.fft2(white) * np.exp(-(radius * scale) ** 2)
    n = np.real(np.fft.ifft2(spectrum))
    return (n - n.mean()) / (n.std() + 1e-9)


def cork(size=512):
    # 1) 粒（ボロノイ分割）。周期的にするため周囲8方向に点を複製して最近傍を探す
    # 細かい粒を中心に、ところどころ大きめの粒を混ぜる
    small, large = 15000, 900
    pts = np.concatenate([rng.random((small, 2)), rng.random((large, 2))]) * size
    count = small + large
    tiles = np.concatenate([pts + [dx * size, dy * size] for dx in (-1, 0, 1) for dy in (-1, 0, 1)])
    ids = np.tile(np.arange(count), 9)
    tree = cKDTree(tiles)
    yy, xx = np.mgrid[0:size, 0:size]
    query = np.stack([xx.ravel() + 0.5, yy.ravel() + 0.5], axis=1)
    dist, idx = tree.query(query, k=2)
    cell = ids[idx[:, 0]].reshape(size, size)
    edge = (dist[:, 1] - dist[:, 0]).reshape(size, size)

    # 2) 粒ごとの明るさ・色み（黄みの強い粒、焦げた粒が混ざる）
    tone = rng.normal(0, 0.8, count)
    warm = rng.normal(0, 1, count)
    burnt = rng.random(count) < 0.08
    t = tone[cell]
    w = warm[cell]

    base = np.array([186, 138, 88], dtype=float)       # コルクの地の色
    img = np.empty((size, size, 3))
    img[..., 0] = base[0] + t * 16 + w * 6
    img[..., 1] = base[1] + t * 13 + w * 2
    img[..., 2] = base[2] + t * 10 - w * 6
    img[burnt[cell]] *= 0.72                            # 焦げ茶の粒

    # 3) 粒のすき間を暗く（くぼみの影）、粒の中に細かいざらつき
    crevice = np.clip(1 - edge / 0.9, 0, 1) ** 2
    img *= (1 - 0.30 * crevice)[..., None]
    img *= (1 + 0.05 * periodic_noise(size, 2, 11))[..., None]
    img *= (1 + 0.06 * periodic_noise(size, 40, 12))[..., None]   # 大きな色むら

    # 4) ところどころの深い穴
    holes = rng.random(count) < 0.02
    img[holes[cell] & (edge > 0.8)] *= 0.6
    # 粒の中の細かい気泡（小さな暗い点）
    pores = periodic_noise(size, 0.8, 13)
    img *= (1 - 0.18 * np.clip(pores - 1.8, 0, 1.5))[..., None]
    im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))
    # 粒の輪郭がくっきりしすぎないよう、ごくわずかにぼかす
    from PIL import ImageFilter
    return im.filter(ImageFilter.GaussianBlur(0.45))


def wood(size=512, horizontal=True):
    # 年輪のような細い縞 + 縞のゆらぎ + 節のない落ち着いたウォールナット
    y = np.arange(size)[:, None] * np.ones((1, size))
    # 横に長く伸びたゆらぎで、まっすぐな木目にする
    warp = periodic_noise(size, 40, 21, stretch=6) * 3 + periodic_noise(size, 10, 22, stretch=5) * 0.8
    # 縞が周期的になるよう、size の約数ぶんの本数にする
    stripes = np.sin(2 * np.pi * (y + warp) * 24 / size)
    fine = np.sin(2 * np.pi * (y + warp * 0.6) * 96 / size)
    pores = periodic_noise(size, 1.0, 23, stretch=8)
    pores = np.where(pores > 1.7, 1, 0) * 0.25
    streak = periodic_noise(size, 50, 24, stretch=10)

    v = 0.5 + 0.13 * stripes + 0.05 * fine + 0.16 * streak - pores
    base_dark = np.array([58, 33, 18], dtype=float)
    base_light = np.array([118, 74, 44], dtype=float)
    v = np.clip(v, 0, 1)[..., None]
    img = base_dark + (base_light - base_dark) * v
    # 木目を横長に伸ばす（横方向のむらを弱く）
    img = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))
    return img if horizontal else img.rotate(90, expand=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cork().save(OUT / "cork.webp", "WEBP", quality=82, method=6)
    wood(horizontal=True).save(OUT / "wood-h.webp", "WEBP", quality=82, method=6)
    wood(horizontal=False).save(OUT / "wood-v.webp", "WEBP", quality=82, method=6)
    for p in sorted(OUT.glob("*.webp")):
        print(f"作成: {p.relative_to(OUT.parent.parent)} ({p.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
