# -*- coding: utf-8 -*-
"""建立回归测试素材：批量目录、TTC 集合字体、缺字体/缺字幕等边界情况。

用法（在项目根目录执行，需先有 test-assets/Show EP01.mkv）:
    python tools/make_test_fonts.py
    python tools/make_test_assets.py
"""
import os
import shutil
import sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fontTools.ttLib import TTCollection

BATCH = os.path.join(ROOT, "test-assets", "batch")
SRC_VIDEO = os.path.join(ROOT, "test-assets", "Show EP01.mkv")
FONTS = os.path.join(ROOT, "test-assets", "fonts")

shutil.rmtree(BATCH, ignore_errors=True)
os.makedirs(os.path.join(BATCH, "fonts"), exist_ok=True)
os.makedirs(os.path.join(BATCH, "subs"), exist_ok=True)

YAHEI = "SubFontTest Sans"
CJK = "SubFontTest CJK"

HEAD = """[Script Info]
Title: {title}
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, Bold, Italic, Spacing, BorderStyle, Outline, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},44,&H00FFFFFF,{bold},0,0,1,2,2,10,10,10,1
{extra}
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
{events}
"""


def write_ass(path, title, font, bold, events, extra=""):
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(HEAD.format(title=title, font=font, bold=bold, events=events, extra=extra))


# 1) EP01 两条字幕
write_ass(os.path.join(BATCH, "Show EP01.chs.ass"), "EP01", YAHEI, -1,
          "Dialogue: 0,0:00:00.50,0:00:02.00,Default,,0,0,0,,Hello EP01 CHS!")
write_ass(os.path.join(BATCH, "Show EP01.jpn.ass"), "EP01 JPN", CJK, 0,
          "Dialogue: 0,0:00:00.60,0:00:02.10,Default,,0,0,0,,こんにちは世界")

# 2) EP02：字幕放到 subs/ 子目录，用 --sub-dir 找到
write_ass(os.path.join(BATCH, "subs", "Show EP02.chs.ass"), "EP02", CJK, 0,
          "Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,你好 EP02")

# 3) 缺字幕的视频（应被跳过）
# 4) 引用了不存在字体的视频（应告警但仍封装）
write_ass(os.path.join(BATCH, "MissingFont.chs.ass"), "MissingFont", "GhostFont NoSuch", 0,
          "Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,ABC ghost font")

for name in ("Show EP01.mkv", "Show EP02.mkv", "NoSubtitle.mkv", "MissingFont.mkv"):
    shutil.copy2(SRC_VIDEO, os.path.join(BATCH, name))

# 5) 把独立的 TTF 也放进 batch/fonts，作为常规来源
for name in ("SubFontTestSans-Regular.ttf", "SubFontTestSans-Bold.ttf",
             "SubFontTestCJK-Regular.ttf"):
    shutil.copy2(os.path.join(FONTS, name), os.path.join(BATCH, "fonts", name))

# 6) TTC 集合字体：一个文件里两个 face，用独立的家族名以便单独验证
def build_ttc_face(family, style, chars, weight):
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    import time

    order = [".notdef", "space"]
    cmap = {0x20: "space"}
    for c in chars:
        n = "uni%04X" % ord(c)
        if n not in order:
            order.append(n)
        cmap[ord(c)] = n

    glyphs = {}
    pen = TTGlyphPen(None); glyphs[".notdef"] = pen.glyph()
    pen = TTGlyphPen(None); glyphs["space"] = pen.glyph()
    for n in order[2:]:
        pen = TTGlyphPen(None)
        w = 520 if "Bold" in style else 500
        pen.moveTo((40, 0)); pen.lineTo((40, 700)); pen.lineTo((40 + w, 700)); pen.lineTo((40 + w, 0))
        pen.closePath()
        glyphs[n] = pen.glyph()
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics({n: (620, 40) for n in order})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": family, "styleName": style,
                       "psName": (family + style).replace(" ", "")})
    fb.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800,
                usWinDescent=200, usWeightClass=weight)
    fb.setupPost()
    stamp = int(time.time()) + 2082844800
    fb.font["head"].created = stamp
    fb.font["head"].modified = stamp
    return fb.font


TTC_FAMILY = "SubFontTest TTC"
face_reg = build_ttc_face(TTC_FAMILY, "Regular", "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 !,.", 400)
face_bold = build_ttc_face(TTC_FAMILY, "Bold", "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 !,.", 700)
ttc_path = os.path.join(BATCH, "fonts", "SubFontTestCollection.ttc")
collection = TTCollection()
collection.fonts = [face_reg, face_bold]
collection.save(ttc_path)
face_reg.close(); face_bold.close()
print("TTC faces:", len(TTCollection(ttc_path).fonts), "->", ttc_path)

# 7) 用 TTC 家族名的视频
write_ass(os.path.join(BATCH, "TTC.chs.ass"), "TTC", TTC_FAMILY, -1,
          "Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,TTC face Bold ABC")
shutil.copy2(SRC_VIDEO, os.path.join(BATCH, "TTC.mkv"))

print("batch 素材就绪:")
for root, dirs, files in os.walk(BATCH):
    for f in sorted(files):
        print("  ", os.path.relpath(os.path.join(root, f), ROOT))
