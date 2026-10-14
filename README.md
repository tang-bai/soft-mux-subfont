# SubFontMKV

**把外挂字幕和字体一起软封装进 MKV。** 字幕变成播放器里可以开关的**软字幕轨**，用到的字体
以**附件**形式内嵌进同一个文件；换台电脑、换个播放器，字幕该长什么样就还是什么样。

MKV 是极少数能同时装下「字幕轨」和「字体附件」的容器格式，SubFontMKV 就是把这个能力用起来的工具。

---

## 它解决什么问题

下载的番剧、电影常常是「视频 + 一堆外挂字幕」。直接看有两个麻烦：

| 麻烦 | SubFontMKV 怎么解决 |
| --- | --- |
| 字幕文件要跟视频放在一起，少一个就没了 | 字幕被封装进 MKV，单文件自带 |
| 字幕用的字体你机器上没有，样式全乱（变成默认宋体、位置跑偏、特效消失） | 把字体**内嵌**进 MKV，播放器直接用 |
| 想装字体又嫌麻烦，装多了还会影响系统里其他软件 | 字体只写进这个视频文件，**不安装到系统** |
| 完整字体动辄几 MB～几十 MB，塞进视频太浪费 | **字体子集化**：只保留字幕真正用到的那些字（实测微软雅黑 19.7 MB → **46.5 KB**） |

### 关键做法：字体改名（CRC32）

光是内嵌还不够。如果内嵌的字体叫「微软雅黑」，而看片的人系统里**也**装了微软雅黑，播放器
很可能优先用系统那份完整的——你内嵌的子集就被忽略了，样式照样可能出问题。

所以本项目会把内嵌字体的**内部名称**改成 `原名.CRC32`（例如 `AgencyFB-Bold.302BD68C`），
同时把字幕里引用的字体名改成同一个名字。名字对上了，播放器就**必然**命中你内嵌的那份。

---

## 功能一览

- **图形界面 + 命令行**，两条路径共用同一套处理流程，行为一致
- **拖拽添加**：视频或整个文件夹直接拖进窗口
- **批量处理**：整个目录一次搞定，支持递归子目录
- **字幕匹配预检**：加进来就告诉你哪个视频找不到字幕（红色标出），不用等跑完才发现
- **字体子集化**：只留用得到的字，顺带改写字体内部名称
- **多语言字幕**：自动按文件名推断语言（`chs`/`tc`/`jpn`…）并写成合法的 ISO-639-2 标签
- **实时进度**：进度条与状态栏显示「正在处理 2/5 — Show EP01.mkv  45%」
- **日志筛选**：按级别（调试/信息/警告/错误）+ 关键字过滤
- **试运行**：`--dry-run` 先看会做什么，不动文件
- **脚本友好**：`--json` 输出机器可读结果，方便接到自己的流程里
- **跨平台**：Windows / Linux / macOS

---

## 安装

### 1. 准备 Python

需要 **Python 3.7 或更高**。Windows 上安装时请勾选 **Add Python to PATH**。

验证：

```bash
python --version
```

### 2. 安装依赖

```bash
pip install fonttools
```

想用**拖拽添加文件**的话再装一个（可选）：

```bash
pip install tkinterdnd2
```

### 3. 安装 MKVToolNix（强烈建议）

SubFontMKV 自己不做封装，它调用 **mkvmerge** 来把字幕和字体写进 MKV。

从 [mkvtoolnix.download](https://mkvtoolnix.download/) 下载安装。
Windows 装完在 `C:\Program Files\MKVToolNix\mkvmerge.exe`，程序会**自动找到**它，不必配 PATH。

> **没有 mkvmerge 行不行？** 行，会退回用 **ffmpeg**，但 ffmpeg 只能把字体挂成附件，
> **无法写入独立的软字幕轨**，效果差很多。所以还是建议装 MKVToolNix。

### 4. 开始使用

**方式 A：便携版 exe（免装 Python，最省事）**

下载 `SubFontMKV-*-portable-win64.zip`，解压后双击 **`SubFontMKV.exe`** 即可，
不用装 Python。除了 MKVToolNix，没有别的依赖。

**方式 B：直接用源码**

把项目文件夹放着就行，**不需要安装**。直接：

```bash
python -m subfontmkv "视频文件或目录"
```

Windows 用户双击 **`运行界面.bat`** 就能打开图形界面。

<details>
<summary>可选：安装成命令（<code>pip install .</code>）</summary>

```bash
pip install .          # 提供 subfontmkv 命令
pip install .[gui]     # 顺便装 tkinterdnd2，启用拖拽
```

装完后可以直接：

```bash
subfontmkv "D:\Anime\Show EP01.mkv"
subfontmkv-gui
```

</details>

---

## 图形界面

双击 **`运行界面.bat`**，或者：

```bash
python -m subfontmkv.gui
# 也可以： python -m subfontmkv gui
```

![界面截图](gui-screenshot.png)

界面是**左操作 + 右日志**两栏。

### 左栏：三步走

**1. 添加视频**

把视频文件或文件夹**直接拖到这一整块区域**，或者点「添加视频…／添加文件夹…」。
支持一次拖多个，路径含空格或中文都没问题。

列表里没东西时，会有一段蓝色提示文字告诉你可以拖拽；加进文件后提示自动让位给列表。

**2. 封装选项**

| 选项 | 说明 |
| --- | --- |
| 字幕语言 | 默认「跟随文件名推断」，也可强制指定 |
| 输出后缀 | 默认 `.subfont`，会加在文件名后面 |
| 额外字体目录 | 视频目录里找不到的字体，到这里找 |
| 输出目录 | 留空就输出到视频同目录 |
| 字体子集化 | 默认开。关掉就内嵌完整字体 |
| 读取系统字体 | 默认开。关掉启动更快（但系统字体就用不上了） |
| 推断字幕语言 | 按 `xxx.chs.ass` 这类文件名判断语言 |
| 保留源字幕轨 | 默认关，避免和新的字幕重复 |
| 文件夹递归 | 加文件夹时是否往下找子目录 |
| 仅试运行 | 只报告会做什么，不真的封装 |

**3. 开始**

点「开始封装」。进度条和状态栏会实时更新，随时可以「停止」（当前文件处理完就停）。
完成后「打开输出目录」直接跳到结果所在的地方。

### 列表里的颜色

添加视频时会**立刻预检**字幕匹配情况：

| 颜色 | 含义 |
| --- | --- |
| 🔴 红色加粗 | **没找到字幕**，这个视频会被跳过——检查一下字幕文件名 |
| 🟢 绿色 | 找到字幕了，可以封装 |
| 黑色 | 普通行 |

### 右栏：日志

顶上有筛选栏，内容多的时候很有用：

| 控件 | 作用 |
| --- | --- |
| **显示** | 按级别过滤：全部（含调试）／信息／警告以上／仅错误 |
| **包含** | 关键字过滤，大小写不敏感，可以和级别叠加 |
| **✕** | 清除筛选 |
| 计数 | 例如「显示 3 / 21 行」 |
| **滚到底部** | 上翻看历史之后，跳回最新一行 |

筛选是实时的：封装过程中切换条件，已经打出来的日志立刻重排。
「复制全部」在有筛选时**只复制看得见的行**。

日志本身实时显示匹配到的字幕、字体子集化过程、封装进度和命令。超长的一行（mkvmerge
命令行、长路径）会**自动换行**，不需要横向拖。

封装跑在后台线程，界面不会卡死。

> 拖拽依赖 `tkinterdnd2`。没装也不影响——只是拖拽用不了，按钮添加照常，
> 提示文字会自动改成让你用按钮。

---

## 命令行用法

```bash
# 处理单个视频（自动找同目录下的外挂字幕）
python -m subfontmkv "D:\Anime\Show EP01.mkv"

# 整个目录递归批量处理
python -m subfontmkv "D:\Anime" --recursive

# 指定额外字体目录，先看看会做什么
python -m subfontmkv "D:\Anime" --font-dir "D:\Fonts" --dry-run

# 输出到别处
python -m subfontmkv "D:\Anime" --output-dir "D:\Muxed" --recursive
```

Windows 上也可以把文件／文件夹直接**拖到 `subfontmkv.bat` 上**。

### 全部参数

| 参数 | 说明 |
| --- | --- |
| `--font-dir DIR` | 额外字体目录，可重复指定 |
| `--sub-dir DIR` | 额外的字幕搜索目录，可重复指定 |
| `--output-dir DIR` / `-o` | 输出目录，默认与视频同目录 |
| `--suffix SUFFIX` | 输出文件名后缀，默认 `.subfont` |
| `--language LANG` / `-l` | 默认字幕语言，默认 `und` |
| `--no-infer-language` | 不从文件名推断语言 |
| `--no-subset` | 不做子集化，直接内嵌完整字体 |
| `--no-system-fonts` | 不读取系统字体目录（启动更快） |
| `--muxer auto\|mkvmerge\|ffmpeg` | 指定封装器，默认自动选择 |
| `--mkvmerge PATH` | 手动指定 mkvmerge 路径 |
| `--ffmpeg PATH` | 手动指定 ffmpeg 路径 |
| `--keep-source-subs` | 保留源 MKV 里已有的字幕轨（默认丢弃） |
| `--keep-source-attach` | 保留源 MKV 里已有的附件（默认丢弃） |
| `--recursive` / `-r` | 递归处理子目录 |
| `--dry-run` | 只报告会做什么，不封装 |
| `--json` | 以 JSON 输出结果（日志转到 stderr） |
| `--work-dir DIR` | 临时工作目录，默认用系统临时目录 |
| `-q` / `--quiet` | 只输出警告与错误 |
| `-v` / `--verbose` | 输出调试信息 |
| `--version` | 显示版本 |

完整列表：`python -m subfontmkv --help`

---

## 它做了什么

处理一个视频的完整流程：

1. **匹配字幕** —— 在同目录（以及 `--sub-dir`）里找与视频同名的 `.ass/.ssa/.srt/.vtt` 等。
   视频名之后只允许跟**语言标签**（`chs`/`简体`/`zh-Hans`…）或**版本标记**（`v2`/`ver2`），
   避免 `Show.mkv` 把 `Show EP01.chs.ass` 这种别的集数也吃进来。

2. **分析字体需求** —— 读字幕 `[V4+ Styles]` 里的 `Fontname`，并沿着文本里的
   `{\fn...}` / `{\r...}` 覆盖标签逐段走，算出**每种字体实际用到哪些字符**。
   注释行（`Comment:`）和 `\p` 绘图指令的坐标不算在内——它们不会显示出来。

3. **查找字体** —— 依次在 视频目录 → `--font-dir` → 系统字体目录里找。
   支持 TTC/OTC 这种一个文件装多个字体的格式，并按样式的粗体／斜体挑合适的那个 face。

4. **子集化** —— 用 `fontTools` 只保留用到的字符，并把字体内部名称改成
   `原名.CRC32`（如 `AgencyFB-Bold.302BD68C`）。
   压缩效果很可观：一份 19.7 MB 的微软雅黑，只为一句话的字幕子集化后只有 **46.5 KB**。

5. **重写字幕** —— 把字幕里引用的字体名同步改成新名字，并在 `[Script Info]` 里留一行
   `; Font Subset: 新名 - 原名` 注释。下次再处理同一个字幕时能据此还原原字体名，
   不会一层层叠加。

6. **封装** —— 用 mkvmerge 把字幕写成软字幕轨、字体写成附件。
   源文件里原有的字幕轨和附件默认丢掉，免得和新的重复。

> 第 4、5 步是整个方案的关键：**字幕引用的字体名 = 内嵌字体的内部名**，
> 播放器就一定会用上内嵌的那份字体。

---

## 项目结构

```
subfontmkv/
  ass.py        SSA/ASS 解析、字体需求分析、字体名改写
  fonts.py      字体索引与匹配、子集化、内部名称改写
  mux.py        mkvmerge / ffmpeg 后端与外部命令调用
  core.py       字幕匹配、任务规划、批量执行（CLI 与 GUI 共用）
  cli.py        命令行接口
  gui.py        Tkinter 图形界面
  log.py        分级日志
tests/
  run_tests.py  49 项回归测试（解析 / 匹配 / 字体 / 进度 / 端到端封装）
  test_gui.py   28 项 GUI 测试（预检 / 拖拽 / 日志 / 进度 / 筛选 / 真实封装）
  fixtures/     测试用字幕
test-assets/    自包含测试素材（由脚本生成的合成视频与字体）
tools/
  fetch_base.py       通过 git.tangbai.cc 代理重新拉取基础项目源码
  make_test_fonts.py  生成合成测试字体
  make_test_assets.py 生成批量 / TTC 等测试素材
  make_screenshot.py  生成 README 用的界面截图
运行界面.bat / subfontmkv.bat   Windows 启动脚本
```

---

## 常见问题

**播放器里看不到字幕？**
MKV 里的软字幕需要手动打开——大多数播放器默认不显示。检查一下字幕轨有没有被关掉。

**字幕样式还是不对？**
确认内嵌字体被用上了。用 `mkvmerge -i 文件.mkv` 应该能在附件里看到字体。
另外注意：如果播放器用了「强制使用系统字体」之类的选项，会绕过内嵌字体。

**提示「未匹配到字幕」？**
字幕必须和视频**同名**，后面只允许再跟**语言标签**或**版本标记**：

```
Show EP01.mkv  ✅ Show EP01.ass        ✅ Show EP01.chs.ass     ✅ Show EP01.简体.ass
               ✅ Show EP01.jpn.ass    ✅ Show EP01.zh-Hans.ass ✅ Show EP01.v2.ass
               ❌ Show EP01.中文字幕.ass   ❌ Show EP01.字幕.ass   ❌ Show EP01.简体中文.ass
               ❌ Show EP01.bak.ass       ❌ Show EP01.EP02.ass
```

被 ❌ 挡住的多是「描述性词句」或会被误当成别的集数的名字。这样做是为了避免
`Show.mkv` 把同目录下别的集数字幕也一起封装进来。真需要时用 `--sub-dir` 指定目录，
或把字幕改成规范文件名即可。

**找不到字体？**
日志里会列出缺哪些。用 `--font-dir` 指定字体所在目录，或者把字体文件放到视频同目录。

**提示「子集化失败: too much data」？**
这是字体文件本身的毛病，不是你的操作问题。有些字体（尤其日文商用字体，
如 Reishoreiryu）的 `gasp` 表头部声明的区间数少于实际数据，fontTools 展开到结尾
发现有剩余字节就报错，导致整个字体用不了。

程序会自动处理：**丢掉这一个表继续子集化**，日志里会提示
「表 gasp 结构异常，已丢弃后继续子集化」。`gasp` 只影响「什么字号下启用网格适配」
这类渲染提示，与字形、字符映射、样式名称都无关，丢掉不影响字幕显示。

如果丢掉后仍然失败，可以改用 `--no-subset` 直接内嵌完整字体：

```bash
python -m subfontmkv "视频.mkv" --no-subset
```

**想保留原有的字幕轨？**
加 `--keep-source-subs`。默认是丢弃的，因为多数情况下你要的是新做的这条。

---

## 开发

### 跑测试

测试素材是脚本生成的，不依赖你机器上装了什么字体：

```bash
python tools/make_test_fonts.py     # 合成测试字体
python tools/make_test_assets.py    # 合成视频 + TTC 等素材

python -m unittest tests.run_tests -v   # 49 项回归测试
python tests/run_tests.py --quick       # 只跑解析/字体逻辑，不封装
python tests/test_gui.py                # 28 项 GUI 测试（需要图形环境）
```

端到端测试会**真的调用 mkvmerge 封装**，然后解封装回来校验：字幕轨语言是不是合法
ISO-639-2、附件名有没有带 CRC32、以及**内嵌字幕引用的字体名是否与附件字体的内部名称完全一致**。
没装 mkvmerge 时这部分自动跳过。

### 打包便携版 exe

想做一个免装 Python 的 Windows 便携版：

```bash
pip install pyinstaller
python tools/build_exe.py --clean
```

产物：

| 文件 | 说明 |
| --- | --- |
| `dist/SubFontMKV.exe` | 单文件，约 28 MB，双击即用 |
| `release/SubFontMKV-1.0.0-portable-win64.zip` | 发布包：exe + 图标 + 使用说明 |

打包时会自动：

- 生成图标（`tools/make_icon.py`，也可以单独跑）；
- 只把**当前平台**的 `tkdnd` 原生库塞进去（拖拽功能依赖它），其它平台的目录不带，省体积；
- 收集 `fontTools` 的全部子模块（子集化会按需 import 各类字体表，漏掉就会在运行时炸）。

调试打包问题时加 `--console` 保留控制台窗口：

```bash
python tools/build_exe.py --console
```

### 与基础项目的关系

本项目在 [DYY-Studio/AddSubFontMKV_py](https://github.com/DYY-Studio/AddSubFontMKV_py)
（Apache-2.0）的思路基础上重写。那个项目用 PyQt5、强依赖 Windows 注册表、且用 `os.system`
拼命令行；本项目保留它「子集化 + CRC32 改名」的核心方案，把其余部分重做了。

<details>
<summary>相对基础项目的主要改动（点开）</summary>

**架构**

1. 库 + CLI 分离，去掉 PyQt5／colorama 等硬依赖，跨平台可用
2. 纯 Python 字体扫描，不再读 Windows 注册表
3. 用 `subprocess` 调外部程序，不用 `os.system` 拼字符串（路径含空格/中文也安全）
4. CLI 与 GUI 共用 `core` 里的同一套流程，不会各改各的

**修掉的原项目缺陷**

- 子集字体文件名会产生 `Name.ttf.ttf` 双扩展名
- 字幕语言用 `zh-Hans` 这类 BCP-47 标签，mkvmerge 会直接报错——改用 ISO-639-2
- 同一字幕因搜索目录重复被匹配多次，封装出重复字幕轨
- ffmpeg 回退路径会把完整临时路径写成附件名

**自己发现并修掉的实现问题**（都有对应回归测试）

- 覆盖标签必须按「标签名 + 其余内容」切分——否则 `{\rNote}` 会被贪婪地读成名为 `rNote`
  的标签，导致那行文字算到错误的字体上
- `\p1` 绘图指令的坐标、`Comment:` 行不应计入字体字符集
- TTC/OTC 的多个 face 共用一个文件 reader，逐个 `close()` 会让其余 face 报
  `seek of closed file`——改为统一收口
- 子集化输出的扩展名按 sfnt 类型（`.ttf`/`.otf`）给，而不是沿用源文件的 `.ttc`
- 重复对同一份字幕子集化时，注释与字体名不会层层叠加

**体验与性能**

- 拖入文件不卡顿：字幕匹配按目录缓存清单、热路径改为纯字符串比较（一次拖入上百个视频约快 12 倍）
- 实时进度：逐行读 mkvmerge 输出（原来 `subprocess.run()` 要等进程结束才拿到全部输出）
- 日志批量写入 + 只保留最近 600 行 + 贴底才自动滚动（原来逐行 `insert`+`see`，3000 行要 8.7 秒）
- 日志自动换行，超长的 mkvmerge 命令行不再横向溢出
- 日志按级别／关键字筛选，「复制全部」只复制可见行

</details>

---

## 许可证

Apache License 2.0。原始项目 Copyright (c) 2022-2024 yyfll。
