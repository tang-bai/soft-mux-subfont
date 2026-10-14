# -*- coding: utf-8 -*-
"""获取基础项目源码。

默认通过 https://git.tangbai.cc 代理下载 DYY-Studio/AddSubFontMKV_py，
解压到 third_party/ 供阅读与对照（本项目只借鉴其思路，未直接引用其代码）。

用法:
    python tools/fetch_base.py
    python tools/fetch_base.py --direct      # 直连 GitHub
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import urllib.request
import zipfile

PROXY = "https://git.tangbai.cc/"
REPO = "DYY-Studio/AddSubFontMKV_py"
BRANCH = "main"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "third_party", "AddSubFontMKV_py")


def download(url: str, timeout: int = 120) -> bytes:
    request = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (SubFontMKV fetch_base)",
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def main() -> int:
    parser = argparse.ArgumentParser(description="下载基础项目源码")
    parser.add_argument("--direct", action="store_true",
                        help="直连 GitHub（默认走 git.tangbai.cc 代理）")
    parser.add_argument("--repo", default=REPO, help="仓库，默认 " + REPO)
    parser.add_argument("--branch", default=BRANCH, help="分支，默认 " + BRANCH)
    parser.add_argument("--output", default=TARGET, help="解压目标目录")
    args = parser.parse_args()

    archive = "https://github.com/{0}/archive/refs/heads/{1}.zip".format(args.repo, args.branch)
    url = archive if args.direct else PROXY + archive
    print("正在下载: {0}".format(url))
    try:
        blob = download(url)
    except Exception as exc:
        print("下载失败: {0}".format(exc), file=sys.stderr)
        return 1
    print("已下载 {0} 字节".format(len(blob)))

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(blob)) as archive_zip:
        names = archive_zip.namelist()
        prefix = names[0].split("/")[0] + "/" if names else ""
        for name in names:
            if name.endswith("/"):
                continue
            relative = name[len(prefix):] if name.startswith(prefix) else name
            destination = os.path.join(args.output, relative)
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            with archive_zip.open(name) as source, open(destination, "wb") as out:
                out.write(source.read())
    print("已解压到: {0}".format(args.output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
