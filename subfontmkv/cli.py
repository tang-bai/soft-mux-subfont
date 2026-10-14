# -*- coding: utf-8 -*-
"""SubFontMKV 命令行入口。"""
from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from . import __version__
from . import core
from .log import DEBUG, WARNING, add_handler, get_logger, set_level

log = get_logger("cli")

EPILOG = """示例:
  python -m subfontmkv "D:\\Anime\\Show EP01.mkv"
  python -m subfontmkv "D:\\Anime" --recursive --font-dir "D:\\Fonts"
  python -m subfontmkv "D:\\Anime" --dry-run --json
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="subfontmkv",
        description="把外挂字幕和字体软封装进 MKV：字幕成为可开关的软字幕轨，字体作为附件内嵌。",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("targets", nargs="*", metavar="路径",
                        help="视频文件或目录（可多个）")
    parser.add_argument("--font-dir", action="append", default=[], metavar="DIR",
                        help="额外字体目录，可重复")
    parser.add_argument("--sub-dir", action="append", default=[], metavar="DIR",
                        help="额外的字幕搜索目录，可重复")
    parser.add_argument("--output-dir", "-o", default=None, metavar="DIR",
                        help="输出目录，默认与视频同目录")
    parser.add_argument("--suffix", default=".subfont", metavar="SUFFIX",
                        help="输出文件名后缀，默认 .subfont")
    parser.add_argument("--language", "-l", default="und", metavar="LANG",
                        help="默认字幕语言，默认 und")
    parser.add_argument("--no-infer-language", action="store_true",
                        help="不从文件名推断字幕语言")
    parser.add_argument("--no-subset", action="store_true",
                        help="不做子集化，直接内嵌完整字体")
    parser.add_argument("--no-system-fonts", action="store_true",
                        help="不读取系统字体目录（启动更快）")
    parser.add_argument("--muxer", choices=("auto", "mkvmerge", "ffmpeg"), default="auto",
                        help="指定封装器，默认自动选择")
    parser.add_argument("--mkvmerge", default=None, metavar="PATH",
                        help="手动指定 mkvmerge 路径")
    parser.add_argument("--ffmpeg", default=None, metavar="PATH",
                        help="手动指定 ffmpeg 路径")
    parser.add_argument("--keep-source-subs", action="store_true",
                        help="保留源 MKV 里已有的字幕轨（默认丢弃）")
    parser.add_argument("--keep-source-attach", action="store_true",
                        help="保留源 MKV 里已有的附件（默认丢弃）")
    parser.add_argument("--recursive", "-r", action="store_true",
                        help="目录递归处理")
    parser.add_argument("--dry-run", action="store_true",
                        help="只显示将会执行的操作，不实际封装")
    parser.add_argument("--json", action="store_true",
                        help="以 JSON 输出结果（日志转到 stderr）")
    parser.add_argument("--work-dir", default=None, metavar="DIR",
                        help="临时工作目录，默认使用系统临时目录")
    parser.add_argument("-q", "--quiet", action="store_true", help="只输出警告与错误")
    parser.add_argument("-v", "--verbose", action="store_true", help="输出调试信息")
    parser.add_argument("--version", action="version",
                        version="SubFontMKV {0}".format(__version__))
    return parser


def options_from_args(args: argparse.Namespace) -> core.Options:
    options = core.Options()
    options.font_dirs = list(args.font_dir)
    options.sub_dirs = list(args.sub_dir)
    options.output_dir = args.output_dir
    options.suffix = args.suffix or ""
    options.language = args.language
    options.infer_language = not args.no_infer_language
    options.subset = not args.no_subset
    options.system_fonts = not args.no_system_fonts
    options.muxer = args.muxer
    options.mkvmerge = args.mkvmerge
    options.ffmpeg = args.ffmpeg
    options.keep_source_subs = args.keep_source_subs
    options.keep_source_attachments = args.keep_source_attach
    options.recursive = args.recursive
    options.dry_run = args.dry_run
    options.work_dir = args.work_dir
    options.attach_full_fonts = args.no_subset
    return options


def _json_report(summary) -> dict:
    files = []
    for job in summary["jobs"]:
        files.append({
            "video": job.video,
            "output": job.output,
            "status": job.status,
            "message": job.message,
            "subtitles": [
                {"path": m.path, "language": m.language, "title": m.title}
                for m in job.subtitles
            ],
            "fonts": sorted({key[0] for key in job.fonts}),
            "missing_fonts": sorted(set(job.missing_fonts)),
        })
    return {
        "tool": "subfontmkv",
        "version": __version__,
        "total": summary["total"],
        "ok": summary["ok"],
        "failed": summary["failed"],
        "skipped": summary["skipped"],
        "dry_run": summary["dry_run"],
        "files": files,
    }


def main(argv: Optional[List[str]] = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw and raw[0] in ("gui", "界面"):
        from .gui import launch

        return launch(raw[1:])
    parser = build_parser()
    args = parser.parse_args(raw)

    if args.verbose:
        set_level(DEBUG)
    elif args.quiet:
        set_level(WARNING)

    if not args.targets:
        parser.print_help()
        return 2

    if args.json:
        # JSON 模式下把日志全部送到 stderr，stdout 只留结果
        add_handler(lambda text, level: print(text, file=sys.stderr, flush=True))

    options = options_from_args(args)
    try:
        summary = core.run(args.targets, options)
    except KeyboardInterrupt:
        log.error("已中断")
        return 130
    except Exception as exc:
        log.error("运行失败: %s", exc)
        if args.verbose:
            import traceback

            traceback.print_exc()
        return 1

    if args.json:
        print(json.dumps(_json_report(summary), ensure_ascii=False, indent=2))

    if summary["failed"]:
        return 1
    if summary["total"] == 0:
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
