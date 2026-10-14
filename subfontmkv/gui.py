# -*- coding: utf-8 -*-
"""SubFontMKV 图形界面（Tkinter）。

左栏：添加视频 / 封装选项 / 开始；右栏：实时日志。
封装在后台线程执行，界面不会卡死；添加文件时会预检字幕匹配情况并以颜色标注。
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional, Tuple

from . import core
from .log import DEBUG, ERROR, INFO, WARNING, add_handler, set_level
from .mux import find_ffmpeg, find_mkvmerge

#: 可选的字幕语言（ISO-639-2）
LANGUAGE_CHOICES = [
    ("跟随文件名推断", None),
    ("未定义 und", "und"),
    ("中文 chi", "chi"),
    ("日语 jpn", "jpn"),
    ("英语 eng", "eng"),
    ("韩语 kor", "kor"),
]

#: 列表行状态 -> 标签颜色
ROW_COLORS = {
    "no-subtitle": "#c62828",   # 未匹配到字幕：不会被封装
    "ok": "#2e7d32",            # 已匹配到字幕
    "video": "#212121",         # 普通行
}

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    HAS_DND = True
except Exception:  # pragma: no cover - 可选依赖
    DND_FILES = None
    TkinterDnD = None
    HAS_DND = False


def launch(argv: Optional[List[str]] = None) -> int:
    """启动图形界面。"""
    if TkinterDnD is not None:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    app = SubFontMKVApp(root)
    if argv:
        app.add_paths(argv)
    root.mainloop()
    return 0


class SubFontMKVApp(object):
    """主窗口。"""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.entries: Dict[str, dict] = {}       # 规范化路径 -> 记录
        self.order: List[str] = []
        self.worker: Optional[threading.Thread] = None
        self.stop_flag = threading.Event()
        # Tkinter 不是线程安全的：工作线程只往队列里投消息，
        # 所有界面更新都在主线程的 _drain_queues 里执行。
        self.log_queue: "queue.Queue[Tuple[str, int]]" = queue.Queue()
        self.ui_queue: "queue.Queue[tuple]" = queue.Queue()

        root.title("SubFontMKV — 字幕与字体软封装")
        root.geometry("1240x780")
        root.minsize(1000, 640)

        self._build_widgets()
        add_handler(self._enqueue_log)
        root.after(100, self._drain_queues)
        self._log("准备就绪。把视频或文件夹拖到左侧列表（需 tkinterdnd2），或用「添加」按钮。", INFO)
        if not HAS_DND:
            self._log("未安装 tkinterdnd2，拖拽不可用（pip install tkinterdnd2 可启用）。", WARNING)
        self._log_tools()

    # ------------------------------------------------------------------
    # 界面
    # ------------------------------------------------------------------
    def _build_widgets(self) -> None:
        outer = ttk.Frame(self.root, padding=8)
        outer.pack(fill="both", expand=True)
        panes = ttk.PanedWindow(outer, orient="horizontal")
        panes.pack(fill="both", expand=True)
        left = ttk.Frame(panes, padding=(0, 0, 6, 0))
        right = ttk.Frame(panes)
        panes.add(left, weight=3)
        panes.add(right, weight=2)

        self._build_left(left)
        self._build_right(right)

        self.status_var = tk.StringVar(value="就绪")
        status = ttk.Frame(self.root)
        status.pack(fill="x", side="bottom")
        ttk.Label(status, textvariable=self.status_var, anchor="w",
                  padding=(8, 2)).pack(side="left", fill="x", expand=True)
        self.progress = ttk.Progressbar(status, mode="determinate", length=220)
        self.progress.pack(side="right", padx=8, pady=3)

    def _build_left(self, parent: ttk.Frame) -> None:
        # -- 添加视频 ---------------------------------------------------
        box = ttk.LabelFrame(parent, text="1. 添加视频", padding=6)
        box.pack(fill="both", expand=True)

        self.drop_hint = tk.Label(
            box,
            text="把视频文件或文件夹拖到这里" if HAS_DND else "拖拽不可用，请使用下方按钮添加",
            relief="ridge", bd=1, height=2, bg="#fafafa", fg="#555555",
        )
        self.drop_hint.pack(fill="x", pady=(0, 6))
        if HAS_DND:
            for widget in (self.drop_hint, box):
                try:
                    widget.drop_target_register(DND_FILES)
                    widget.dnd_bind("<<Drop>>", self._on_drop)
                    widget.dnd_bind("<<DragEnter>>", self._on_drag_enter)
                    widget.dnd_bind("<<DragLeave>>", self._on_drag_leave)
                except Exception:
                    pass

        buttons = ttk.Frame(box)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="添加视频…", command=self._pick_files).pack(side="left")
        ttk.Button(buttons, text="添加文件夹…", command=self._pick_folder).pack(side="left", padx=4)
        ttk.Button(buttons, text="移除选中", command=self._remove_selected).pack(side="left")
        ttk.Button(buttons, text="清空", command=self._clear).pack(side="left", padx=4)

        # 表格容器：Treeview 与两个滚动条都用 grid 布局
        table = ttk.Frame(box)
        table.pack(fill="both", expand=True, pady=(6, 0))
        columns = ("name", "path", "match", "status")
        self.tree = ttk.Treeview(table, columns=columns, show="headings", selectmode="extended",
                                 height=10)
        self.tree.heading("name", text="名称")
        self.tree.heading("path", text="路径")
        self.tree.heading("match", text="匹配字幕")
        self.tree.heading("status", text="状态")
        # 宽度要让「匹配字幕 / 状态」两列完整可见（不伸展，避免被路径挤掉）；
        # 路径整列放不下时可用下方横向滚动条查看。
        self.tree.column("name", width=145, anchor="w", stretch=False)
        self.tree.column("path", width=150, anchor="w", stretch=False)
        self.tree.column("match", width=178, anchor="w", stretch=True)
        self.tree.column("status", width=112, anchor="w", stretch=False)
        yscroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        self.tree.bind("<Delete>", lambda _e: self._remove_selected())
        self.tree.bind("<Double-1>", lambda _e: self._remove_selected())
        for key, color in ROW_COLORS.items():
            self.tree.tag_configure(key, foreground=color)
        self.tree.tag_configure("no-subtitle", foreground=ROW_COLORS["no-subtitle"],
                                font=("", 9, "bold"))

        # -- 选项 -------------------------------------------------------
        options = ttk.LabelFrame(parent, text="2. 封装选项", padding=6)
        options.pack(fill="x", pady=(8, 0))
        options.columnconfigure(1, weight=1)

        ttk.Label(options, text="字幕语言").grid(row=0, column=0, sticky="w", pady=2)
        self.language_var = tk.StringVar(value=LANGUAGE_CHOICES[0][0])
        combo = ttk.Combobox(options, textvariable=self.language_var, state="readonly",
                             values=[name for name, _ in LANGUAGE_CHOICES])
        combo.grid(row=0, column=1, sticky="ew", padx=4, pady=2)
        ttk.Label(options, text="输出后缀").grid(row=0, column=2, sticky="w", padx=(8, 0))
        self.suffix_var = tk.StringVar(value=".subfont")
        ttk.Entry(options, textvariable=self.suffix_var, width=12).grid(
            row=0, column=3, sticky="w", padx=4, pady=2)

        ttk.Label(options, text="额外字体目录").grid(row=1, column=0, sticky="w", pady=2)
        self.fontdir_var = tk.StringVar()
        ttk.Entry(options, textvariable=self.fontdir_var).grid(
            row=1, column=1, columnspan=2, sticky="ew", padx=4, pady=2)
        ttk.Button(options, text="浏览…", command=self._pick_font_dir).grid(
            row=1, column=3, sticky="w", padx=4)

        ttk.Label(options, text="输出目录").grid(row=2, column=0, sticky="w", pady=2)
        self.outdir_var = tk.StringVar()
        ttk.Entry(options, textvariable=self.outdir_var).grid(
            row=2, column=1, columnspan=2, sticky="ew", padx=4, pady=2)
        ttk.Button(options, text="浏览…", command=self._pick_out_dir).grid(
            row=2, column=3, sticky="w", padx=4)

        switches = ttk.Frame(options)
        switches.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        self.subset_var = tk.BooleanVar(value=True)
        self.system_fonts_var = tk.BooleanVar(value=True)
        self.infer_lang_var = tk.BooleanVar(value=True)
        self.keep_subs_var = tk.BooleanVar(value=False)
        self.recursive_var = tk.BooleanVar(value=False)
        self.dry_run_var = tk.BooleanVar(value=False)
        for index, (text, var) in enumerate([
            ("字体子集化", self.subset_var),
            ("读取系统字体", self.system_fonts_var),
            ("推断字幕语言", self.infer_lang_var),
            ("保留源字幕轨", self.keep_subs_var),
            ("文件夹递归", self.recursive_var),
            ("仅试运行", self.dry_run_var),
        ]):
            ttk.Checkbutton(switches, text=text, variable=var).grid(
                row=index // 3, column=index % 3, sticky="w", padx=(0, 12), pady=2)

        # -- 开始 -------------------------------------------------------
        run_box = ttk.LabelFrame(parent, text="3. 开始", padding=6)
        run_box.pack(fill="x", pady=(8, 0))
        self.start_button = ttk.Button(run_box, text="开始封装", command=self._start)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(run_box, text="停止", command=self._stop, state="disabled")
        self.stop_button.pack(side="left", padx=4)
        ttk.Button(run_box, text="打开输出目录", command=self._open_output).pack(side="left", padx=4)

    def _build_right(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text="日志", padding=6)
        box.pack(fill="both", expand=True)
        self.log_text = tk.Text(box, wrap="none", height=24, background="#1e1e1e",
                                foreground="#e0e0e0", insertbackground="#e0e0e0",
                                font=("Consolas", 9))
        yscroll = ttk.Scrollbar(box, orient="vertical", command=self.log_text.yview)
        xscroll = ttk.Scrollbar(box, orient="horizontal", command=self.log_text.xview)
        self.log_text.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        box.rowconfigure(0, weight=1)
        box.columnconfigure(0, weight=1)
        for tag, color in (("INFO", "#e0e0e0"), ("WARNING", "#ffcc66"),
                           ("ERROR", "#ff6b6b"), ("DEBUG", "#8a8a8a")):
            self.log_text.tag_configure(tag, foreground=color)

        buttons = ttk.Frame(box)
        buttons.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        ttk.Button(buttons, text="复制全部", command=self._copy_log).pack(side="left")
        ttk.Button(buttons, text="清空日志", command=self._clear_log).pack(side="left", padx=4)

    # ------------------------------------------------------------------
    # 日志
    # ------------------------------------------------------------------
    def _enqueue_log(self, text: str, level: int) -> None:
        self.log_queue.put((text, level))

    def _drain_queues(self) -> None:
        try:
            while True:
                text, level = self.log_queue.get_nowait()
                self._append_log(text, level)
        except queue.Empty:
            pass
        try:
            while True:
                self._handle_ui_event(self.ui_queue.get_nowait())
        except queue.Empty:
            pass
        self.root.after(100, self._drain_queues)

    def _handle_ui_event(self, event: tuple) -> None:
        kind = event[0]
        if kind == "progress":
            self._update_progress(event[1], event[2])
        elif kind == "finished":
            self._on_finished(event[1])
        elif kind == "failed":
            self._on_failed(event[1])
        elif kind == "status":
            self.status_var.set(event[1])

    def _append_log(self, text: str, level: int) -> None:
        tag = {DEBUG: "DEBUG", INFO: "INFO", WARNING: "WARNING", ERROR: "ERROR"}.get(level, "INFO")
        self.log_text.insert("end", text + "\n", tag)
        self.log_text.see("end")

    def _log(self, text: str, level: int = INFO) -> None:
        self._append_log(text, level)

    def _clear_log(self) -> None:
        self.log_text.delete("1.0", "end")

    def _copy_log(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self.log_text.get("1.0", "end"))

    def _log_tools(self) -> None:
        mkv = find_mkvmerge()
        ff = find_ffmpeg()
        self._log("mkvmerge: {0}".format(mkv or "未找到（将回退 ffmpeg）"),
                  INFO if mkv else WARNING)
        self._log("ffmpeg:   {0}".format(ff or "未找到"), INFO if ff else WARNING)
        if not mkv and not ff:
            self._log("既没有 mkvmerge 也没有 ffmpeg，无法封装。请安装 MKVToolNix。", ERROR)

    # ------------------------------------------------------------------
    # 添加 / 移除
    # ------------------------------------------------------------------
    def _on_drag_enter(self, _event):
        self.drop_hint.configure(bg="#dbeafe", fg="#1d4ed8")
        return "copy"

    def _on_drag_leave(self, _event):
        self.drop_hint.configure(bg="#fafafa", fg="#555555")
        return "copy"

    def _on_drop(self, event):
        self.drop_hint.configure(bg="#fafafa", fg="#555555")
        paths = self.root.tk.splitlist(event.data)
        self.add_paths(list(paths))
        return "copy"

    def _pick_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="选择视频文件",
            filetypes=[("视频文件", "*.mkv *.mp4 *.ts *.m2ts *.mts *.avi *.mov *.webm *.flv"),
                       ("所有文件", "*.*")],
        )
        if paths:
            self.add_paths(list(paths))

    def _pick_folder(self) -> None:
        path = filedialog.askdirectory(title="选择包含视频的文件夹")
        if path:
            self.add_paths([path])

    def _pick_font_dir(self) -> None:
        path = filedialog.askdirectory(title="选择额外字体目录")
        if path:
            current = self.fontdir_var.get().strip()
            self.fontdir_var.set("{0}{1}{2}".format(current, os.pathsep, path) if current else path)

    def _pick_out_dir(self) -> None:
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.outdir_var.set(path)

    def add_paths(self, paths: List[str]) -> None:
        """把文件/文件夹加入列表。

        目录展开复用 core.collect_videos，保证与命令行一致（包括跳过本工具
        自己的产物），不会出现 GUI 与 CLI 行为不一致的问题。
        """
        recursive = self.recursive_var.get()
        suffix = self.suffix_var.get().strip()
        videos: List[str] = []
        empty_dirs: List[str] = []
        for raw in paths:
            real = os.path.abspath(raw)
            if os.path.isfile(real):
                videos.append(real)
                continue
            if not os.path.isdir(real):
                self._log("路径不存在: {0}".format(real), WARNING)
                continue
            before = len(videos)
            videos.extend(core.collect_videos([real], recursive=recursive, suffix=suffix))
            if len(videos) == before:
                empty_dirs.append(real)
        for directory in empty_dirs:
            self._log("文件夹里没有可用的视频文件: {0}".format(directory), WARNING)
        added = 0
        for video in videos:
            if self._insert_video(video):
                added += 1
        self._refresh_summary()
        if added:
            self._log("已添加 {0} 个视频。".format(added), INFO)
        elif videos:
            self._log("这些视频已经在列表里了。", INFO)
        else:
            self._log("没有找到视频文件。", WARNING)

    def _insert_video(self, video: str) -> bool:
        key = os.path.normcase(os.path.abspath(video))
        if key in self.entries:
            return False
        record = {"video": os.path.abspath(video), "status": "", "match": "", "node": None}
        self.entries[key] = record
        self.order.append(key)
        self._recheck(record)
        self._insert_node(record)
        return True

    def _insert_node(self, record: dict) -> None:
        video = record["video"]
        tag = record.get("tag", "video")
        node = self.tree.insert(
            "", "end",
            values=(os.path.basename(video), os.path.dirname(video),
                    record.get("match", ""), record.get("status", "")),
            tags=(tag,),
        )
        record["node"] = node

    def _recheck(self, record: dict) -> None:
        """预检字幕匹配情况。"""
        video = record["video"]
        options = self._collect_options(for_check=True)
        try:
            matches = core.match_subtitles(video, options)
        except Exception as exc:
            record.update(status="预检失败: {0}".format(exc), match="-", tag="no-subtitle")
            return
        if not matches:
            record.update(status="未匹配到字幕", match="0 条", tag="no-subtitle")
        else:
            names = "、".join(
                "{0}{1}".format(os.path.splitext(os.path.basename(m.path))[0][-12:],
                                " [{0}]".format(m.language) if m.language else "")
                for m in matches[:3]
            )
            if len(matches) > 3:
                names += " 等 {0} 条".format(len(matches))
            record.update(status="可以封装", match="{0} 条: {1}".format(len(matches), names), tag="ok")

    def _refresh_record(self, record: dict) -> None:
        node = record.get("node")
        if node is None or not self.tree.exists(node):
            return
        video = record["video"]
        self.tree.item(node, values=(os.path.basename(video), os.path.dirname(video),
                                     record.get("match", ""), record.get("status", "")),
                       tags=(record.get("tag", "video"),))

    def _remove_selected(self) -> None:
        for node in self.tree.selection():
            values = self.tree.item(node, "values")
            if not values:
                continue
            path = os.path.join(values[1], values[0])
            key = os.path.normcase(os.path.abspath(path))
            self.tree.delete(node)
            self.entries.pop(key, None)
            if key in self.order:
                self.order.remove(key)
        self._refresh_summary()

    def _clear(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.entries.clear()
        self.order.clear()
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        total = len(self.order)
        missing = sum(1 for k in self.order if self.entries[k].get("tag") == "no-subtitle")
        if total == 0:
            self.status_var.set("就绪")
        elif missing:
            self.status_var.set("共 {0} 个视频，其中 {1} 个未匹配到字幕".format(total, missing))
        else:
            self.status_var.set("共 {0} 个视频，全部匹配到字幕".format(total))

    # ------------------------------------------------------------------
    # 运行
    # ------------------------------------------------------------------
    def _collect_options(self, for_check: bool = False) -> core.Options:
        options = core.Options()
        label = self.language_var.get()
        for name, code in LANGUAGE_CHOICES:
            if name == label:
                # 选择「跟随文件名推断」时才启用推断，否则固定用所选语言
                options.language = code or "und"
                options.infer_language = (code is None) and self.infer_lang_var.get()
                break
        options.suffix = self.suffix_var.get().strip()
        options.font_dirs = [p for p in self.fontdir_var.get().split(os.pathsep) if p.strip()]
        options.output_dir = self.outdir_var.get().strip() or None
        options.subset = self.subset_var.get()
        options.system_fonts = self.system_fonts_var.get()
        options.keep_source_subs = self.keep_subs_var.get()
        options.recursive = self.recursive_var.get()
        options.dry_run = False if for_check else self.dry_run_var.get()
        options.attach_full_fonts = not options.subset
        return options

    def _start(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            return
        paths = [self.entries[k]["video"] for k in self.order if k in self.entries]
        if not paths:
            messagebox.showinfo("SubFontMKV", "请先添加视频文件。")
            return
        missing = [k for k in self.order if self.entries[k].get("tag") == "no-subtitle"]
        if missing:
            ok = messagebox.askyesno(
                "有视频没有字幕",
                "有 {0} 个视频未匹配到外挂字幕，这些视频会被跳过。\n仍要继续吗？".format(len(missing)),
            )
            if not ok:
                return
        options = self._collect_options()
        self.stop_flag.clear()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.progress.configure(maximum=len(paths), value=0)
        self._log("-" * 70, INFO)
        self._log("开始处理 {0} 个视频…".format(len(paths)), INFO)
        self.worker = threading.Thread(
            target=self._run_worker, args=(paths, options),
            name="subfontmkv-worker", daemon=True)
        self.worker.start()

    def _run_worker(self, paths: List[str], options: core.Options) -> None:
        """工作线程：只做计算，界面更新一律通过队列交给主线程。"""

        def on_event(kind: str, job: core.Job, index: int, total: int) -> None:
            if kind == "done":
                level = INFO if job.status in ("ok", "dry-run") else WARNING
                self.log_queue.put((
                    "  -> {0}: {1}".format(job.status, job.output or job.message), level))
            self.ui_queue.put(("progress", index, total))

        try:
            set_level(DEBUG)
            summary = core.run(paths, options, on_event=on_event,
                               should_stop=self.stop_flag.is_set)
            self.ui_queue.put(("finished", summary))
        except Exception as exc:
            self.ui_queue.put(("failed", exc))

    def _update_progress(self, index: int, total: int) -> None:
        self.progress.configure(maximum=total, value=index)
        self.status_var.set("正在处理 {0}/{1}".format(index, total))

    def _on_finished(self, summary) -> None:
        set_level(INFO)
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.status_var.set("完成: 成功 {0} / 跳过 {1} / 失败 {2}".format(
            summary["ok"], summary["skipped"], summary["failed"]))
        for key in self.order:
            record = self.entries.get(key)
            if record:
                record["status"] = "已处理"
                self._refresh_record(record)
        if summary["failed"]:
            messagebox.showwarning("SubFontMKV", "有 {0} 个视频处理失败，请查看日志。".format(
                summary["failed"]))
        else:
            messagebox.showinfo("SubFontMKV", "处理完成：成功 {0}，跳过 {1}。".format(
                summary["ok"], summary["skipped"]))

    def _on_failed(self, exc: Exception) -> None:
        set_level(INFO)
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self._log("运行失败: {0}".format(exc), ERROR)
        messagebox.showerror("SubFontMKV", "运行失败：\n{0}".format(exc))

    def _stop(self) -> None:
        self.stop_flag.set()
        self._log("已请求停止，当前文件处理完后中断。", WARNING)

    def _open_output(self) -> None:
        target = self.outdir_var.get().strip()
        if not target:
            for key in self.order:
                record = self.entries.get(key)
                if record and record.get("status") == "已处理":
                    target = os.path.dirname(record["video"])
                    break
        if not target or not os.path.isdir(target):
            messagebox.showinfo("SubFontMKV", "还没有可打开的输出目录。")
            return
        if os.name == "nt":
            os.startfile(target)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", target])
        else:
            subprocess.Popen(["xdg-open", target])


def main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover
    return launch(argv)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
