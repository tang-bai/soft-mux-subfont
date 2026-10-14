# -*- coding: utf-8 -*-
"""生成用于测试的合成字体（不依赖系统字体，结果可复现）。

用法（在项目根目录执行）:
    python tools/make_test_fonts.py
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_DIR = os.path.join(ROOT, "test-assets", "fonts")

def build(path, family, style, chars, weight):
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    order = [".notdef"]
    cmap = {}
    for c in chars:
        name = "uni%04X" % ord(c)
        if name not in order:
            order.append(name)
        cmap[ord(c)] = name
    order.append("space")
    cmap[0x20] = "space"

    def box(pen, size=500):
        pen.moveTo((40, 0)); pen.lineTo((40, 700)); pen.lineTo((40 + size, 700))
        pen.lineTo((40 + size, 0)); pen.closePath()

    glyphs = {}
    pen = TTGlyphPen(None); glyphs[".notdef"] = pen.glyph()
    for name in order[1:]:
        pen = TTGlyphPen(None)
        if name == "space":
            glyphs[name] = pen.glyph()
            continue
        if "Bold" in style:
            box(pen, 520)
        else:
            box(pen, 500)
        glyphs[name] = pen.glyph()

    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics({n: (620, 40) for n in order})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": family, "styleName": style,
                       "psName": (family + "-" + style).replace(" ", "")})
    fb.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800,
                usWinDescent=200, usWeightClass=weight)
    fb.setupPost()
    # fontTools 会抱怨 created 太小；显式写成当前时间（Mac 纪元起算）
    import time
    stamp = int(time.time()) + 2082844800
    fb.font["head"].created = stamp
    fb.font["head"].modified = stamp
    fb.save(path)
    print("built", path, "glyphs:", len(order))


CJK = "你好世界字幕测试字体中文日本語こんにちは"
LATIN = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 !?,.:;'-()[]"

os.makedirs(FONT_DIR, exist_ok=True)
build(os.path.join(FONT_DIR, "SubFontTestSans-Regular.ttf"), "SubFontTest Sans", "Regular", LATIN, 400)
build(os.path.join(FONT_DIR, "SubFontTestSans-Bold.ttf"), "SubFontTest Sans", "Bold", LATIN, 700)
build(os.path.join(FONT_DIR, "SubFontTestCJK-Regular.ttf"), "SubFontTest CJK", "Regular", CJK + LATIN, 400)
print("OK")
