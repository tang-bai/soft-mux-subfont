# -*- coding: utf-8 -*-
"""字体索引、匹配、子集化与内部名称改写。

思路沿用 DYY-Studio/AddSubFontMKV_py：把字体内部名称改成
「原字体名.CRC32」，并同步改写 ASS 里引用的字体名，从而避免播放器
误用系统里同名的完整字体。
"""
from __future__ import annotations

import os
import re
import zlib
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .log import get_logger

log = get_logger("fonts")

#: 可被索引的字体扩展名
FONT_EXTENSIONS = (".ttf", ".otf", ".ttc", ".otc")

#: 作为 attachment 内嵌时的 MIME 类型
FONT_MIME = {
    ".ttf": "application/x-truetype-font",
    ".ttc": "application/x-truetype-font",
    ".otf": "application/vnd.ms-opentype",
    ".otc": "application/vnd.ms-opentype",
}

#: 参与改名的字体名 ID：1=Family 3=UniqueID 4=FullName 6=PostScript
NAME_ID_RENAME = (1, 3, 4, 6)

#: PostScript 名允许的字符
RE_PS_SAFE = re.compile(r"[^A-Za-z0-9.\-_]")


def system_font_dirs() -> List[str]:
    """返回当前系统的字体目录（不读取注册表，跨平台）。"""
    import sys

    dirs: List[str] = []
    if os.name == "nt":
        win = os.environ.get("WINDIR", r"C:\Windows")
        dirs.append(os.path.join(win, "Fonts"))
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.append(os.path.join(local, "Microsoft", "Windows", "Fonts"))
    elif sys.platform == "darwin":
        dirs.extend(["/System/Library/Fonts", "/Library/Fonts",
                     os.path.expanduser("~/Library/Fonts")])
    else:
        dirs.extend(["/usr/share/fonts", "/usr/local/share/fonts",
                     os.path.expanduser("~/.fonts"),
                     os.path.expanduser("~/.local/share/fonts")])
    seen: Set[str] = set()
    out: List[str] = []
    for d in dirs:
        real = os.path.abspath(d)
        if os.path.isdir(real) and real.lower() not in seen:
            seen.add(real.lower())
            out.append(real)
    return out


def _iter_font_files(directory: str) -> Iterable[str]:
    try:
        entries = sorted(os.scandir(directory), key=lambda e: e.name.lower())
    except (PermissionError, FileNotFoundError, OSError):
        return
    for entry in entries:
        try:
            if entry.is_file(follow_symlinks=False) and entry.name.lower().endswith(FONT_EXTENSIONS):
                yield entry.path
        except OSError:
            continue


class Face(object):
    """TTC/OTC 里的一个 face（普通字体则只有一个 face）。"""

    __slots__ = ("path", "index", "names", "style_names", "family_names", "weight", "italic")

    def __init__(self, path: str, index: int) -> None:
        self.path = path
        self.index = index
        self.names: Dict[str, str] = {}          # 小写名 -> 规范名
        self.style_names: Set[str] = set()
        self.family_names: Set[str] = set()
        self.weight: Optional[int] = None
        self.italic: Optional[int] = None

    @property
    def key(self) -> Tuple[str, int]:
        return (self.path, self.index)

    def __repr__(self) -> str:  # pragma: no cover
        return "<Face {0}#{1} {2}>".format(os.path.basename(self.path), self.index,
                                           ",".join(sorted(self.names.values()))[:60])


def _decode_name(record) -> str:
    try:
        return record.toUnicode().strip()
    except Exception:
        try:
            return str(record)
        except Exception:
            return ""


def read_face_names(font, face: Face) -> None:
    """从已打开的 TTFont 里读取可用于匹配的名称。"""
    try:
        name_table = font["name"]
    except KeyError:
        return
    family: Set[str] = set()
    style: Set[str] = set()
    for record in name_table.names:
        text = _decode_name(record)
        if not text:
            continue
        if record.nameID in (1, 16):        # Family / Typographic Family
            family.add(text)
        elif record.nameID in (2, 17):      # Subfamily / Typographic Subfamily
            style.add(text)
        if record.nameID in (1, 2, 4, 6, 16, 17):
            face.names.setdefault(text.lower(), text)
    face.family_names = family
    face.style_names = style
    try:
        os2 = font["OS/2"]
        face.weight = getattr(os2, "usWeightClass", None)
        if getattr(os2, "fsSelection", 0) & 1:
            face.italic = 1
    except Exception:
        pass
    if face.italic is None:
        try:
            if font["head"].macStyle & 2:
                face.italic = 1
        except Exception:
            pass


class FaceSet(object):
    """一批已打开的 face，以及需要在读完后统一关闭的底层 reader。

    TTC/OTC 里的多个 face 共用一个文件 reader，逐个 face 关闭会把
    其它 face 也一起弄坏（表现为 seek of closed file），因此统一收口。
    """

    __slots__ = ("fonts", "reader")

    def __init__(self, fonts, reader=None) -> None:
        self.fonts = list(fonts)
        self.reader = reader

    def close(self) -> None:
        for font in self.fonts:
            try:
                font.close()
            except Exception:
                pass
        if self.reader is not None:
            try:
                self.reader.close()
            except Exception:
                pass
        self.reader = None

    def __enter__(self) -> "FaceSet":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


def open_faces(path: str) -> FaceSet:
    """打开字体文件，返回 FaceSet（TTC/OTC 会含多个 face）。"""
    from fontTools.ttLib import TTFont, TTCollection

    if path.lower().endswith((".ttc", ".otc")):
        try:
            collection = TTCollection(path, lazy=True)
            return FaceSet(collection.fonts, getattr(collection, "reader", None))
        except Exception as exc:
            log.debug("按集合打开失败，退回单字体: %s (%s)", path, exc)
    try:
        return FaceSet([TTFont(path, fontNumber=0, lazy=True)])
    except Exception as exc:
        log.debug("打开字体失败 %s: %s", path, exc)
        return FaceSet([])


class FontIndex(object):
    """字体名 -> Face 的索引，同时支持「字体族 + 粗斜体」匹配。"""

    def __init__(self) -> None:
        self.faces: Dict[Tuple[str, int], Face] = {}
        self._by_name: Dict[str, List[Face]] = {}
        self._families: Dict[str, List[Face]] = {}

    # -- 构建 ---------------------------------------------------------------
    def add_directory(self, directory: str, recursive: bool = False) -> int:
        count = 0
        pending = [directory]
        while pending:
            current = pending.pop()
            for path in _iter_font_files(current):
                count += self.add_file(path)
            if recursive:
                try:
                    for entry in os.scandir(current):
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(entry.path)
                except OSError:
                    pass
        return count

    def add_file(self, path: str) -> int:
        real = os.path.abspath(path)
        added = 0
        # 先把所有 face 的名称读出来，再统一关闭底层 reader
        with open_faces(real) as face_set:
            faces: List[Face] = []
            for index, font in enumerate(face_set.fonts):
                face = Face(real, index)
                read_face_names(font, face)
                if face.names:
                    faces.append(face)
        for face in faces:
            self.faces[face.key] = face
            for low, _canonical in face.names.items():
                self._by_name.setdefault(low, []).append(face)
                squeezed = re.sub(r"\s+", "", low)
                if squeezed != low:
                    self._by_name.setdefault(squeezed, []).append(face)
            for family in face.family_names:
                self._families.setdefault(family.lower(), []).append(face)
            added += 1
        return added

    # -- 查询 ---------------------------------------------------------------
    def __len__(self) -> int:
        return len(self.faces)

    @property
    def name_count(self) -> int:
        return len(self._by_name)

    def lookup(self, name: str) -> Optional[Face]:
        """按字体名精确查找（忽略大小写与多余空格）。"""
        if not name:
            return None
        key = name.strip().lower()
        candidates = self._by_name.get(key)
        if not candidates:
            candidates = self._by_name.get(re.sub(r"\s+", "", key))
        return candidates[0] if candidates else None

    def match(self, name: str, bold: bool = False, italic: bool = False) -> Optional[Face]:
        """按 ASS 样式里的 Fontname（含 Bold/Italic 标志）匹配最合适的 face。"""
        base = name.lstrip("@").strip()
        if not base:
            return None
        face = self.lookup(base)
        if face is not None and self._style_matches(face, bold, italic):
            return face

        # 退一步：把 ASS 字体名按「族名 + 样式后缀」拆开再找
        family, suffix_bold, suffix_italic = split_style_suffix(base)
        need_bold = bold or suffix_bold
        need_italic = italic or suffix_italic
        pool = self._families.get(family.lower())
        if not pool:
            pool = self._by_name.get(family.lower())
        if not pool and face is not None:
            pool = [face]
        if not pool:
            return None
        return min(pool, key=lambda f: self._distance(f, need_bold, need_italic))

    @staticmethod
    def _style_matches(face: Face, bold: bool, italic: bool) -> bool:
        if bool(italic) != (face.italic == 1):
            return False
        weight = face.weight if face.weight is not None else 400
        if bold and weight < 600:
            return False
        if not bold and weight >= 600:
            return False
        return True

    @staticmethod
    def _distance(face: Face, bold: bool, italic: bool) -> int:
        weight = face.weight if face.weight is not None else 400
        want = 700 if bold else 400
        return abs(weight - want) + (0 if (face.italic == 1) == bool(italic) else 100)


def split_style_suffix(name: str) -> Tuple[str, bool, bool]:
    """把字体名里的粗体/斜体后缀拆出来。

    例如 "Agency FB Bold Italic" -> ("Agency FB", True, True)，
    "NotoSansSC-Bold" -> ("NotoSansSC", True, False)。
    """
    tokens = {
        "bold": "b", "black": "b", "heavy": "b", "semibold": "b", "demibold": "b",
        "extrabold": "b", "ultrabold": "b", "ultra": "b", "medium": "n",
        "italic": "i", "oblique": "i",
        "light": "n", "regular": "n", "narrow": "n", "condensed": "n",
        "thin": "n", "book": "n", "roman": "n", "normal": "n",
    }
    suffix = name
    bold = False
    italic = False
    changed = True
    while changed and suffix:
        changed = False
        low = suffix.lower().rstrip()
        for token, flag in sorted(tokens.items(), key=lambda kv: -len(kv[0])):
            for sep in (" ", "-", "_"):
                full = sep + token
                if len(low) > len(full) and low.endswith(full):
                    suffix = suffix[: len(suffix) - len(full)]
                    bold = bold or flag == "b"
                    italic = italic or flag == "i"
                    changed = True
                    break
            if changed:
                break
    family = suffix.strip() or name.strip()
    return family, bold, italic


def crc32_of_file(path: str) -> str:
    """计算文件的 CRC32，返回 8 位大写十六进制字符串。"""
    value = 0
    with open(path, "rb") as fp:
        while True:
            chunk = fp.read(1 << 20)
            if not chunk:
                break
            value = zlib.crc32(chunk, value)
    return "{0:08X}".format(value & 0xFFFFFFFF)


def sanitize_filename(name: str) -> str:
    """把字体名转成安全的文件名（保留中文）。"""
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", name).strip().strip(".")
    return cleaned or "font"


def sanitize_postscript(name: str) -> str:
    return RE_PS_SAFE.sub("", name) or "Font"


# --------------------------------------------------------------------------
# 名称改写
# --------------------------------------------------------------------------
def rename_records(font, new_name: str) -> None:
    """把字体内部名称改成 new_name；版权等无关名称保持原样。"""
    try:
        table = font["name"]
    except KeyError:
        return
    ps_name = sanitize_postscript(new_name)
    for record in list(table.names):
        if record.nameID not in NAME_ID_RENAME:
            continue
        value = ps_name if record.nameID == 6 else new_name
        try:
            record.string = value.encode(record.getEncoding())
        except (UnicodeEncodeError, LookupError):
            try:
                record.string = value.encode("utf-16-be")
            except Exception:
                pass


# --------------------------------------------------------------------------
# 子集化
# --------------------------------------------------------------------------
class SubsetError(Exception):
    """子集化失败。"""


#: 可以被安全丢弃的表。
#: 这些表只影响「在什么字号下启用网格适配/灰度」之类的渲染提示，
#: 与字形轮廓、cmap 映射、样式名称全都无关；但某些字体（尤其是日文商用字体）
#: 会把它们写坏 —— 典型症状就是 fontTools 反序列化时抛断言
#: ("too much data" / "not enough data")，导致整个字体读不进来。
#: 丢掉一个表换来「字幕能正常显示」，比整个字体子集化失败划算得多。
_SANITIZABLE_TABLES = ("gasp", "VDMX", "LTSH", "hdmx", "DSIG", "PADDING")


def _broken_optional_tables(font) -> List[str]:
    """探测哪些「可选表」展开会失败。

    注意 fontTools 的 lazy=False 只是把表读进内存、并不真正反序列化，
    所以不能靠「打开是否报错」来判断 —— 必须逐个访问才会暴露问题。
    这正是 "too much data" 出现在子集化阶段、而不是加载阶段的原因。
    """
    broken: List[str] = []
    for tag in _SANITIZABLE_TABLES:
        if tag not in font:
            continue
        try:
            font[tag]  # 触发展开
        except Exception:
            broken.append(tag)
    return broken


def load_font_safely(src_path: str, font_number: int):
    """打开字体，并丢掉那些「展开就会报错」的可选表。

    返回 (TTFont, 被丢弃的表名列表)。

    真实案例：某些日文商用字体（如 Reishoreiryu）的 gasp 表头部声明的区间数
    少于实际数据，fontTools 反序列化到结尾发现还有剩余字节，直接
    assert not data, "too much data" —— 于是整个字体子集化失败。
    gasp 只影响「什么字号下启用网格适配/灰度」这类渲染提示，丢掉它不影响
    字形、cmap 与样式名称，换来的是这套字幕能正常显示。
    """
    from fontTools.ttLib import TTFont

    font = TTFont(src_path, fontNumber=font_number, lazy=False)

    dropped: List[str] = []
    for tag in _broken_optional_tables(font):
        try:
            del font[tag]
            dropped.append(tag)
        except Exception:
            pass

    # reader 里也要摘掉，否则后续 save/ensureDecompiled 可能再次碰到它
    for tag in dropped:
        try:
            if tag in font.reader.tables:
                del font.reader.tables[tag]
        except Exception:
            pass

    return font, dropped


def sfnt_extension(font) -> str:
    """单个 sfnt 字体应使用的扩展名（不是集合格式）。

    TTC/OTC 里的一个 face 导出后就是普通 sfnt，若继续叫 .ttc，
    播放器可能解析失败，所以按 CFF/glyf 分别写成 .otf/.ttf。
    """
    version = getattr(font, "sfntVersion", None)
    if version in ("OTTO", b"OTTO"):
        return ".otf"
    return ".ttf"


def _subset_options():
    """子集化参数。保留名称、cmap 与布局特性，尽量贴近原字体的显示效果。"""
    from fontTools.subset import Options

    options = Options()
    options.name_IDs = list(range(0, 26))
    options.name_legacy = True
    options.name_languages = ["*"]
    options.layout_features = ["*"]
    options.glyph_names = True
    options.legacy_cmap = True
    options.passthrough_tables = True
    options.notdef_outline = True
    options.recalc_bounds = True
    options.recalc_timestamp = False
    options.drop_tables = []
    return options


def _run_subset(font, wanted: str, temp_path: str) -> str:
    """对已打开的字体做一次子集化并保存，返回输出用的扩展名。"""
    from fontTools.subset import Subsetter

    subsetter = Subsetter(options=_subset_options())
    subsetter.populate(text=wanted)
    subsetter.subset(font)

    if not [g for g in font.getGlyphOrder() if g != ".notdef"]:
        raise SubsetError("子集化后没有留下任何字形")
    ext = sfnt_extension(font)
    font.save(temp_path)
    return ext


def _finalize(temp_path: str, output_path: str, ext: str) -> Tuple[str, str]:
    """算 CRC 定名，并把字体内部名称改成「原名.CRC32」。"""
    from fontTools.ttLib import TTFont

    if not os.path.exists(temp_path) or os.path.getsize(temp_path) == 0:
        raise SubsetError("子集化输出为空")

    # 先算 CRC 得到最终文件名，再改名，保证文件名里的 CRC 与内容一致
    crc = crc32_of_file(temp_path)
    stem = os.path.splitext(output_path)[0]
    final_path = "{0}.{1}{2}".format(stem, crc, ext)
    if os.path.exists(final_path):
        os.remove(final_path)
    os.replace(temp_path, final_path)

    subset = TTFont(final_path, lazy=False)
    try:
        rename_records(subset, os.path.basename(stem) + "." + crc)
        subset.save(final_path)
    except Exception as exc:
        log.debug("改写字体内部名称失败（保留子集但名称未改）: %s", exc)
    finally:
        try:
            subset.close()
        except Exception:
            pass
    return final_path, crc


def subset_font(
    src_path: str,
    font_number: int,
    output_path: str,
    chars: str,
    extra_chars: str = "",
) -> Tuple[str, str]:
    """把字体子集化并改名，返回 (最终输出路径, CRC32)。

    最终文件名形如 AgencyFB-Bold.302BD68C.ttf（扩展名只出现一次），
    字体内部的 Family/FullName/UniqueID/PostScript 名称同样被改成
    AgencyFB-Bold.302BD68C，因此 ASS 里引用这个名字就一定会命中内嵌字体。

    对「个别表损坏」的字体有容错：先丢弃已知会报错的可选表；如果还是失败，
    就把全部可选表都丢掉再试一次，尽量保住字形与 cmap，而不是直接放弃。
    """
    from fontTools.ttLib import TTFont

    wanted = _dedupe(chars + extra_chars)
    if not wanted:
        raise SubsetError("没有需要子集化的字符")

    directory = os.path.dirname(os.path.abspath(output_path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory, exist_ok=True)
    temp_path = output_path + ".tmp"
    if os.path.exists(temp_path):
        os.remove(temp_path)

    # -- 第一次尝试：正常加载，只丢「确实展开失败」的可选表 --
    font, dropped = load_font_safely(src_path, font_number)
    try:
        if dropped:
            log.warning("字体 %s 的表 %s 结构异常，已丢弃后继续子集化。",
                        os.path.basename(src_path), "/".join(dropped))
        ext = _run_subset(font, wanted, temp_path)
    except SubsetError:
        raise
    except Exception as exc:
        first_error = exc
        log.debug("字体 %s 首次子集化失败: %s", os.path.basename(src_path), exc)
        # -- 第二次尝试：把全部可选表都丢掉 --
        try:
            font2 = TTFont(src_path, fontNumber=font_number, lazy=False)
            for tag in _SANITIZABLE_TABLES:
                try:
                    if tag in font2:
                        del font2[tag]
                    if tag in font2.reader.tables:
                        del font2.reader.tables[tag]
                except Exception:
                    pass
            try:
                ext = _run_subset(font2, wanted, temp_path)
            finally:
                try:
                    font2.close()
                except Exception:
                    pass
            log.warning("字体 %s 首次子集化失败（%s），丢弃全部可选表后成功。",
                        os.path.basename(src_path), first_error)
        except Exception:
            raise SubsetError("子集化失败: {0}".format(first_error))
    finally:
        try:
            font.close()
        except Exception:
            pass

    return _finalize(temp_path, output_path, ext)


def extract_face(src_path: str, font_number: int, output_path: str) -> str:
    """把 TTC/OTC 里的单个 face 导出成独立字体文件（不做子集化）。"""
    from fontTools.ttLib import TTFont

    font = TTFont(src_path, fontNumber=font_number, lazy=False)
    try:
        stem = os.path.splitext(output_path)[0]
        final_path = stem + sfnt_extension(font)
        directory = os.path.dirname(os.path.abspath(final_path))
        if directory and not os.path.isdir(directory):
            os.makedirs(directory, exist_ok=True)
        font.save(final_path)
    finally:
        try:
            font.close()
        except Exception:
            pass
    return final_path


def _dedupe(chars: str) -> str:
    return "".join(sorted(set(chars)))


def missing_glyphs(src_path: str, font_number: int, chars: str) -> str:
    """返回字体里缺失的字符（用于子集化前自检）。"""
    from fontTools.ttLib import TTFont

    try:
        font = TTFont(src_path, fontNumber=font_number, lazy=True)
    except Exception as exc:
        log.debug("打开字体失败 %s: %s", src_path, exc)
        return ""
    try:
        cmap: Dict[int, str] = {}
        tables = font["cmap"].tables
        for table in tables:
            if table.isUnicode() and len(table.cmap) > len(cmap):
                cmap = table.cmap
        if not cmap:
            for table in tables:
                if len(table.cmap) > len(cmap):
                    cmap = table.cmap
        if not cmap:
            return ""
        return "".join(sorted({c for c in chars if ord(c) not in cmap}))
    except Exception as exc:
        log.debug("读取 cmap 失败 %s: %s", src_path, exc)
        return ""
    finally:
        try:
            font.close()
        except Exception:
            pass


def font_mime_type(path: str) -> str:
    return FONT_MIME.get(os.path.splitext(path)[1].lower(), "application/octet-stream")


#: 额外内嵌的字符：数字与拉丁字母，避免子集化后切到内嵌字体时缺字
DEFAULT_EXTRA_CHARS = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"