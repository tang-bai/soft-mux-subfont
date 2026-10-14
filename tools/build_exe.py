# -*- coding: utf-8 -*-
"""一键打包 Windows 可执行文件。

用法（在项目根目录执行）：
    python tools/build_exe.py              # 打包
    python tools/build_exe.py --console    # 顺便保留控制台窗口（调试用）
    python tools/build_exe.py --clean      # 打包前清掉 build/ dist/

产物：dist/SubFontMKV.exe
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join(ROOT, "packaging", "SubFontMKV.spec")
DIST = os.path.join(ROOT, "dist")
BUILD = os.path.join(ROOT, "build")


def main() -> int:
    parser = argparse.ArgumentParser(description="打包 SubFontMKV 为单文件 exe")
    parser.add_argument("--clean", action="store_true", help="打包前清理 build/ 与 dist/")
    parser.add_argument("--console", action="store_true",
                        help="保留控制台窗口（便于排查启动问题）")
    parser.add_argument("--no-icon", action="store_true",
                        help="不使用自定义图标")
    args = parser.parse_args()

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("未安装 PyInstaller。请先执行：\n    pip install pyinstaller", file=sys.stderr)
        return 1

    if args.clean:
        for path in (BUILD, DIST):
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
                print("已清理:", path)

    # 注意：给了 .spec 文件后，--console/--windowed 这类 makespec 选项不再允许，
    # 它们已经在 spec 的 EXE(...) 里写死了。这里用环境变量传「是否保留控制台」。
    env = dict(os.environ)
    env["SUBFONTMKV_CONSOLE"] = "1" if args.console else "0"
    env["SUBFONTMKV_NOICON"] = "1" if args.no_icon else "0"

    command = [
        sys.executable, "-m", "PyInstaller",
        SPEC,
        "--noconfirm",
        "--distpath", DIST,
        "--workpath", BUILD,
    ]

    print("执行:", " ".join(command))
    result = subprocess.run(command, cwd=ROOT, env=env)
    if result.returncode != 0:
        print("\n打包失败（返回码 %d）" % result.returncode, file=sys.stderr)
        return result.returncode

    exe = os.path.join(DIST, "SubFontMKV.exe")
    if not os.path.exists(exe):
        print("\n未找到产物:", exe, file=sys.stderr)
        return 1

    # 顺带打一个发布包：exe + 便携版说明
    import zipfile

    release_dir = os.path.join(ROOT, "release")
    os.makedirs(release_dir, exist_ok=True)
    zip_path = os.path.join(release_dir, "SubFontMKV-1.0.0-portable-win64.zip")
    note = os.path.join(ROOT, "packaging", "PORTABLE-README.txt")
    icon = os.path.join(ROOT, "packaging", "icon.ico")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(exe, "SubFontMKV/SubFontMKV.exe")
        if os.path.exists(note):
            zf.write(note, "SubFontMKV/使用说明.txt")
        if os.path.exists(icon):
            zf.write(icon, "SubFontMKV/SubFontMKV.ico")

    size_mb = os.path.getsize(exe) / (1024 * 1024)
    zip_mb = os.path.getsize(zip_path) / (1024 * 1024)
    print()
    print("=" * 60)
    print("打包完成: %s" % exe)
    print("体积: %.1f MB" % size_mb)
    print("发布包: %s (%.1f MB)" % (zip_path, zip_mb))
    print("=" * 60)
    print()
    print("提示:")
    print("  * 目标是「图形界面程序」：双击直接开界面，可把视频/文件夹拖进去。")
    print("  * 也支持命令行：SubFontMKV.exe \"目录\" --recursive")
    print("  * 运行需要 MKVToolNix（mkvmerge）。用户机器上装好即可，exe 不含它。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
