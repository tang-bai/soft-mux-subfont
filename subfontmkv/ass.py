# -*- coding: utf-8 -*-
"""SSA/ASS 字幕的解析、字体需求分析与字体名改写。

解析时保留「原始行号」与行尾符，改写只动必须动的字段，
其余内容（注释、特效标签、Dialogue 文本）原样保留。
"""
from __future__ import annotations

import codecs
import os
import re
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

# --------------------------------------------------------------------------
# 段落标记
# --------------------------------------------------------------------------
RE_SCRIPT_INFO = re.compile(r"^\[[Ss]cript\s+[Ii]nfo\]\s*$")
RE_STYLES = re.compile(r"^\[[Vv]4\+?\s*[Ss]tyles\]\s*$")
RE_EVENTS = re.compile(r"^\[[Ee]vents\]\s*$")

#: 子集化注释: ; Font Subset: <子集字体名> - <原始字体名>
RE_SUBSET_COMMENT = re.compile(
    r"^;\s*Font\s+Subset\s*:\s*(?P<new>.+?)\s*-\s*(?P<orig>.+?)\s*$",
    re.IGNORECASE,
)

#: 覆盖标签块 { ... }
RE_OVERRIDE = re.compile(r"\{[^}]*\}")
#: 覆盖标签内的单个标签（只关心会影响文字字体的标签；\\fn 与 \\r 的参数
#: 必须按「标签名 + 其余内容」切分，否则 \\rNote 会被贪婪地读成名为 rNote 的标签）
RE_TAG = re.compile(r"\\(fn|r|p)([^\\}]*)")

RE_FONT_TAG = re.compile(r"\\fn([^\\}]*)")

TEXT_EXTENSIONS = (".ass", ".ssa")


# --------------------------------------------------------------------------
# 编码
# --------------------------------------------------------------------------
def detect_encoding(raw: bytes) -> str:
    """确定字幕文本编码，优先使用 BOM。"""
    for bom, enc in (
        (codecs.BOM_UTF8, "utf-8-sig"),
        (codecs.BOM_UTF32_LE, "utf-32-le"),
        (codecs.BOM_UTF32_BE, "utf-32-be"),
        (codecs.BOM_UTF16_LE, "utf-16"),
        (codecs.BOM_UTF16_BE, "utf-16"),
    ):
        if raw.startswith(bom):
            return enc
    try:
        from charset_normalizer import from_bytes

        best = from_bytes(raw).best()
        if best is not None and best.encoding:
            return best.encoding
    except Exception:
        pass
    try:
        import chardet

        guess = chardet.detect(raw).get("encoding")
        if guess:
            return guess
    except Exception:
        pass
    return "utf-8"


def read_text(path: str) -> Tuple[str, str]:
    """读取字幕文本，返回 (文本, 实际使用的编码)。"""
    with open(path, "rb") as fp:
        raw = fp.read()
    enc = detect_encoding(raw)
    for candidate in (enc, "utf-8-sig", "utf-8", "gbk", "gb18030", "cp1252"):
        try:
            return raw.decode(candidate), candidate
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8"


# --------------------------------------------------------------------------
# 文本清理
# --------------------------------------------------------------------------
def _flag_true(value: str) -> bool:
    """解析 ASS 里表示「真」的写法：-1 / 1 / true / 700 等。"""
    text = (value or "").strip().lower()
    if text in ("-1", "1", "true", "yes"):
        return True
    if text in ("0", "false", "no", ""):
        return False
    try:
        return int(text) >= 600
    except ValueError:
        return False


def visible_text(fragment: str) -> str:
    """去掉特效标签与转义符，返回观众实际看到的字符。"""
    fragment = RE_OVERRIDE.sub("", fragment)
    fragment = fragment.replace("\\N", "")
    fragment = fragment.replace("\\n", "")
    fragment = fragment.replace("\\h", "\u00a0")
    return fragment


# --------------------------------------------------------------------------
# 数据结构
# --------------------------------------------------------------------------
class _Line(object):
    """一条可渲染的记录，保留行尾符。"""

    __slots__ = ("line_index", "prefix", "eol", "fields")

    def __init__(self, line_index: int, prefix: str, eol: str, fields: List[str]) -> None:
        self.line_index = line_index
        self.prefix = prefix
        self.eol = eol
        self.fields = fields

    def render(self) -> str:
        return self.prefix + ",".join(self.fields) + self.eol


class Style(_Line):
    __slots__ = ("name", "fontname", "bold", "italic")

    def __init__(self, line_index: int, prefix: str, eol: str, fields: List[str]) -> None:
        super().__init__(line_index, prefix, eol, fields)
        self.name = ""
        self.fontname = ""
        self.bold = False
        self.italic = False


class Event(_Line):
    __slots__ = ("text_index", "style_index", "style", "is_comment")

    def __init__(self, line_index: int, prefix: str, eol: str, fields: List[str],
                 text_index: int, style_index: int, is_comment: bool = False) -> None:
        super().__init__(line_index, prefix, eol, fields)
        self.text_index = text_index
        self.style_index = style_index
        self.style = ""
        self.is_comment = is_comment

    @property
    def text(self) -> str:
        return self.fields[self.text_index] if self.text_index < len(self.fields) else ""


class AssFile(object):
    """一个 SSA/ASS 文件。"""

    def __init__(self, path: str) -> None:
        self.path = path
        self.lines: List[str] = []
        self.encoding = "utf-8"
        self.script_info_index: Optional[int] = None
        self.styles_header_index: Optional[int] = None
        self.events_header_index: Optional[int] = None
        self.styles: List[Style] = []
        self.events: List[Event] = []
        self.name_pos: int = 0
        self.font_pos: int = 1
        self.recovered: Dict[str, str] = {}   # 子集字体名 -> 原始字体名
        self.subset_comment_lines: List[int] = []   # 上一次子集化留下的注释行号

    # -- 载入 ---------------------------------------------------------------
    @classmethod
    def load(cls, path: str) -> "AssFile":
        self = cls(path)
        text, enc = read_text(path)
        self.encoding = enc
        self.lines = text.splitlines(True)
        self.parse()
        return self

    @classmethod
    def from_string(cls, text: str, path: str = "<string>") -> "AssFile":
        self = cls(path)
        self.lines = text.splitlines(True)
        self.parse()
        return self

    # -- 解析 ---------------------------------------------------------------
    def parse(self) -> None:
        for i, raw in enumerate(self.lines):
            line = raw.rstrip("\r\n")
            if self.script_info_index is None and RE_SCRIPT_INFO.match(line):
                self.script_info_index = i
            elif self.styles_header_index is None and RE_STYLES.match(line):
                self.styles_header_index = i
            elif self.events_header_index is None and RE_EVENTS.match(line):
                self.events_header_index = i

        self._parse_subset_comments()
        self._parse_styles()
        self._parse_events()

    def _parse_subset_comments(self) -> None:
        if self.script_info_index is None:
            return
        for i in range(self.script_info_index + 1, len(self.lines)):
            stripped = self.lines[i].strip()
            if not stripped:
                continue
            if stripped.startswith("["):
                break
            low = stripped.lower()
            if low.startswith("; subset via") or low.startswith("; font subset"):
                self.subset_comment_lines.append(i)
            match = RE_SUBSET_COMMENT.match(stripped)
            if match:
                new_name = match.group("new").strip()
                orig_name = match.group("orig").strip()
                if new_name and orig_name and new_name != orig_name:
                    self.recovered[new_name] = orig_name

    def _split_line(self, index: int) -> Tuple[str, List[str], str]:
        raw = self.lines[index]
        body = raw.rstrip("\r\n")
        eol = raw[len(body):]
        head, sep, value = body.partition(":")
        lead = value[:len(value) - len(value.lstrip())]
        prefix = head + sep + lead if sep else head
        return prefix, [f.strip() for f in value.split(",")], eol

    def _find_format(self, start: int, limit: int) -> Tuple[Optional[List[str]], Optional[int]]:
        for i in range(start, min(limit, len(self.lines))):
            stripped = self.lines[i].strip()
            if not stripped or stripped.startswith(";") or stripped.startswith("!"):
                continue
            head, sep, value = self.lines[i].partition(":")
            if sep and head.strip().lower() == "format":
                return [f.strip() for f in value.split(",")], i
            return None, None
        return None, None

    @staticmethod
    def _index_of(fmt: Sequence[str], *names: str) -> int:
        for idx, field in enumerate(fmt):
            if field.lower().strip() in names:
                return idx
        return -1

    def _parse_styles(self) -> None:
        if self.styles_header_index is None:
            return
        fmt, fmt_index = self._find_format(self.styles_header_index + 1, len(self.lines))
        bold_at = italic_at = -1
        if fmt:
            name_at = self._index_of(fmt, "name")
            font_at = self._index_of(fmt, "fontname")
            bold_at = self._index_of(fmt, "bold")
            italic_at = self._index_of(fmt, "italic")
            if name_at >= 0:
                self.name_pos = name_at
            if font_at >= 0:
                self.font_pos = font_at
        start = (fmt_index + 1) if fmt_index is not None else (self.styles_header_index + 1)
        for i in range(start, len(self.lines)):
            stripped = self.lines[i].strip()
            if not stripped:
                continue
            if stripped.startswith("["):
                break
            head, sep, _ = self.lines[i].partition(":")
            if not sep or head.strip().lower() != "style":
                break
            prefix, fields, eol = self._split_line(i)
            style = Style(i, prefix, eol, fields)
            if self.name_pos < len(fields):
                style.name = fields[self.name_pos]
            if self.font_pos < len(fields):
                raw_name = fields[self.font_pos]
                style.fontname = raw_name.lstrip("@")
                if style.fontname in self.recovered:
                    # 上一次已被本工具子集化过：把字段也还原成原始字体名，
                    # 这样再改一次名仍然是「原名 -> 新名」，不会层层叠加。
                    style.fontname = self.recovered[style.fontname]
                    style.fields[self.font_pos] = (
                        ("@" if raw_name.startswith("@") else "") + style.fontname)
            if 0 <= bold_at < len(fields):
                style.bold = _flag_true(fields[bold_at])
            if 0 <= italic_at < len(fields):
                style.italic = _flag_true(fields[italic_at])
            self.styles.append(style)

    def _parse_events(self) -> None:
        if self.events_header_index is None:
            return
        fmt, fmt_index = self._find_format(self.events_header_index + 1, len(self.lines))
        text_index, style_index = 9, 3
        if fmt:
            at = self._index_of(fmt, "text")
            if at >= 0:
                text_index = at
            at = self._index_of(fmt, "style")
            if at >= 0:
                style_index = at
        start = (fmt_index + 1) if fmt_index is not None else (self.events_header_index + 1)
        for i in range(start, len(self.lines)):
            stripped = self.lines[i].strip()
            if not stripped:
                continue
            if stripped.startswith("["):
                break
            head, sep, _ = self.lines[i].partition(":")
            if not sep or head.strip().lower() not in ("dialogue", "comment"):
                continue
            prefix, fields, eol = self._split_n(i, text_index)
            event = Event(i, prefix, eol, fields, text_index, style_index,
                          is_comment=head.strip().lower() == "comment")
            if style_index < len(fields):
                event.style = fields[style_index].strip()
            self.events.append(event)

    def _split_n(self, index: int, text_index: int) -> Tuple[str, List[str], str]:
        """按 text_index 做受限分割，保证 Text 字段里的逗号不被切开。"""
        raw = self.lines[index]
        body = raw.rstrip("\r\n")
        eol = raw[len(body):]
        head, sep, value = body.partition(":")
        lead = value[:len(value) - len(value.lstrip())]
        prefix = head + sep + lead if sep else head
        fields = value.split(",", text_index)
        return prefix, [f.strip() for f in fields[:text_index]] + fields[text_index:], eol

    # -- 查询 ---------------------------------------------------------------
    def style_font_map(self) -> Dict[str, str]:
        return {s.name: s.fontname for s in self.styles if s.name}

    def style_chars(self) -> Dict[str, str]:
        """样式字体 -> 该字体实际需要显示的字符集合。

        会考虑 \\fn / \\r 对字体的覆盖，以及 \\p 绘图模式下不产生文字的情况。
        """
        style_fonts = self.style_font_map()
        needs: Dict[str, Set[str]] = {}

        def add(font: str, chars: Iterable[str]) -> None:
            if not font:
                return
            bucket = needs.setdefault(font, set())
            bucket.update(chars)

        for event in self.events:
            if event.is_comment or event.text_index >= len(event.fields):
                continue
            base_font = style_fonts.get(event.style, "")
            for font, chars in self._split_by_font(event.text, base_font, style_fonts):
                add(font, chars)
        return {k: "".join(sorted(v)) for k, v in needs.items() if v}

    def font_usage(self) -> Dict[Tuple[str, bool, bool], str]:
        """返回 {(字体名, 粗体, 斜体): 需要显示的字符}。

        \\fn / \\r 覆盖来的字体沿用所属样式的粗斜体标志（这也是字幕作者的本意）。
        """
        style_fonts = self.style_font_map()
        usage: Dict[Tuple[str, bool, bool], Set[str]] = {}
        for event in self.events:
            if event.is_comment or event.text_index >= len(event.fields):
                continue
            style = next((s for s in self.styles if s.name == event.style), None)
            base_font = style.fontname if style is not None else style_fonts.get(event.style, "")
            bold = style.bold if style is not None else False
            italic = style.italic if style is not None else False
            for font, chars in self._split_by_font(event.text, base_font, style_fonts):
                bucket = usage.setdefault((font, bold, italic), set())
                bucket.update(chars)
        return {k: "".join(sorted(v)) for k, v in usage.items() if v}

    def _split_by_font(
        self, text: str, base_font: str, style_fonts: Dict[str, str]
    ) -> List[Tuple[str, str]]:
        """把一条 Dialogue 文本按当前生效字体切成若干段。"""
        chunks: List[Tuple[str, str]] = []
        current = base_font
        drawing = False
        pos = 0
        buf: List[str] = []
        buf_drawing = False

        def flush() -> None:
            chunk = visible_text("".join(buf))
            if chunk and not buf_drawing:
                chunks.append((current, chunk))
            del buf[:]

        for match in RE_OVERRIDE.finditer(text):
            if text[pos:match.start()]:
                buf.append(text[pos:match.start()])
            pos = match.end()
            for tag in RE_TAG.finditer(match.group(0)):
                name = tag.group(1).lower()
                arg = tag.group(2).strip()
                if name == "fn":
                    flush()
                    if arg:
                        current = self.recovered.get(arg, arg)
                elif name == "r":
                    flush()
                    current = base_font if not arg else style_fonts.get(arg, base_font)
                elif name == "p":
                    # \\p 只在参数为数字时表示「进入/退出绘图模式」
                    if arg.lstrip("-").isdigit():
                        flush()
                        buf_drawing = drawing = int(arg) > 0
        if text[pos:]:
            buf.append(text[pos:])
        flush()
        return chunks

    # -- 改写 ---------------------------------------------------------------
    def apply_font_map(self, mapping: Dict[str, str]) -> List[str]:
        """把样式与 \\fn 中的字体名改成子集字体名，并在 Script Info 里留下还原注释。"""
        if not mapping:
            return []
        lowered = {k.lower(): v for k, v in mapping.items()}

        def resolve(name: str) -> Optional[str]:
            if name in mapping:
                return mapping[name]
            return lowered.get(name.lower())

        applied: Dict[str, str] = {}   # 原始字体名 -> 子集字体名（只记录真正用到的）

        for style in self.styles:
            if self.font_pos >= len(style.fields):
                continue
            raw = style.fields[self.font_pos]
            vertical = raw.startswith("@")
            base = raw.lstrip("@")
            new = resolve(base)
            if new and new != base:
                style.fields[self.font_pos] = ("@" if vertical else "") + new
                self.lines[style.line_index] = style.render()
                applied.setdefault(base, new)

        for event in self.events:
            if event.text_index >= len(event.fields):
                continue
            text = event.fields[event.text_index]

            def sub(match: "re.Match[str]") -> str:
                name = match.group(1)
                new = resolve(name)
                if new and new != name:
                    applied.setdefault(name, new)
                    return "\\fn" + new
                return match.group(0)

            new_text = RE_FONT_TAG.sub(sub, text)
            if new_text != text:
                event.fields[event.text_index] = new_text
                self.lines[event.line_index] = event.render()

        if not applied:
            return []
        notes = ["; Subset via SubFontMKV (fontTools)\n"]
        for orig, new in sorted(applied.items()):
            notes.append("; Font Subset: {0} - {1}\n".format(new, orig))
        insert_at = (self.script_info_index + 1) if self.script_info_index is not None else 0
        # 去掉上一次子集化留下的注释，避免同一个字幕被处理两次后注释越堆越多
        for index in sorted(self.subset_comment_lines, reverse=True):
            if 0 <= index < len(self.lines):
                del self.lines[index]
        self.subset_comment_lines = []
        for offset, note in enumerate(notes):
            self.lines.insert(insert_at + offset, note)
        return notes

    def save(self, path: str, encoding: str = "utf-8-sig") -> str:
        directory = os.path.dirname(os.path.abspath(path))
        if directory and not os.path.isdir(directory):
            os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding=encoding, newline="") as fp:
            fp.writelines(self.lines)
        return path

    def dialogue_texts(self) -> List[str]:
        out = []
        for event in self.events:
            if event.text_index < len(event.fields):
                out.append(event.fields[event.text_index])
        return out


# --------------------------------------------------------------------------
# 语言推断
# --------------------------------------------------------------------------
#: 常见语言标记 -> ISO-639-2（mkvmerge 只接受 ISO-639-2 / ISO-639-1）
LANGUAGE_TAGS: Dict[str, str] = {
    "chi": "chi", "chs": "chi", "cht": "chi", "zh": "chi", "sc": "chi", "tc": "chi",
    "cn": "chi", "gb": "chi", "gbk": "chi", "big5": "chi", "hans": "chi", "hant": "chi",
    "简体": "chi", "繁体": "chi", "简": "chi", "繁": "chi", "中文": "chi",
    "jpn": "jpn", "jp": "jpn", "ja": "jpn", "日语": "jpn", "日文": "jpn",
    "eng": "eng", "en": "eng", "english": "eng", "英文": "eng", "英语": "eng",
    "kor": "kor", "kr": "kor", "ko": "kor", "韩语": "kor", "韩文": "kor",
    "fre": "fra", "fra": "fra", "fr": "fra", "ger": "deu", "deu": "deu", "de": "deu",
    "spa": "spa", "es": "spa", "rus": "rus", "ru": "rus", "por": "por", "pt": "por",
    "ita": "ita", "it": "ita", "und": "und",
}


def language_from_name(filename: str) -> Optional[str]:
    """从文件名推断字幕语言，返回 ISO-639-2 三字母代码。"""
    stem = os.path.splitext(os.path.basename(filename))[0]
    parts = [p for p in re.split(r"[.\-_\[\]()\s]+", stem) if p]
    for part in reversed(parts):
        low = part.lower()
        if low in LANGUAGE_TAGS:
            return LANGUAGE_TAGS[low]
        if "-" in low or "_" in low:
            head = re.split(r"[-_]", low)[0]
            if head in LANGUAGE_TAGS:
                return LANGUAGE_TAGS[head]
    return None


def track_title(video_stem: str, subtitle_path: str) -> Optional[str]:
    """由字幕文件名推出轨道标题，例如 Show.chs.ass -> chs。"""
    sub_stem = os.path.splitext(os.path.basename(subtitle_path))[0]
    if video_stem and sub_stem.lower().startswith(video_stem.lower()):
        note = sub_stem[len(video_stem):]
    else:
        note = sub_stem
    note = note.replace(".subset", "").strip(". -_")
    return note or None
