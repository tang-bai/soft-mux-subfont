# -*- coding: utf-8 -*-
"""SubFontMKV —— 把外挂字幕与字体软封装进 MKV。

在 DYY-Studio/AddSubFontMKV_py（Apache-2.0）的思路基础上重写：
字体子集化 + 字体名改写（CRC32 后缀），字幕成为可开关的软字幕轨，
字体作为 attachment 内嵌。
"""

__version__ = "1.0.0"
__all__ = ["__version__"]
