# SubFontMKV

把**外挂字幕和字体软封装进 MKV**：字幕成为可开关的软字幕轨，字体作为附件（attachment）内嵌，
播放器会优先使用内嵌的子集字体，因此在任何机器上都能正确显示字幕样式。

本项目在 GitHub 上现有的同类项目基础上修改而成，基础项目为
**[DYY-Studio/AddSubFontMKV_py](https://github.com/DYY-Studio/AddSubFontMKV_py)**（Apache-2.0）。
源码经由 `https://git.tangbai.cc` 代理获取。

---

## 为什么选择这个基础项目

调研过 GitHub 上的同类项目：

| 项目 | 语言 | 说明 | 是否采用 |
| --- | --- | --- | --- |
| [DYY-Studio/AddSubFontMKV_py](https://github.com/DYY-Studio/AddSubFontMKV_py) | Python | 字体子集化 + mkvmerge/ffmpeg 封装，逻辑最完整 | ✅ **基础项目** |
| [MkvAutoSubset/MkvAutoSubset](https://github.com/MkvAutoSubset/MkvAutoSubset) | Go | 功能强但需编译，体积大（78MB） | ✖ |
| [DYY-Studio/AddSubFont-to-MKV](https://github.com/DYY-Studio/AddSubFont-to-MKV) | Batch | 该项目的前身，已被取代 | ✖ |
| [Danyuyuyuyu/mux-deck](https://github.com/Danyuyuyuyu/mux-deck) | JS/Python | Web UI，较重 | ✖ |

选它的原因：**字体子集化 + 名称改写（CRC32 后缀）** 的方案已经过长期验证，能避免播放器错误地
使用系统里同名的完整字体。

## 相对基础项目的改动

原项目是 PyQt5 GUI、强依赖 Windows 注册表，且用 `os.system` 拼接命令行。本项目在其思路基础上重写：

1. **库 + CLI 分离**，去掉 PyQt5 / colorama / chardet 依赖，跨平台可用（Windows / Linux / macOS）。
2. **纯 Python 字体扫描**，不再依赖 Windows 注册表，改用 `fontTools` 直接读取字体表。
3. **`subprocess` 调用外部程序**，杜绝 `os.system` 的引号转义与命令注入问题，路径含空格/中文也安全。
4. **修复原项目缺陷**：
   - 子集字体文件名产生 `Name.ttf.ttf` 双扩展名；
   - 字幕语言使用 `zh-Hans` 等 BCP-47 标签，mkvmerge 会直接报错 —— 改用 ISO-639-2（`chi`/`jpn`）；
   - 同一字幕因搜索目录重复而被匹配多次，导致封装出重复字幕轨；
   - ffmpeg 回退路径会把完整临时路径写成附件名。
5. **新增能力**：
   - **Tkinter 图形界面**（支持拖拽、后台线程、实时日志、进度条）；
   - **字幕匹配预检**：添加文件时即标红提示哪些视频找不到外挂字幕；
   - `--dry-run` 试运行、`--json` 机器可读输出、分级日志（`-q`/`-v`）；
   - 依据文件名自动推断字幕语言与轨道标题（`chs`/`tc`/`jpn` …）；
   - `--no-subset` 直接内嵌完整字体、`--no-system-fonts` 加速启动；
   - mkvmerge 与 ffmpeg 双后端自动选择与回退。
6. **CLI 与 GUI 共用同一套流程**（`core` + `runner`），两条路径行为完全一致，不会各改各的。

## 环境要求

- Python 3.7+
- `fontTools`：`pip install fonttools`
- `tkinterdnd2`（可选）：`pip install tkinterdnd2` —— 仅用于图形界面的**拖拽添加**功能
- **mkvmerge**（推荐）：安装 [MKVToolNix](https://mkvtoolnix.download/)，或放在 PATH 中；
  程序也会自动查找 `C:\Program Files\MKVToolNix\mkvmerge.exe`
- **ffmpeg**（可选，mkvmerge 缺失时回退使用）

## 图形界面（推荐新手）

双击 **`运行界面.bat`**，或执行：

```bash
python -m subfontmkv.gui
# 也可以直接写 subfontmkv gui
```

界面为**左操作 + 右日志**两栏布局：

**左栏**

1. **添加视频** —— 顶部是拖拽区，把视频文件或文件夹直接拖进来即可添加（可一次拖多个，
   含空格的中文路径也没问题）；也可以用「添加视频…/添加文件夹…」按钮。
   拖拽经过时边框和背景会高亮。列表支持多选，双击或按 Delete 可移除。

   **列表会自动预检字幕匹配情况，并以颜色区分：**

   | 颜色 | 含义 |
   | --- | --- |
   | 🔴 红色加粗 | **未匹配到字幕**（0 条）—— 该视频不会被封装，请检查字幕文件名 |
   | 🟢 绿色 | 已匹配到字幕，可以封装 |
   | ⚪ 灰色 | 文件夹（若其中含缺字幕的视频，文件夹行也会标红并汇总数量） |
   | 🟠 橙色 | 文件夹里没有视频文件 |

   添加文件夹时会自动展开出里面的每个视频，逐个判定。列表右侧还有「匹配字幕 / 状态」
   两列，底部汇总会提示「其中 N 个未匹配到字幕」。
2. **封装选项** —— 字幕语言、输出后缀、额外字体目录，以及子集化/系统字体/轨道命名/
   递归/保留源轨道/试运行等开关。
3. **开始** —— 开始 / 停止 / 打开输出目录，下方是状态文字与进度条。

**右栏：日志**

实时显示探测结果、匹配到的字幕、子集化过程与封装命令；带垂直+水平滚动条
（mkvmerge 命令行很长，可横向查看），另有「复制全部」「清空日志」按钮。

封装在后台线程执行，界面不会卡死，「停止」会在当前文件处理完后中断。

> 拖拽依赖可选包 `tkinterdnd2`（`pip install tkinterdnd2`）。未安装时界面其余功能
> 完全正常，只是拖拽不可用，此时提示会自动变为使用按钮添加。

![界面截图](gui-screenshot.png)

## 命令行快速开始

```bash
# 处理单个视频（自动匹配同目录下的外挂字幕）
python -m subfontmkv "D:\Anime\Show EP01.mkv"

# 批量递归处理整个目录
python -m subfontmkv "D:\Anime" --recursive

# 指定额外字体目录 + 先试运行看看会做什么
python -m subfontmkv "D:\Anime" --font-dir "D:\Fonts" --dry-run
```

## 常用参数

| 参数 | 说明 |
| --- | --- |
| `--font-dir DIR` | 额外字体目录，可重复 |
| `--no-subset` | 不做子集化，直接内嵌完整字体 |
| `--no-system-fonts` | 不读取系统字体目录（启动更快） |
| `--language LANG` | 默认字幕语言，默认 `und` |
| `--no-infer-language` | 不从文件名推断语言 |
| `--muxer auto\|mkvmerge\|ffmpeg` | 指定封装器 |
| `--mkvmerge PATH` | 手动指定 mkvmerge 路径 |
| `--keep-source-subs` / `--keep-source-attach` | 保留源 MKV 里已有的字幕/附件（默认丢弃） |
| `--suffix .subfont` | 输出文件后缀 |
| `--dry-run` / `--json` / `-q` / `-v` | 试运行 / JSON 输出 / 静默 / 详细日志 |

完整列表见 `python -m subfontmkv --help`。

## 工作原理

1. **匹配字幕** —— 按「视频名 + 后缀」匹配同目录（或 `--sub-dir`）下的 `.ass/.ssa/.srt/.vtt` 等。
2. **解析字体需求** —— 读取字幕 `[V4+ Styles]` 段中每个样式使用的 `Fontname`。
3. **查找字体** —— 在视频目录 → `--font-dir` → 系统字体目录中按字体名查找，支持 TTC/OTC 中的单个 face。
4. **子集化** —— 用 `fontTools` 只保留字幕实际用到的字符，并把字体内部名称改写为
   `原名.CRC32`（例如 `AgencyFB-Bold.302BD68C`）。
5. **重写字幕** —— 把 ASS 里引用的字体名同步改为 `原名.CRC32`。
6. **封装** —— 用 mkvmerge 把字幕作为软字幕轨、字体作为附件写入 MKV；
   源文件里原有的字幕轨与附件默认丢弃（`-S -M`），避免与新的重复。

第 4、5 步是关键：字幕引用的字体名与内嵌字体的内部名一致，播放器就一定会用上内嵌的字体。

## 验证

```bash
$ python -m subfontmkv "test-assets\Show EP01.mkv" --font-dir "test-assets\fonts"
封装器: mkvmerge (C:\Program Files\MKVToolNix\mkvmerge.exe)
字体索引就绪，共 2861 个字体名。
=== Show EP01.mkv ===
匹配到 2 条字幕:
  - Show EP01.chs.ass
  - Show EP01.jpn.ass
  子集化字体: TestFont.ttf (76 字)
封装完成: test-assets\Show EP01.subfont.mkv
完成: 成功 1 / 试运行 0 / 跳过 0 / 失败 0
```

用 `mkvmerge -i` 检查产物：

```
Track ID 0: video (MPEG-4p10/AVC/h.264)
Track ID 1: audio (AAC)
Track ID 2: subtitles (SubStationAlpha)      <- 软字幕，语言 chi
Track ID 3: subtitles (SubStationAlpha)      <- 软字幕，语言 jpn
Attachment ID 1: type 'application/x-truetype-font', size 20568 bytes,
                 file name 'TestFont.subset.302BD68C.ttf'   <- 内嵌子集字体
```

字体由完整的 60656 字节压缩到 20568 字节。

## 许可证

Apache License 2.0。原始项目 Copyright (c) 2022-2024 yyfll。
