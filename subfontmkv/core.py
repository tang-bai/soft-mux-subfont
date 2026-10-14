# -*- coding: utf-8 -*-
"""SubFontMKV 核心流程：匹配字幕、子集化字体、改写字幕、封装 MKV。

CLI 与 GUI 共用这里的 Planner / MuxJob，两条路径行为完全一致。
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
from typing import Dict, List, Optional, Sequence, Set, Tuple

from . import ass
from .fonts import (DEFAULT_EXTRA_CHARS, FontIndex, SubsetError, extract_face,
                    sanitize_filename, subset_font)
from .log import get_logger
from .mux import MuxError, Muxer, is_subtitle, is_video, select_muxer

log = get_logger("core")

#: 与视频同名的字幕才算外挂字幕；这些后缀允许出现在名字与扩展名之间
RE_SUBTITLE_SUFFIX = re.compile(r"^(?:[.\-_ ]|$)")


class SubtitleMatch(object):
    """一个视频匹配到的一条字幕。"""

    __slots__ = ("path", "language", "title")

    def __init__(self, path: str, language: Optional[str], title: Optional[str]) -> None:
        self.path = path
        self.language = language
        self.title = title

    def __repr__(self) -> str:  # pragma: no cover
        return "<SubtitleMatch {0} lang={1}>".format(os.path.basename(self.path), self.language)


class FontRequest(object):
    """一个字体的子集化需求。"""

    __slots__ = ("fontname", "bold", "italic", "chars", "uses", "face")

    def __init__(self, fontname: str, bold: bool, italic: bool) -> None:
        self.fontname = fontname
        self.bold = bold
        self.italic = italic
        self.chars = ""
        self.uses = 0
        self.face = None

    def add(self, chars: str, uses: int = 1) -> None:
        self.chars = "".join(sorted(set(self.chars) | set(chars)))
        self.uses += uses

    def __repr__(self) -> str:  # pragma: no cover
        return "<FontRequest {0} bold={1} italic={2} chars={3}>".format(
            self.fontname, self.bold, self.italic, len(self.chars))


class Job(object):
    """一个待处理的视频任务。"""

    def __init__(self, video: str) -> None:
        self.video = os.path.abspath(video)
        self.subtitles: List[SubtitleMatch] = []
        self.fonts: Dict[Tuple[str, bool, bool], FontRequest] = {}
        self.missing_fonts: List[str] = []
        self.missing_chars: List[str] = []
        self.output: Optional[str] = None
        self.status = "pending"
        self.message = ""

    @property
    def stem(self) -> str:
        return os.path.splitext(os.path.basename(self.video))[0]

    @property
    def directory(self) -> str:
        return os.path.dirname(self.video)

    def __repr__(self) -> str:  # pragma: no cover
        return "<Job {0} subs={1} fonts={2}>".format(self.stem, len(self.subtitles), len(self.fonts))


class Options(object):
    """运行选项。"""

    def __init__(self) -> None:
        self.font_dirs: List[str] = []
        self.sub_dirs: List[str] = []
        self.language: str = "und"
        self.infer_language: bool = True
        self.subset: bool = True
        self.system_fonts: bool = True
        self.suffix: str = ".subfont"
        self.keep_source_subs: bool = False
        self.keep_source_attachments: bool = False
        self.muxer: str = "auto"
        self.mkvmerge: Optional[str] = None
        self.ffmpeg: Optional[str] = None
        self.output_dir: Optional[str] = None
        self.work_dir: Optional[str] = None
        self.recursive: bool = False
        self.dry_run: bool = False
        self.attach_full_fonts: bool = False   # 子集化失败时是否内嵌完整字体
        self.title_from_filename: bool = True


# --------------------------------------------------------------------------
# 字幕匹配
# --------------------------------------------------------------------------
def find_subtitles(video: str, extra_dirs: Sequence[str] = (), ) -> List[str]:
    """找出与视频同名的外挂字幕。

    同时搜索视频所在目录与 --sub-dir 指定的目录，结果按绝对路径去重，
    避免同一个字幕被匹配到两次而封装出重复轨道。
    """
    stem = os.path.splitext(os.path.basename(video))[0]
    directories: List[str] = [os.path.dirname(os.path.abspath(video))]
    for d in extra_dirs:
        real = os.path.abspath(d)
        if os.path.isdir(real):
            directories.append(real)
    seen: Set[str] = set()
    matches: List[str] = []
    for directory in directories:
        try:
            entries = sorted(os.scandir(directory), key=lambda e: e.name.lower())
        except OSError:
            continue
        for entry in entries:
            if not entry.is_file(follow_symlinks=False):
                continue
            path = os.path.abspath(entry.path)
            key = os.path.normcase(path)
            if key in seen:
                continue
            name = entry.name
            if not is_subtitle(path):
                continue
            if not _name_matches(stem, name):
                continue
            seen.add(key)
            matches.append(path)
    # 按 (语言, 文件名) 排序，保证语言与轨道顺序稳定可预期
    matches.sort(key=lambda p: (ass.language_from_name(p) or "zzz", os.path.basename(p).lower()))
    return matches


#: 允许出现在视频名之后、属于同一部片子的版本标记（v2 / ver2 / version2）。
#: 刻意不接受 ep01 / part2 —— 那些属于不同集数，不能当成同一个视频的字幕。
RE_VERSION_TOKEN = re.compile(r"^(?:v|ver|version)\d+$", re.IGNORECASE)


def _name_matches(stem: str, subtitle_name: str) -> bool:
    """判断字幕文件名是否属于该视频（视频名 + 语言/版本标记 + 扩展名）。

    只允许在视频名之后追加语言标签（chs/jpn/...）与版本标记（v2/ep01/...），
    这样可以避免同一目录下 "Show.mkv" 误吃 "Show EP01.chs.ass"。
    """
    name = os.path.splitext(subtitle_name)[0]
    if name.lower() == stem.lower():
        return True
    if not name.lower().startswith(stem.lower()):
        return False
    rest = name[len(stem):]
    if not rest:
        return True
    if rest[0] not in ".-_ ":
        return False
    if not RE_SUBTITLE_SUFFIX.match(rest):
        return False
    for token in (t for t in re.split(r"[.\-_ ]+", rest) if t):
        low = token.lower()
        if low in ass.LANGUAGE_TAGS:
            continue
        if RE_VERSION_TOKEN.match(low):
            continue
        if low in ("subset", "font", "fonts", "zh", "cn"):
            continue
        return False
    return True


def match_subtitles(video: str, options: Options) -> List[SubtitleMatch]:
    stem = os.path.splitext(os.path.basename(video))[0]
    out: List[SubtitleMatch] = []
    for path in find_subtitles(video, options.sub_dirs):
        language = options.language
        if options.infer_language:
            language = ass.language_from_name(path) or options.language
        out.append(SubtitleMatch(path, language, ass.track_title(stem, path)))
    return out


def is_own_output(path: str, suffix: str) -> bool:
    """判断这是不是本工具之前生成的产物（避免重复加工自己的输出）。"""
    if not suffix:
        return False
    stem = os.path.splitext(os.path.basename(path))[0]
    return stem.lower().endswith(suffix.lower())


def collect_videos(targets: Sequence[str], recursive: bool = False,
                   suffix: str = "") -> List[str]:
    """把文件/目录展开成一个去重后的视频列表。

    扫描目录时会跳过本工具自己的产物（文件名带 suffix），否则对库目录
    反复执行 --recursive 会把上次的输出再封装一遍。
    显式指定的文件一律保留，尊重用户的意图。
    """
    found: List[str] = []
    seen: Set[str] = set()
    skipped_outputs: List[str] = []

    def add(path: str, from_scan: bool) -> None:
        real = os.path.abspath(path)
        if from_scan and is_own_output(real, suffix):
            skipped_outputs.append(real)
            return
        key = os.path.normcase(real)
        if key not in seen:
            seen.add(key)
            found.append(real)

    for target in targets:
        real = os.path.abspath(target)
        if os.path.isfile(real):
            if is_video(real):
                add(real, from_scan=False)
            else:
                log.warning("跳过非视频文件: %s", real)
        elif os.path.isdir(real):
            if recursive:
                for root, dirs, files in os.walk(real):
                    dirs[:] = sorted(d for d in dirs if not d.startswith("."))
                    for name in sorted(files):
                        if is_video(name):
                            add(os.path.join(root, name), from_scan=True)
            else:
                for entry in sorted(os.scandir(real), key=lambda e: e.name.lower()):
                    if entry.is_file(follow_symlinks=False) and is_video(entry.name):
                        add(entry.path, from_scan=True)
        else:
            log.warning("路径不存在: %s", real)
    if skipped_outputs:
        log.info("跳过 %d 个本工具之前的输出（文件名含 %s）。", len(skipped_outputs), suffix)
    return found


# --------------------------------------------------------------------------
# 规划
# --------------------------------------------------------------------------
class Planner(object):
    """负责建立字体索引、分析字幕、决定需要子集化哪些字体。"""

    def __init__(self, options: Options) -> None:
        self.options = options
        self.index = FontIndex()
        self._indexed = False

    def build_index(self) -> None:
        if self._indexed:
            return
        count = 0
        for directory in self.options.font_dirs:
            real = os.path.abspath(directory)
            if os.path.isdir(real):
                count += self.index.add_directory(real, recursive=True)
            else:
                log.warning("额外字体目录不存在: %s", real)
        if self.options.system_fonts:
            for directory in _system_dirs():
                count += self.index.add_directory(directory)
        log.info("字体索引就绪，共 %d 个字体名。", self.index.name_count)
        self._indexed = True

    def plan(self, job: Job) -> Job:
        self.build_index()
        job.subtitles = match_subtitles(job.video, self.options)
        if not job.subtitles:
            job.status = "skipped"
            job.message = "未匹配到字幕"
            return job

        for match in job.subtitles:
            if os.path.splitext(match.path)[1].lower() not in (".ass", ".ssa"):
                continue  # 其它格式不做字体处理
            try:
                parsed = ass.AssFile.load(match.path)
            except Exception as exc:
                log.error("解析字幕失败 %s: %s", match.path, exc)
                continue
            for key, chars in parsed.font_usage().items():
                fontname, bold, italic = key
                request = job.fonts.get(key)
                if request is None:
                    request = FontRequest(fontname, bold, italic)
                    job.fonts[key] = request
                request.add(chars)
        # 先做一次字体查找，这样试运行也能报出缺失字体
        self.resolve_fonts(job)
        return job

    def resolve_fonts(self, job: Job) -> None:
        """把字体需求解析成实际字体文件；找不到的记入 missing_fonts。"""
        # 注意：这里不要重置 job.missing_fonts —— 它由 plan() 阶段填充
        for key, request in sorted(job.fonts.items()):
            face = self.index.match(request.fontname, request.bold, request.italic)
            if face is None:
                if request.fontname not in job.missing_fonts:
                    job.missing_fonts.append(request.fontname)
                continue
            request.face = face


def _system_dirs() -> List[str]:
    from .fonts import system_font_dirs

    return system_font_dirs()


# --------------------------------------------------------------------------
# 执行
# --------------------------------------------------------------------------
class Processor(object):
    """执行封装。"""

    def __init__(self, options: Options) -> None:
        self.options = options
        self.planner = Planner(options)
        self.muxer: Optional[Muxer] = None
        self._temp_root: Optional[str] = None

    # -- 资源 ---------------------------------------------------------------
    def setup(self) -> None:
        self.planner.build_index()
        self.muxer = select_muxer(self.options.muxer, self.options.mkvmerge, self.options.ffmpeg)
        log.info("封装器: %s (%s)", self.muxer.name, getattr(self.muxer, "executable", "?"))

    def temp_root(self) -> str:
        if self._temp_root is None:
            base = self.options.work_dir or tempfile.gettempdir()
            os.makedirs(base, exist_ok=True)
            self._temp_root = tempfile.mkdtemp(prefix="subfontmkv-", dir=base)
        return self._temp_root

    def cleanup(self) -> None:
        if self._temp_root and os.path.isdir(self._temp_root):
            shutil.rmtree(self._temp_root, ignore_errors=True)
        self._temp_root = None

    # -- 输出路径 -----------------------------------------------------------
    def output_path(self, job: Job) -> str:
        stem = job.stem
        suffix = self.options.suffix or ""
        if self.options.output_dir:
            directory = os.path.abspath(self.options.output_dir)
        else:
            directory = job.directory
        os.makedirs(directory, exist_ok=True)
        candidate = os.path.join(directory, stem + suffix + ".mkv")
        counter = 1
        while os.path.exists(candidate):
            candidate = os.path.join(directory, "{0}{1}#{2}.mkv".format(stem, suffix, counter))
            counter += 1
        return candidate

    # -- 单个任务 -----------------------------------------------------------
    def process(self, job: Job) -> Job:
        if self.muxer is None:
            self.setup()
        assert self.muxer is not None

        self.planner.plan(job)
        if job.status == "skipped":
            log.info("跳过（%s）: %s", job.message, os.path.basename(job.video))
            return job

        log.info("=== %s ===", os.path.basename(job.video))
        log.info("匹配到 %d 条字幕:", len(job.subtitles))
        for match in job.subtitles:
            log.info("  - %s%s", os.path.basename(match.path),
                     "  [{0}]".format(match.language) if match.language else "")

        if job.missing_fonts:
            log.warning("以下字体未找到，将不在 MKV 中内嵌: %s", "、".join(sorted(set(job.missing_fonts))))

        # 1. 子集化字体
        attachments: List[str] = []
        font_map: Dict[Tuple[str, bool, bool], str] = {}
        work = self.temp_root()
        if job.fonts and not self.options.dry_run:
            self.planner.resolve_fonts(job)
            for key in sorted(job.fonts):
                request = job.fonts[key]
                face = request.face
                if face is None:
                    continue
                try:
                    if self.options.subset:
                        path, _crc = self._subset(request, face, work)
                        font_map[key] = os.path.basename(path)[: -len(os.path.splitext(path)[1])]
                        log.info("  子集化字体: %s (%d 字)", os.path.basename(path), len(request.chars))
                    else:
                        path = extract_face(face.path, face.index,
                                            os.path.join(work, _unique_name(
                                                work, os.path.basename(face.path))))
                        log.info("  内嵌完整字体: %s", os.path.basename(path))
                except SubsetError as exc:
                    log.warning("字体 %s 子集化失败: %s", request.fontname, exc)
                    if not self.options.attach_full_fonts:
                        continue   # 默认不降级：宁可少一个字体也不要塞进完整字体
                    try:
                        path = extract_face(face.path, face.index,
                                            os.path.join(work, _unique_name(
                                                work, os.path.basename(face.path))))
                        log.info("  改为内嵌完整字体: %s", os.path.basename(path))
                    except Exception as fallback_exc:
                        log.error("导出完整字体也失败: %s", fallback_exc)
                        continue
                if path not in attachments:
                    attachments.append(path)

        # 2. 改写字幕字体名
        rewritten: List[Tuple[str, Optional[str], Optional[str]]] = []
        for match in job.subtitles:
            extension = os.path.splitext(match.path)[1].lower()
            if extension in (".ass", ".ssa") and font_map and not self.options.dry_run:
                try:
                    parsed = ass.AssFile.load(match.path)
                    mapping = {}
                    for (fontname, bold, italic), new_name in font_map.items():
                        mapping[fontname] = new_name
                    parsed.apply_font_map(mapping)
                    target = os.path.join(work, _unique_name(work, os.path.basename(match.path)))
                    parsed.save(target, encoding="utf-8-sig")
                    rewritten.append((target, match.language, match.title))
                    continue
                except Exception as exc:
                    log.error("改写字幕失败 %s: %s", match.path, exc)
            rewritten.append((match.path, match.language, match.title))

        if self.options.dry_run:
            job.status = "dry-run"
            job.output = self.output_path(job)
            log.info("试运行：将输出 %s", job.output)
            return job

        # 3. 封装
        output = self.output_path(job)
        title = job.stem if self.options.title_from_filename else None
        try:
            result = self.muxer.mux(
                video=job.video,
                output=output,
                subtitles=rewritten,
                attachments=attachments,
                keep_source_subs=self.options.keep_source_subs,
                keep_source_attachments=self.options.keep_source_attachments,
                title=title,
            )
        except MuxError as exc:
            job.status = "failed"
            job.message = str(exc)
            log.error("封装失败 %s: %s", job.stem, exc)
            return job

        for warning in result.warnings[:5]:
            log.warning("mkvmerge: %s", warning)
        job.output = result.output
        job.status = "ok"
        log.info("封装完成: %s", result.output)
        return job

    def _subset(self, request: FontRequest, face, work: str) -> Tuple[str, str]:
        name = "{0}{1}".format(
            sanitize_filename(request.fontname),
            "_Bold" if request.bold else "",
        )
        if request.italic:
            name += "_Italic"
        output = os.path.join(work, name + os.path.splitext(face.path)[1])
        return subset_font(face.path, face.index, output, request.chars, DEFAULT_EXTRA_CHARS)


def _unique_name(directory: str, name: str) -> str:
    candidate = name
    counter = 1
    while os.path.exists(os.path.join(directory, candidate)):
        stem, ext = os.path.splitext(name)
        candidate = "{0}#{1}{2}".format(stem, counter, ext)
        counter += 1
    return candidate


# --------------------------------------------------------------------------
# 高层入口
# --------------------------------------------------------------------------
def new_summary(total: int) -> Dict[str, object]:
    return {"total": total, "ok": 0, "failed": 0, "skipped": 0, "dry_run": 0, "jobs": []}


def run(
    targets: Sequence[str],
    options: Options,
    on_event=None,
    should_stop=None,
) -> Dict[str, object]:
    """处理一批目标，返回统计结果。

    on_event(kind, job, index, total) 会在每个任务开始/结束时被调用，
    should_stop() 返回 True 时会在当前文件处理完后中断（供 GUI 的「停止」使用）。
    """
    videos = collect_videos(targets, options.recursive, options.suffix)
    if not videos:
        log.error("没有找到任何视频文件")
        return new_summary(0)

    processor = Processor(options)
    processor.setup()
    summary = new_summary(len(videos))
    try:
        for index, video in enumerate(videos, 1):
            if should_stop is not None and should_stop():
                log.warning("已停止，剩余 %d 个文件未处理", len(videos) - index + 1)
                break
            log.info("[%d/%d] %s", index, len(videos), os.path.basename(video))
            job = Job(video)
            if on_event is not None:
                on_event("start", job, index, len(videos))
            try:
                processor.process(job)
            except Exception as exc:  # 单个任务失败不应中断整批
                job.status = "failed"
                job.message = str(exc)
                log.error("处理失败 %s: %s", os.path.basename(video), exc)
            counter_key = {"dry-run": "dry_run"}.get(job.status, job.status)
            if counter_key not in summary:
                counter_key = "failed"
            summary[counter_key] += 1  # type: ignore[operator]
            summary["jobs"].append(job)  # type: ignore[union-attr]
            if on_event is not None:
                on_event("done", job, index, len(videos))
    finally:
        processor.cleanup()

    log.info("完成: 成功 %d / 试运行 %d / 跳过 %d / 失败 %d",
             summary["ok"], summary["dry_run"], summary["skipped"], summary["failed"])
    return summary
