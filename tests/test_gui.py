# -*- coding: utf-8 -*-
"""GUI 验证：窗口构建、字幕预检、后台线程、封装、空目录提示。

用法:
    python tests/test_gui.py
需要图形环境（Windows 上直接可跑）。
"""
import os, sys, time, shutil, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tkinter as tk
import tkinter.messagebox as mb
seen = []
mb.showinfo = lambda *a, **k: seen.append(("info", a))
mb.showwarning = lambda *a, **k: seen.append(("warn", a))
mb.showerror = lambda *a, **k: seen.append(("error", a))
mb.askyesno = lambda *a, **k: True

from subfontmkv import gui

root = tk.Tk(); root.withdraw()
app = gui.SubFontMKVApp(root)
print("1 构建 OK")

work = tempfile.mkdtemp(prefix="guifinal-")
app.fontdir_var.set(os.path.join(ROOT, "test-assets", "fonts"))
app.outdir_var.set(work)
app.system_fonts_var.set(False)
app.suffix_var.set(".f")

# 空目录提示
empty = tempfile.mkdtemp(prefix="empty-")
app.add_paths([empty])
log = app.log_text.get("1.0", "end")
assert "文件夹里没有可用的视频文件" in log, log[-300:]
print("2 空目录提示 OK")

# 预检：有字幕的标绿，没字幕的标红
app.add_paths([os.path.join(ROOT, "test-assets", "Show EP01.mkv")])
app.add_paths([os.path.join(ROOT, "test-assets", "batch", "NoSubtitle.mkv")])
tags = [app.entries[k]["tag"] for k in app.order]
print("3 预检标签:", tags)
assert "ok" in tags and "no-subtitle" in tags, tags

app.recursive_var.set(True)
before = len(app.order)
app.add_paths([os.path.join(ROOT, "test-assets")])
after = len(app.order)
print("4 递归添加前后:", before, "->", after)
assert after > before, "递归应找到更多视频"
assert len({app.entries[k]["video"] for k in app.order}) == after, "不应有重复条目"

# 只留一个有效视频来跑完整流程
app._clear()
app.add_paths([os.path.join(ROOT, "test-assets", "Show EP01.mkv")])
app._start()
t0 = time.time()
while time.time() - t0 < 90:
    root.update()
    if not app.worker.is_alive() and app.start_button["state"] == "normal":
        break
    time.sleep(0.05)
for _ in range(30):
    root.update(); time.sleep(0.03)
print("5 状态:", app.status_var.get())
out = os.listdir(work)
print("6 输出:", out)
assert any(n.endswith(".mkv") for n in out), out
assert app.status_var.get().startswith("完成: 成功 1"), app.status_var.get()
assert seen and seen[-1][0] == "info", seen
print("7 完成回调 OK")

# 界面确实能渲染（不弹窗，只做一次布局计算）
root2 = tk.Tk(); root2.withdraw()
app2 = gui.SubFontMKVApp(root2)
root2.update_idletasks()
print("8 界面布局计算 OK, 列表列数 =", len(app2.tree["columns"]))
root2.destroy()
root.destroy()
shutil.rmtree(work, ignore_errors=True); shutil.rmtree(empty, ignore_errors=True)
print("\nGUI CHECKS PASSED")
