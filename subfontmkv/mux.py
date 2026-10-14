# -*- coding: utf-8 -*-
"""调用 mkvmerge / ffmpeg 把视频、字幕、字体封装成 MKV。

优先使用 mkvmerge（能同时写入软字幕轨与字体附件）；
若找不到 mkvmerge 则回退到 ffmpeg（只能附加字体，能力有限）。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import Dict, List, Optional, Sequence, Tuple

from .fonts import font_mime_type
from .log import get_logger

log = get_logger("mux")

#: MKV 支持的视频扩展名
VIDEO_EXTENSIONS = (
    ".mkv", ".mk3d", ".webm", ".mp4", ".m4v", ".avi", ".mov", ".ts", ".m2ts",
    ".mts", ".mpg", ".mpeg", ".vob", ".flv", ".rm", ".rmvb", ".wmv", ".asf",
)

#: 字幕扩展名
SUBTITLE_EXTENSIONS = (".ass", ".ssa", ".srt", ".vtt", ".sup", ".idx", ".sub")

#: 断言语言标签只接受 ISO-639-2 / ISO-639-1
RE_LANGUAGE = re.compile(r"^[A-Za-z]{2,3}$")

WINDOWS_MKVMERGE_CANDIDATES = (
    r"C:\Program Files\MKVToolNix\mkvmerge.exe",
    r"C:\Program Files (x86)\MKVToolNix\mkvmerge.exe",
)


def _which(name: str) -> Optional[str]:
    found = shutil.which(name)
    return found


def find_mkvmerge(explicit: Optional[str] = None) -> Optional[str]:
    """查找 mkvmerge，返回绝对路径或 None。"""
    if explicit:
        if os.path.isfile(explicit):
            return os.path.abspath(explicit)
        found = _which(explicit)
        if found:
            return found
        raise FileNotFoundError("指定的 mkvmerge 不存在: {0}".format(explicit))
    found = _which("mkvmerge")
    if found:
        return found
    if os.name == "nt":
        for candidate in WINDOWS_MKVMERGE_CANDIDATES:
            if os.path.isfile(candidate):
                return candidate
        # 兜底：在常见安装根目录里搜一层
        for root in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
            if not root:
                continue
            guess = os.path.join(root, "MKVToolNix", "mkvmerge.exe")
            if os.path.isfile(guess):
                return guess
    return None


def find_ffmpeg(explicit: Optional[str] = None) -> Optional[str]:
    if explicit:
        if os.path.isfile(explicit):
            return os.path.abspath(explicit)
        return _which(explicit)
    return _which("ffmpeg")


class MuxError(Exception):
    """封装失败。"""


class Muxer(object):
    """封装器后端。"""

    name = "base"
    supports_attachments = False

    def __init__(self, executable: str) -> None:
        self.executable = executable

    def version(self) -> str:
        try:
            result = run_command([self.executable, "--version"], capture=True)
            first = (result.stdout or result.stderr or "").splitlines()
            return first[0].strip() if first else "unknown"
        except Exception:
            return "unknown"


class MkvmergeMuxer(Muxer):
    name = "mkvmerge"
    supports_attachments = True

    @classmethod
    def locate(cls, explicit: Optional[str] = None) -> Optional["MkvmergeMuxer"]:
        path = find_mkvmerge(explicit)
        return cls(path) if path else None

    def build_command(
        self,
        video: str,
        output: str,
        subtitles: Sequence[Tuple[str, Optional[str], Optional[str]]] = (),
        attachments: Sequence[str] = (),
        keep_source_subs: bool = False,
        keep_source_attachments: bool = False,
        title: Optional[str] = None,
    ) -> List[str]:
        """构造 mkvmerge 参数列表。

        subtitles 的每一项是 (路径, 语言, 轨道标题)。
        """
        args: List[str] = []
        if not keep_source_subs:
            args.append("--no-subtitles")
        if not keep_source_attachments:
            args.append("--no-attachments")
        args.extend(["--no-global-tags", "--no-chapters"])

        args.append(video)
        for path, language, track_title in subtitles:
            if track_title:
                args.extend(["--track-name", "0:{0}".format(track_title)])
            if language and RE_LANGUAGE.match(language):
                args.extend(["--language", "0:{0}".format(language)])
            args.append(path)
        for path in attachments:
            args.extend(["--attachment-mime-type", font_mime_type(path)])
            args.extend(["--attach-file", os.path.abspath(path)])
        if title:
            args.extend(["--title", title])
        args.extend(["-o", os.path.abspath(output)])
        return args

    def mux(self, **kwargs) -> "MuxResult":
        output = kwargs["output"]
        args = self.build_command(**kwargs)
        log.debug("mkvmerge 参数: %s", args)
        result = run_command([self.executable] + args)
        if result.returncode not in (0, 1):
            raise MuxError("mkvmerge 失败（返回码 {0}）\n{1}".format(
                result.returncode, _tail(result.stderr or result.stdout)))
        if not os.path.exists(output) or os.path.getsize(output) == 0:
            raise MuxError("mkvmerge 未生成输出文件: {0}".format(output))
        warnings = [ln for ln in (result.stderr or "").splitlines()
                    if ln.lower().startswith("warning")]
        return MuxResult(output, result.returncode, warnings)

    def identify(self, path: str) -> Dict:
        result = run_command([self.executable, "-J", path], capture=True)
        try:
            return json.loads(result.stdout)
        except Exception:
            return {}


class FfmpegMuxer(Muxer):
    name = "ffmpeg"
    supports_attachments = True

    @classmethod
    def locate(cls, explicit: Optional[str] = None) -> Optional["FfmpegMuxer"]:
        path = find_ffmpeg(explicit)
        return cls(path) if path else None

    def build_command(
        self,
        video: str,
        output: str,
        subtitles: Sequence[Tuple[str, Optional[str], Optional[str]]] = (),
        attachments: Sequence[str] = (),
        keep_source_subs: bool = False,
        keep_source_attachments: bool = False,
        title: Optional[str] = None,
    ) -> List[str]:
        args = ["-y", "-i", os.path.abspath(video)]
        if subtitles:
            # 视频里已有的字幕轨默认丢弃，避免与新的重复
            args.extend(["-map", "0:v", "-map", "0:a?"])
        else:
            args.extend(["-map", "0"])
        for path, language, track_title in subtitles:
            args.extend(["-i", os.path.abspath(path)])
        args.extend(["-map_metadata", "-1", "-map_chapters", "-1"])
        if title:
            args.extend(["-metadata", "title={0}".format(title)])
        for index, (path, language, track_title) in enumerate(subtitles):
            out_index = index if subtitles else 0
            if language and RE_LANGUAGE.match(language):
                args.extend(["-metadata:s:s:{0}".format(out_index),
                             "language={0}".format(language)])
            if track_title:
                args.extend(["-metadata:s:s:{0}".format(out_index),
                             "title={0}".format(track_title)])
        for path in attachments:
            # ffmpeg 只能把字体挂成「带 mimetype 的附件流」
            args.extend(["-attach", os.path.abspath(path)])
            args.extend(["-metadata:s:t", "mimetype={0}".format(font_mime_type(path))])
        args.extend(["-c", "copy"])
        args.extend(["-f", "matroska", os.path.abspath(output)])
        return args

    def mux(self, **kwargs) -> "MuxResult":
        output = kwargs["output"]
        args = self.build_command(**kwargs)
        log.debug("ffmpeg 参数: %s", args)
        result = run_command([self.executable] + args)
        if result.returncode != 0:
            raise MuxError("ffmpeg 失败（返回码 {0}）\n{1}".format(
                result.returncode, _tail(result.stderr or result.stdout)))
        if not os.path.exists(output) or os.path.getsize(output) == 0:
            raise MuxError("ffmpeg 未生成输出文件: {0}".format(output))
        return MuxResult(output, result.returncode, [])

    def identify(self, path: str) -> Dict:
        return {}


class MuxResult(object):
    """一次封装的结果。"""

    __slots__ = ("output", "returncode", "warnings")

    def __init__(self, output: str, returncode: int, warnings: List[str]) -> None:
        self.output = output
        self.returncode = returncode
        self.warnings = warnings


class CommandResult(object):
    __slots__ = ("returncode", "stdout", "stderr")

    def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def run_command(args: Sequence[str], capture: bool = False) -> CommandResult:
    """用 subprocess 运行外部程序，杜绝 shell 引号转义问题。"""
    kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            list(args),
            stdin=subprocess.DEVNULL,
            universal_newlines=True,
            encoding="utf-8",
            errors="replace",
            **kwargs
        )
    except FileNotFoundError:
        raise MuxError("找不到可执行文件: {0}".format(args[0]))
    except OSError as exc:
        raise MuxError("无法执行 {0}: {1}".format(args[0], exc))
    out = completed.stdout or ""
    err = completed.stderr or ""
    if not capture:
        for line in (out + err).splitlines():
            if line.strip():
                log.debug("  %s", line)
    return CommandResult(completed.returncode, out, err)


def _tail(text: str, lines: int = 15) -> str:
    parts = [ln for ln in (text or "").splitlines() if ln.strip()]
    return "\n".join(parts[-lines:])


def select_muxer(preference: str = "auto", mkvmerge_path: Optional[str] = None,
                 ffmpeg_path: Optional[str] = None) -> Muxer:
    """按偏好选择封装器。"""
    preference = (preference or "auto").lower()
    if preference == "mkvmerge":
        muxer = MkvmergeMuxer.locate(mkvmerge_path)
        if muxer is None:
            raise MuxError("未找到 mkvmerge，请安装 MKVToolNix 或用 --mkvmerge 指定路径")
        return muxer
    if preference == "ffmpeg":
        muxer = FfmpegMuxer.locate(ffmpeg_path)
        if muxer is None:
            raise MuxError("未找到 ffmpeg，请安装 ffmpeg 或加入 PATH")
        return muxer
    mkv = MkvmergeMuxer.locate(mkvmerge_path)
    if mkv is not None:
        return mkv
    ff = FfmpegMuxer.locate(ffmpeg_path)
    if ff is not None:
        log.warning("未找到 mkvmerge，回退到 ffmpeg；ffmpeg 无法写入独立的软字幕轨")
        return ff
    raise MuxError("既没有找到 mkvmerge 也没有找到 ffmpeg，请先安装其中之一")


def is_video(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in VIDEO_EXTENSIONS


def is_subtitle(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in SUBTITLE_EXTENSIONS


def is_font(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in (".ttf", ".otf", ".ttc", ".otc")
