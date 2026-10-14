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

# ---- 拖拽区域：提示文字为蓝色高亮，且旧的拖拽占位框已移除 ----
print("8 拖拽提示:", repr(app.drop_hint.cget("text")))
assert app.drop_hint.cget("foreground") == gui.DROP_HINT_COLOR, app.drop_hint.cget("foreground")
assert "拖" in app.drop_hint.cget("text") and "文件夹" in app.drop_hint.cget("text")
assert not hasattr(app, "drop_hint_box"), "旧的拖拽区域控件应该已经删除"
print("   颜色:", app.drop_hint.cget("foreground"), "字体:", app.drop_hint.cget("font"))

# 悬停状态机：只在状态变化时改样式（拖拽过程重复 enter 不应反复 configure）
assert app._drag_hover is False
app._on_drag_enter(None)
assert app._drag_hover is True and app._drop_box.cget("style") == "DropHover.TLabelframe"
app._on_drag_leave(None)
assert app._drag_hover is False and app._drop_box.cget("style") == "TLabelframe"

calls = []
orig_cfg = tk.Widget.configure
def spy(self, cnf=None, **kw):
    calls.append(kw)
    return orig_cfg(self, cnf, **kw)
tk.Widget.configure = spy
import tkinter.ttk as _ttk
_ttk.Widget.configure = spy
try:
    # 先让状态真正进入「悬停」，再观察后续重复 enter 的开销
    app._on_drag_enter(None)
    del calls[:]
    for _ in range(300):
        app._on_drag_enter(None)
    assert calls == [], "已高亮时重复 DragEnter 不应做多余的 configure：%r" % calls[:3]
finally:
    tk.Widget.configure = orig_cfg
    _ttk.Widget.configure = orig_cfg
print("9 悬停高亮 OK（300 次重复 DragEnter 零重绘）")

# 提示文字随宽度换行，窄窗口不会撑破布局。
# 宽度更新被推迟到 idle（避免每帧都重排），这里要跑一次 update 让它生效。
app._on_hint_resize(type("E", (), {"width": 300})())
root.update()
assert int(app.drop_hint.cget("wraplength")) <= 300, app.drop_hint.cget("wraplength")
print("10 提示自动换行 OK, wraplength =", app.drop_hint.cget("wraplength"))

# ---- 提示是「添加视频」区域内部的空状态占位，与列表互斥 ----
def _hint_shown():
    return app.drop_hint.grid_info() != {}

def _tree_shown():
    return app.tree.grid_info() != {}

# 提示必须位于「1. 添加视频」这块 LabelFrame 内
container = app.drop_hint.master
chain_texts = []
node = container
while node is not None and node is not root:
    try:
        if node.winfo_class() == "TLabelframe":
            chain_texts.append(str(node.cget("text")))
    except Exception:
        pass
    node = getattr(node, "master", None)
assert any("添加视频" in t for t in chain_texts), chain_texts
print("11 提示位于「添加视频」区域内 OK, 容器标题:", chain_texts)

app._clear(); root.update()
assert _hint_shown() and not _tree_shown(), (_hint_shown(), _tree_shown())
app.add_paths([os.path.join(ROOT, "test-assets", "Show EP01.mkv")]); root.update()
assert not _hint_shown() and _tree_shown(), (_hint_shown(), _tree_shown())
app._clear(); root.update()
assert _hint_shown() and not _tree_shown(), (_hint_shown(), _tree_shown())
print("12 提示/列表互斥 OK（空列表显示提示 -> 有文件换成列表 -> 清空恢复）")

# ---- 模拟一次真实拖放：Tk 对含空格的路径会用花括号包裹 ----
drop_dir = tempfile.mkdtemp(prefix="drop-")
drop_videos = []
for i in range(3):
    p = os.path.join(drop_dir, "My Video %d.mkv" % i)
    with open(p, "wb") as fp:
        fp.write(b"x")
    with open(os.path.join(drop_dir, "My Video %d.chs.ass" % i), "w", encoding="utf-8"):
        pass
    drop_videos.append(p)

class _FakeDrop:
    data = " ".join("{%s}" % v for v in drop_videos)

app._clear()
app._on_drag_enter(None)
assert app._drag_hover is True
app._on_drop(_FakeDrop())
assert len(app.order) == 3, app.order
assert app._drag_hover is False, "放下后应恢复高亮"
assert all(app.entries[k]["tag"] == "ok" for k in app.order)
print("13 模拟拖放 OK（含空格路径的花括号列表格式）")

# ---- 批量拖入性能：不再为每个视频重复扫描目录 ----
bulk = tempfile.mkdtemp(prefix="bulk-")
BULK_N = 200
for i in range(BULK_N):
    with open(os.path.join(bulk, "EP%03d.mkv" % i), "wb") as fp:
        fp.write(b"x")
    with open(os.path.join(bulk, "EP%03d.chs.ass" % i), "w", encoding="utf-8"):
        pass
app._clear()
t0 = time.perf_counter()
app.add_paths([bulk])
bulk_dt = time.perf_counter() - t0
print("14 拖入 %d 个视频耗时 %.3fs（%.0f 个/秒）" % (BULK_N, bulk_dt, BULK_N / bulk_dt))
assert len(app.order) == BULK_N
assert bulk_dt < 3.0, "批量添加太慢: %.3fs" % bulk_dt
shutil.rmtree(bulk, ignore_errors=True)



# ---- 日志：行数受限、自动滚动只在贴底时生效 ----
app._clear_log()
for i in range(gui.LOG_MAX_LINES * 3):
    app._append_log("log line %d" % i, 20)
root.update()
kept_lines = int(app.log_text.index("end-1c").split(".")[0])
assert kept_lines <= gui.LOG_MAX_LINES + 1, kept_lines
print("15 日志行数上限 OK（写入 %d 行，控件保留 %d 行）"
      % (gui.LOG_MAX_LINES * 3, kept_lines))

assert app._log_at_bottom() is True, "刚写完应贴底"
app.log_text.yview_moveto(0.0)
root.update()
assert app._log_at_bottom() is False
app._append_log("追加一行", 20)
root.update()
assert app.log_text.yview()[0] < 0.5, "用户上翻后不应被强行拉到底部"
print("16 日志滚动 OK（贴底才跟随，上翻不打扰）")

# ---- 日志自动换行：超长行（mkvmerge 命令行 / 完整路径）不应横向溢出 ----
app._clear_log()
long_line = ("--no-subtitles --no-attachments H:\\软件\\SubFontMKV\\test-assets\\Show EP01.mkv "
             "--track-name 0:chs --language 0:chi "
             + " ".join("--attach-file 字体%02d.ttf" % str_tmpl for str_tmpl in range(20)))
app._append_log(long_line, 20)
root.update()
assert app.log_text.cget("wrap") == "word", app.log_text.cget("wrap")
disp = app.log_text.count("1.0", "end", "displaylines")[0]
xview = app.log_text.xview()
assert disp > 3, "超长行应换行成多行显示，实际 %d" % disp
assert xview[0] == 0.0 and xview[1] >= 0.999, "不应再有横向溢出: %r" % (xview,)
print("17 日志自动换行 OK（1 个逻辑行 -> %d 个显示行，无横向溢出）" % disp)

# 无空格的中文长路径也要能断开
app._clear_log()
app._append_log("H:\\软件\\SubFontMKV\\" + "很长的中文目录名\\" * 12 + "文件.ass", 20)
root.update()
assert app.log_text.count("1.0", "end", "displaylines")[0] > 2, "中文长路径应能换行"
print("18 中文长路径也能换行 OK")

# ---- 批量日志插入远快于逐行（防卡顿的核心）----
app._clear_log()
entries = [("bulk line %d" % i, 20) for i in range(2000)]
t0 = time.perf_counter()
app._append_log_batch(entries)
batch_dt = time.perf_counter() - t0
print("19 批量写入 2000 行日志: %.3fs" % batch_dt)
assert batch_dt < 0.5, "批量写入过慢: %.3fs" % batch_dt

# ---- 实时进度：进度条刻度 & 状态栏百分比 ----
app.progress.configure(maximum=300, value=0)
app._update_file_progress(45, "Show.mkv", 2, 3)
assert app.progress["value"] == 145, app.progress["value"]
assert "2/3" in app.status_var.get() and "45%" in app.status_var.get(), app.status_var.get()
print("20 单文件进度折算 OK（第 2/3 个文件的 45%% -> 进度条 %d/%d，状态栏 %r）"
      % (app.progress["value"], app.progress["maximum"], app.status_var.get()))

# start 事件只推进到 index-1，结束时才补齐，避免未开始就显示完成
app.progress.configure(maximum=300, value=0)
app._update_progress(2, 3, True)
assert app.progress["value"] == 100, app.progress["value"]
app._update_progress(2, 3, False)
assert app.progress["value"] == 200, app.progress["value"]
print("21 整文件进度推进 OK（开始 %d -> 结束 %d）" % (100, app.progress["value"]))

app._finish_progress()
assert app.progress["value"] == app.progress["maximum"]
print("22 完成后进度条填满 OK")

# 界面确实能渲染（不弹窗，只做一次布局计算）
root2 = tk.Tk(); root2.withdraw()
app2 = gui.SubFontMKVApp(root2)
root2.update_idletasks()
print("23 界面布局计算 OK, 列表列数 =", len(app2.tree["columns"]))
root2.destroy()
shutil.rmtree(drop_dir, ignore_errors=True)
root.destroy()
shutil.rmtree(work, ignore_errors=True); shutil.rmtree(empty, ignore_errors=True)
print("\nGUI CHECKS PASSED")
