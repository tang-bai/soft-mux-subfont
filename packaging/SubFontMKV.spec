# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置。

用法：
    python tools/build_exe.py            # 一键打包（推荐）
    pyinstaller packaging/SubFontMKV.spec --noconfirm

要点：
  * 单文件（onefile）方便迁移，双击即用；
  * --noconsole 让 GUI 模式不弹黑框，命令行输出由 entry.py 里的
    AttachConsole 逻辑接回控制台；
  * tkinterdnd2 的 tkdnd 目录要随包带上，且只带 win-x64 / win-x64-tcl9 ——
    它按 __file__ 相对定位，多余平台的 DLL 白白增加体积。
"""
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))

# 由 tools/build_exe.py 通过环境变量传入（给 .spec 时不能再传 --windowed 这类开关）
KEEP_CONSOLE = os.environ.get("SUBFONTMKV_CONSOLE") == "1"
NO_ICON = os.environ.get("SUBFONTMKV_NOICON") == "1"

datas = []
binaries = []
hiddenimports = []

# --------------------------------------------------------------------------
# tkinterdnd2：只保留当前平台用得到的 tkdnd 资源
# --------------------------------------------------------------------------
try:
    import tkinterdnd2

    pkg_dir = os.path.dirname(os.path.abspath(tkinterdnd2.__file__))
    # 只带当前操作系统对应的目录，减少体积
    current_os = {"win32": "win", "linux": "linux", "darwin": "osx"}.get(sys.platform, "win")
    tkdnd_root = os.path.join(pkg_dir, "tkdnd")
    if os.path.isdir(tkdnd_root):
        for name in sorted(os.listdir(tkdnd_root)):
            full = os.path.join(tkdnd_root, name)
            if not os.path.isdir(full):
                continue
            if not name.startswith(current_os):
                continue
            for dirpath, _dirs, files in os.walk(full):
                for fname in files:
                    src = os.path.join(dirpath, fname)
                    rel = os.path.relpath(src, pkg_dir)
                    datas.append((src, os.path.dirname(rel)))
        print("[spec] tkdnd 资源条目: %d" % len(datas))
    hiddenimports.append("tkinterdnd2")
    hiddenimports.append("tkinterdnd2.TkinterDnD")
except ImportError:
    print("[spec] 未安装 tkinterdnd2，打包后的界面将不支持拖拽")

# --------------------------------------------------------------------------
# fontTools：子集化会按需 import 各类表，显式收集避免漏掉
# --------------------------------------------------------------------------
hiddenimports += collect_submodules("fontTools")

# --------------------------------------------------------------------------
# 可选：更好的字幕编码识别
# --------------------------------------------------------------------------
for name in ("charset_normalizer", "chardet"):
    try:
        __import__(name)
        hiddenimports += collect_submodules(name)
        hiddenimports.append(name)
    except ImportError:
        pass

# 明确排除用不到的大块头，控制体积
# 只排除确定用不到的大块头；像 unittest/distutils 这类可能被间接 import 的
# 标准库不动，避免打包后出现莫名其妙的 ImportError。
excludes = [
    "numpy", "pandas", "scipy", "matplotlib", "PIL", "pytest",
    "IPython", "notebook", "PyQt5", "PyQt6", "PySide2", "PySide6",
    "wx", "lib2to3", "pydoc_data",
]

a = Analysis(
    [os.path.join(ROOT, "packaging", "entry.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="SubFontMKV",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    # GUI 程序默认不弹黑框；命令行输出由 entry.py 里的 AttachConsole 接回控制台。
    # 用 --console 打包则保留控制台窗口，方便排查启动问题。
    console=KEEP_CONSOLE,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT, "packaging", "icon.ico")
    if (not NO_ICON and os.path.exists(os.path.join(ROOT, "packaging", "icon.ico"))) else None,
)
