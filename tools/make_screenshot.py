# -*- coding: utf-8 -*-
"""生成 README 用的界面截图。"""
import os, sys, time, tempfile, shutil
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tkinter as tk
from PIL import ImageGrab
from subfontmkv import gui
from subfontmkv.log import INFO, WARNING

root = tk.Tk()
app = gui.SubFontMKVApp(root)
root.geometry("1240x780+60+40")
app.fontdir_var.set(os.path.join(ROOT, "test-assets", "fonts"))
app.suffix_var.set(".subfont")
app.system_fonts_var.set(False)
# 截图取启动时的空列表状态，这样能看到「添加视频」区域里的蓝色拖拽提示

demo = [
    (INFO, "mkvmerge: C:\\Program Files\\MKVToolNix\\mkvmerge.exe"),
    (INFO, "ffmpeg:   C:\\Program Files\\ffmpeg\\bin\\ffmpeg.exe"),
    (INFO, "字体索引就绪，共 2861 个字体名。"),
    (INFO, "封装器: mkvmerge (C:\\Program Files\\MKVToolNix\\mkvmerge.exe)"),
    (INFO, "[1/3] Show EP01.mkv"),
    (INFO, "匹配到 2 条字幕:"),
    (INFO, "  - Show EP01.chs.ass  [chi]"),
    (INFO, "  - Show EP01.jpn.ass  [jpn]"),
    (INFO, "  子集化字体: SubFontTest CJK.60A1B3E9.ttf (128 字)"),
    (INFO, "  子集化字体: SubFontTest Sans_Bold.5E14DFF2.ttf (64 字)"),
    # 实时进度：mkvmerge 每 0.5 秒左右上报一次，日志与进度条同步更新
    (INFO, "  Show EP01.mkv 封装中 0%"),
    (INFO, "  Show EP01.mkv 封装中 18%"),
    (INFO, "  Show EP01.mkv 封装中 39%"),
    (INFO, "  Show EP01.mkv 封装中 61%"),
    (INFO, "  Show EP01.mkv 封装中 83%"),
    (INFO, "  Show EP01.mkv 封装中 100%"),
    # 故意放一条超长的 mkvmerge 参数行，用来展示日志自动换行
    (INFO, "mkvmerge 参数: [--no-subtitles, --no-attachments, "
           "H:\\软件\\SubFontMKV\\test-assets\\Show EP01.mkv, --track-name, 0:chs, "
           "--language, 0:chi, --track-name, 0:jpn, --language, 0:jpn, "
           "--attach-file, SubFontTest CJK.60A1B3E9.ttf, --title, Show EP01]"),
    (INFO, "封装完成: test-assets\\Show EP01.subfont.mkv"),
    (INFO, "[2/3] Show EP02.mkv"),
    (WARNING, "以下字体未找到，将不在 MKV 中内嵌: GhostFont NoSuch"),
    (INFO, "  子集化字体: SubFontTest CJK.1A2B3C4D.ttf (96 字)"),
    (INFO, "  Show EP02.mkv 封装中 0%"),
    (INFO, "  Show EP02.mkv 封装中 45%"),
    (INFO, "封装完成: test-assets\\Show EP02.subfont.mkv"),
    (INFO, "跳过（未匹配到字幕）: NoSubtitle.mkv"),
    (INFO, "完成: 成功 2 / 试运行 0 / 跳过 1 / 失败 0"),
]
app._clear_log()
for level, text in demo:
    app._append_log(text, level)
app.status_var.set("正在处理 2/3 — Show EP02.mkv  45%")
app.progress.configure(maximum=300, value=145)
root.update_idletasks(); root.update()
root.lift(); root.attributes("-topmost", True); root.update(); time.sleep(0.7)
root.update()
x, y = root.winfo_rootx(), root.winfo_rooty()
w, h = root.winfo_width(), root.winfo_height()
ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(os.path.join(ROOT, "gui-screenshot.png"))
print("saved", (w, h))
root.attributes("-topmost", False)
root.destroy()
