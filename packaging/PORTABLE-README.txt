# SubFontMKV 便携版

这是用 PyInstaller 打包的 Windows 便携版，**免安装 Python**，双击即用。

## 怎么用

1. 把 `SubFontMKV.exe` 复制到任意位置（U 盘也行），双击打开。
2. 还没装 **MKVToolNix** 的话先装一个 → <https://mkvtoolnix.download/>
   （程序靠它把字幕和字体写进 MKV；装好后会被自动找到，不用配 PATH）
3. 把视频或文件夹**拖进窗口**，点「开始封装」。

详细说明见项目根目录的 `README.md`。

## 也能当命令行用

```bat
SubFontMKV.exe "D:\Anime\Show EP01.mkv"
SubFontMKV.exe "D:\Anime" --recursive --dry-run
SubFontMKV.exe --help
SubFontMKV.exe --version
```

> 小提示：在 cmd 里跑命令行时，如果看不到输出，先执行一次 `chcp 65001`。

## 运行环境要求

| 项目 | 说明 |
| --- | --- |
| 系统 | Windows 10 / 11 64 位 |
| Python | **不需要**，已打包进 exe |
| MKVToolNix | **需要**（提供 mkvmerge），请自行安装 |
| 首次启动 | 单文件版会解压到临时目录，比常规程序慢 1～3 秒，属正常现象 |

## 常见问题

**双击没反应？**
先装 MKVToolNix。如果确实启动失败，程序会弹窗提示；日志同时写到
`%USERPROFILE%\SubFontMKV-crash.log`。

**杀毒软件报毒？**
PyInstaller 打包的程序常被误报（它会把 Python 运行时解包到临时目录）。
可以加入信任，或改用源码方式运行（见主 README）。

**下次启动还是慢？**
单文件版每次启动都要自解压。想更快的话，删掉这一个文件，改用主 README 里
「直接使用」的方式（需要装 Python）。
