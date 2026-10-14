# -*- coding: utf-8 -*-
"""SubFontMKV 打包入口（PyInstaller 用）。

打包后是一个**图形界面**程序：双击就开界面。
同时保留了完整的命令行能力 —— 带参数运行时按命令行处理，例如：

    SubFontMKV.exe "D:\\Anime" --recursive
    SubFontMKV.exe --help
    SubFontMKV.exe --version

命令行模式下把 stdout/stderr 接到控制台，方便脚本调用与重定向。
"""
from __future__ import annotations

import os
import sys


def _is_gui_launch(argv) -> bool:
    """没有任何参数（或被资源管理器双击）时开图形界面。"""
    if not argv:
        return True
    # 显式要求命令行时一律走 CLI 分支
    return False


def _attach_console() -> None:
    """在 Windows 上把标准输出接回调用方的控制台。

    用 --noconsole 打包后 stdout/stderr 是无效句柄，脚本重定向会拿到空内容；
    这里在确实有控制台时重新绑定，保证 CLI 输出可用。
    """
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        ATTACH_PARENT_PROCESS = -1
        # 已经有关联控制台就不用管；否则尝试附到父进程的控制台
        if kernel32.GetConsoleWindow() == 0:
            if not kernel32.AttachConsole(ATTACH_PARENT_PROCESS):
                return
        for index, name in ((1, "stdout"), (2, "stderr")):
            try:
                stream = open("CONOUT$", "w", encoding="utf-8", errors="replace",
                              buffering=1, closefd=True)
                setattr(sys, name, stream)
            except OSError:
                pass
        try:
            sys.stdin = open("CONIN$", "r", encoding="utf-8", errors="replace")
        except OSError:
            pass
    except Exception:
        pass


def _show_startup_error(message: str) -> None:
    """启动阶段出错时，用弹窗告诉用户（GUI 模式下没有控制台可看）。"""
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("SubFontMKV 启动失败", message)
        root.destroy()
    except Exception:
        # 连弹窗都不行就写到文件，至少留下线索
        try:
            path = os.path.join(os.path.expanduser("~"), "SubFontMKV-crash.log")
            with open(path, "a", encoding="utf-8") as fp:
                fp.write(message + "\n")
        except Exception:
            pass


def main() -> int:
    argv = sys.argv[1:]
    gui_mode = not argv

    if not gui_mode:
        _attach_console()

    try:
        if gui_mode:
            from subfontmkv.gui import launch

            return launch([])

        from subfontmkv.cli import main as cli_main

        return cli_main(argv)
    except Exception as exc:  # 打包后没有 traceback 输出，兜底提示
        import traceback

        detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        sys.stderr.write(detail)
        _show_startup_error(
            "程序启动时发生错误：\n\n{0}\n\n"
            "如果提示缺少 mkvmerge，请安装 MKVToolNix；\n"
            "详细错误信息：\n{1}".format(exc, detail.strip().splitlines()[-1] if detail.strip() else "")
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
