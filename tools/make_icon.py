# -*- coding: utf-8 -*-
"""生成打包用的图标 packaging/icon.ico。

画一个简洁的图标：深色圆角底 + 白色「字幕条」+ 一个小字体方块，
直观表达「字幕 + 字体装进同一个容器」。
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "packaging", "icon.ico")


def draw(size: int):
    from PIL import Image, ImageDraw

    scale = 8  # 先按大尺寸画再缩小，边缘更平滑
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 圆角底
    radius = int(s * 0.22)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=radius, fill=(21, 101, 192, 255))

    # 字幕条（三条，模拟字幕轨）
    bar_h = int(s * 0.085)
    bar_r = bar_h // 2
    left = int(s * 0.18)
    for i, frac in enumerate((0.60, 0.46, 0.34)):
        top = int(s * (0.30 + i * 0.155))
        right = left + int(s * frac)
        d.rounded_rectangle([left, top, right, top + bar_h], radius=bar_r,
                            fill=(255, 255, 255, 255))

    # 字体方块（右下角的“附件”）
    box = int(s * 0.30)
    bx = s - box - int(s * 0.14)
    by = s - box - int(s * 0.13)
    d.rounded_rectangle([bx, by, bx + box, by + box], radius=int(box * 0.22),
                        fill=(255, 214, 102, 255))
    # 方块里放一个 "A"，表示字体
    try:
        from PIL import ImageFont

        font = None
        for cand in ("arialbd.ttf", "arial.ttf", "segoeuib.ttf", "msyhbd.ttc"):
            try:
                font = ImageFont.truetype(cand, int(box * 0.72))
                break
            except Exception:
                continue
        if font is not None:
            text = "A"
            tb = d.textbbox((0, 0), text, font=font)
            d.text((bx + (box - (tb[2] - tb[0])) / 2 - tb[0],
                    by + (box - (tb[3] - tb[1])) / 2 - tb[1]),
                   text, font=font, fill=(38, 50, 56, 255))
    except Exception:
        pass

    return img.resize((size, size), Image.LANCZOS)


def main() -> int:
    try:
        from PIL import Image
    except ImportError:
        print("需要 Pillow 才能生成图标：pip install pillow", file=sys.stderr)
        return 1

    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [draw(n) for n in sizes]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    images[-1].save(OUT, format="ICO", sizes=[(n, n) for n in sizes])
    print("已生成:", OUT, "(%.1f KB)" % (os.path.getsize(OUT) / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
