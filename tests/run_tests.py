# -*- coding: utf-8 -*-
"""SubFontMKV 测试套件。

运行:
    python tests/run_tests.py            # 需要 mkvmerge（端到端部分会自动跳过）
    python tests/run_tests.py --quick    # 只跑解析/字体逻辑，不封装
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from subfontmkv import ass, core, fonts
from subfontmkv.mux import MkvmergeMuxer, is_subtitle, is_video

YAHEI = "微软雅黑"
FIXTURE_DIR = os.path.join(HERE, "fixtures")

QUICK = "--quick" in sys.argv
if QUICK:
    sys.argv.remove("--quick")


def mkvmerge_path():
    muxer = MkvmergeMuxer.locate()
    return muxer.executable if muxer else None


MKVMERGE = mkvmerge_path()

#: 合成测试素材（视频/字体）不入库，缺失时相关用例自动跳过
ASSETS = os.path.join(ROOT, "test-assets")
TEST_VIDEO = os.path.join(ASSETS, "Show EP01.mkv")
TEST_FONTS = os.path.join(ASSETS, "fonts")
BATCH_FONTS = os.path.join(ASSETS, "batch", "fonts")

HAS_ASSETS = os.path.exists(TEST_VIDEO) and os.path.isdir(TEST_FONTS)
ASSETS_HINT = ("缺少合成测试素材，请先运行:\n"
               "    python tools/make_test_fonts.py\n"
               "    python tools/make_test_assets.py")


# ==========================================================================
# 字幕解析
# ==========================================================================
class TestAssParsing(unittest.TestCase):
    def setUp(self):
        self.ass = ass.AssFile.load(os.path.join(FIXTURE_DIR, "Show EP01.chs.ass"))

    def test_sections_found(self):
        self.assertIsNotNone(self.ass.script_info_index)
        self.assertIsNotNone(self.ass.styles_header_index)
        self.assertIsNotNone(self.ass.events_header_index)

    def test_style_cursor_read_from_format(self):
        self.assertEqual(self.ass.name_pos, 0)
        self.assertEqual(self.ass.font_pos, 1)
        names = [s.name for s in self.ass.styles]
        self.assertEqual(names, ["Default", "Note"])

    def test_bold_italic_parsed(self):
        default = [s for s in self.ass.styles if s.name == "Default"][0]
        self.assertTrue(default.bold, "Bold=-1 应解析为 True")
        self.assertFalse(default.italic)

    def test_comment_events_flagged(self):
        comments = [e for e in self.ass.events if e.is_comment]
        self.assertEqual(len(comments), 1)
        self.assertIn("SHOULD NOT COUNT", comments[0].text)

    def test_text_with_commas_not_split(self):
        event = self.ass.events[0]
        self.assertTrue(event.text.startswith("Hello {"), event.text)

    def test_font_usage_respects_fn_and_r(self):
        usage = self.ass.font_usage()
        # Default 样式 Bold=-1，所以 Arial 的需求带粗体标志；Note 样式不粗体
        self.assertIn(("Arial", True, False), usage)
        self.assertIn((YAHEI, False, False), usage)
        # "Hello " 与 " back!" 用 Default（Arial, Bold=-1）
        self.assertEqual(set(usage[("Arial", True, False)]), set("Hello  back!Text"))
        # Note 样式那一行用微软雅黑、不粗体
        self.assertEqual(set(usage[(YAHEI, False, False)]), set("世你好界"))
        # Default 行里的 \fn 与 \rNote 都是微软雅黑，沿用该行的粗体标志
        self.assertEqual(set(usage[(YAHEI, True, False)]), set("worldvia style reset"))

    def test_comment_text_excluded(self):
        joined = "".join(self.ass.font_usage().values())
        self.assertNotIn("SNOWMAN", joined)

    def test_drawing_commands_excluded(self):
        joined = "".join(self.ass.font_usage().values())
        self.assertNotIn("m 0 0", joined)

    def test_vertical_fontname_marker_stripped(self):
        text = ("[Script Info]\n\n[V4+ Styles]\n"
                "Format: Name, Fontname, Fontsize\n"
                "Style: D,@Vertical,48\n\n[Events]\n"
                "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                "Dialogue: 0,0:00:01.00,0:00:02.00,D,,0,0,0,,AB\n")
        parsed = ass.AssFile.from_string(text)
        self.assertEqual(parsed.styles[0].fontname, "Vertical",
                         "@ 前缀是竖排标记，不应算作字体名的一部分")
        parsed.apply_font_map({"Vertical": "V.1"})
        self.assertIn("Style: D,@V.1,48", "".join(parsed.lines))

    def test_rewrite_only_touches_fonts(self):
        self.ass.apply_font_map({"Arial": "Arial.ABCD1234", YAHEI: YAHEI + ".DEADBEEF"})
        out = "".join(self.ass.lines)
        self.assertIn("Style: Default,Arial.ABCD1234,", out)
        self.assertIn("Style: Note,{0}.DEADBEEF,".format(YAHEI), out)
        self.assertIn("{\\fn" + YAHEI + ".DEADBEEF}world", out)
        self.assertIn("SHOULD NOT COUNT SNOWMAN", out)
        self.assertIn("{\\p1}m 0 0 l 10 10", out)
        self.assertIn("{\\rNote}via style reset", out)

    def test_notes_only_for_used_fonts(self):
        self.ass.apply_font_map({"Arial": "A.1", "Unused Font": "U.2"})
        out = "".join(self.ass.lines)
        self.assertIn("; Font Subset: A.1 - Arial", out)
        self.assertNotIn("U.2", out, "未使用的字体不应出现在注释里")

    def test_reload_recovers_original_names(self):
        self.ass.apply_font_map({"Arial": "Arial.ABCD1234", YAHEI: YAHEI + ".DEADBEEF"})
        again = ass.AssFile.from_string("".join(self.ass.lines))
        self.assertEqual(again.recovered["Arial.ABCD1234"], "Arial")
        self.assertEqual([s.fontname for s in again.styles], ["Arial", YAHEI])

    def test_idempotent_second_pass(self):
        m = {"Arial": "Arial.ABCD1234"}
        self.ass.apply_font_map(m)
        again = ass.AssFile.from_string("".join(self.ass.lines))
        again.apply_font_map({"Arial": "Arial.NEWCRC"})
        self.assertIn("Arial.NEWCRC", "".join(again.lines))
        self.assertNotIn("Arial.ABCD1234.NEWCRC", "".join(again.lines))

    def test_crlf_preserved(self):
        text = ("a\r\n[Events]\r\nFormat: Layer, Start, End, Style, Name, MarginL, "
                "MarginR, MarginV, Effect, Text\r\n"
                "Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,AB\r\n")
        parsed = ass.AssFile.from_string(text)
        parsed.apply_font_map({"Default": "D.1"})
        self.assertIn("\r\nDialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,AB\r\n",
                      "".join(parsed.lines))

    def test_no_styles_section_does_not_crash(self):
        parsed = ass.AssFile.from_string("[Script Info]\nTitle: x\n\n[Events]\n")
        self.assertEqual(parsed.font_usage(), {})


class TestLanguageInference(unittest.TestCase):
    def test_inference(self):
        cases = [("Show.chs.ass", "chi"), ("Show.tc.ass", "chi"), ("Show.jpn.ass", "jpn"),
                 ("x.zh-Hans.ass", "chi"), ("x.zh-Hant.ass", "chi"), ("x.eng.srt", "eng"),
                 ("x.kor.ass", "kor"), ("plain.ass", None)]
        for name, want in cases:
            self.assertEqual(ass.language_from_name(name), want, name)

    def test_bcp47_would_break_mkvmerge(self):
        # 原项目的缺陷：zh-Hans 不是合法 ISO-639-2，必须转成 chi
        self.assertEqual(ass.language_from_name("Show.zh-Hans.ass"), "chi")
        self.assertRegex(ass.language_from_name("Show.zh-Hans.ass"), r"^[A-Za-z]{2,3}$")

    def test_track_title(self):
        self.assertEqual(ass.track_title("Show EP01", "Show EP01.chs.ass"), "chs")
        self.assertIsNone(ass.track_title("Show", "Show.ass"))


# ==========================================================================
# 字幕匹配
# ==========================================================================
class TestSubtitleMatching(unittest.TestCase):
    def test_exact_and_suffixed(self):
        self.assertTrue(core._name_matches("Show EP01", "Show EP01.ass"))
        self.assertTrue(core._name_matches("Show EP01", "Show EP01.chs.ass"))
        self.assertTrue(core._name_matches("Show", "Show.jpn.ass"))
        self.assertTrue(core._name_matches("Show", "Show.v2.ass"))

    def test_does_not_steal_other_episodes(self):
        # "Show.mkv" 不应吃掉 "Show EP01.chs.ass"
        self.assertFalse(core._name_matches("Show", "Show EP01.chs.ass"))
        self.assertFalse(core._name_matches("Show EP01", "Show EP02.chs.ass"))
        self.assertFalse(core._name_matches("Show", "ShowMovie.chs.ass"))

    def test_deduplicates_across_search_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = os.path.join(tmp, "Show.mkv")
            with open(video, "wb") as fp:
                fp.write(b"x")
            with open(os.path.join(tmp, "Show.ass"), "w", encoding="utf-8"):
                pass
            # 同一个目录作为「额外目录」再传一次，不应产生重复
            found = core.find_subtitles(video, [tmp])
            self.assertEqual(len(found), 1, found)

    def test_language_sorting_is_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = os.path.join(tmp, "Show.mkv")
            with open(video, "wb") as fp:
                fp.write(b"x")
            for n in ("Show.jpn.ass", "Show.chs.ass", "Show.ass"):
                with open(os.path.join(tmp, n), "w", encoding="utf-8"):
                    pass
            found = core.find_subtitles(video, [])
            langs = [ass.language_from_name(p) for p in found]
            self.assertEqual(langs, sorted(langs, key=lambda x: x or "zzz"))


# ==========================================================================
# 字体索引与子集化
# ==========================================================================
@unittest.skipUnless(HAS_ASSETS, ASSETS_HINT)
class TestFonts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = fonts.FontIndex()
        cls.font_dir = TEST_FONTS
        cls.index.add_directory(cls.font_dir)

    def test_index_built(self):
        self.assertGreater(len(self.index), 0)

    def test_lookup_by_family(self):
        face = self.index.lookup("SubFontTest Sans")
        self.assertIsNotNone(face)
        self.assertTrue(face.path.endswith(".ttf"))

    def test_bold_selects_bold_face(self):
        face = self.index.match("SubFontTest Sans", bold=True)
        self.assertIsNotNone(face)
        self.assertEqual(face.weight, 700, "应该匹配到 Bold face")
        regular = self.index.match("SubFontTest Sans", bold=False)
        self.assertEqual(regular.weight, 400)

    def test_style_suffix_split(self):
        self.assertEqual(fonts.split_style_suffix("Agency FB Bold"), ("Agency FB", True, False))
        self.assertEqual(fonts.split_style_suffix("NotoSansSC-Bold"), ("NotoSansSC", True, False))
        self.assertEqual(fonts.split_style_suffix("Font Italic"), ("Font", False, True))
        self.assertEqual(fonts.split_style_suffix("Plain"), ("Plain", False, False))

    def test_crc32_stable(self):
        path = os.path.join(self.font_dir, "SubFontTestSans-Regular.ttf")
        self.assertEqual(fonts.crc32_of_file(path), fonts.crc32_of_file(path))
        self.assertRegex(fonts.crc32_of_file(path), r"^[0-9A-F]{8}$")

    def test_subset_renames_and_sizes(self):
        from fontTools.ttLib import TTFont
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(self.font_dir, "SubFontTestSans-Regular.ttf")
            out, crc = fonts.subset_font(src, 0, os.path.join(tmp, "Test.ttf"), "Hello")
            self.assertTrue(os.path.basename(out).endswith(".{0}.ttf".format(crc)),
                            "扩展名应只出现一次且带 CRC: " + out)
            self.assertLess(os.path.getsize(out), os.path.getsize(src))
            font = TTFont(out)
            names = {}
            for record in font["name"].names:
                if record.nameID in (1, 4, 6):
                    names.setdefault(record.nameID, record.toUnicode())
            expected = "Test." + crc
            self.assertEqual(names[1], expected, "Family 名应改为 原名.CRC")
            self.assertNotIn(" ", names[6], "PostScript 名不应含空格")

    def test_subset_of_ttc_face_is_single_sfnt(self):
        from fontTools.ttLib import TTFont
        ttc = os.path.join(BATCH_FONTS, "SubFontTestCollection.ttc")
        if not os.path.exists(ttc):
            self.skipTest("缺少 TTC 测试素材")
        with tempfile.TemporaryDirectory() as tmp:
            out, _crc = fonts.subset_font(ttc, 1, os.path.join(tmp, "Face.ttf"), "ABC")
            self.assertTrue(out.endswith(".ttf"), out)
            font = TTFont(out)
            self.assertEqual(font["OS/2"].usWeightClass, 700, "应取 TTC 里的 Bold face")

    def test_missing_glyphs_reported(self):
        src = os.path.join(self.font_dir, "SubFontTestSans-Regular.ttf")
        self.assertTrue(fonts.missing_glyphs(src, 0, "你好"), "该字体不含汉字")


# ==========================================================================
# 端到端封装
# ==========================================================================
@unittest.skipIf(MKVMERGE is None, "未安装 mkvmerge")
@unittest.skipUnless(HAS_ASSETS, ASSETS_HINT)
class TestEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.muxer = MkvmergeMuxer(MKVMERGE)
        cls.work = tempfile.mkdtemp(prefix="subfontmkv-test-")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def _identify(self, path):
        return self.muxer.identify(path)

    def test_full_pipeline(self):
        options = core.Options()
        options.font_dirs = [TEST_FONTS]
        options.system_fonts = False
        options.output_dir = self.work
        options.suffix = ".t1"

        video = TEST_VIDEO
        summary = core.run([video], options)
        self.assertEqual(summary["ok"], 1, summary)
        self.assertEqual(summary["failed"], 0)

        job = summary["jobs"][0]
        self.assertTrue(os.path.exists(job.output), job.output)
        info = self._identify(job.output)

        subs = [t for t in info["tracks"] if t["type"] == "subtitles"]
        videos = [t for t in info["tracks"] if t["type"] == "video"]
        self.assertEqual(len(videos), 1, "源视频轨应保留")
        self.assertEqual(len(subs), 2, "应有 2 条软字幕轨")

        langs = sorted(t["properties"]["language"] for t in subs)
        self.assertEqual(langs, ["chi", "jpn"])
        for track in subs:
            self.assertRegex(track["properties"]["language"], r"^[a-z]{3}$",
                             "语言必须是 ISO-639-2")
        self.assertTrue(any(t["properties"].get("track_name") == "chs" for t in subs))

        self.assertGreaterEqual(len(info["attachments"]), 1, "应内嵌字体附件")
        for attachment in info["attachments"]:
            self.assertRegex(attachment["file_name"], r"\.[0-9A-F]{8}\.(ttf|otf|ttc|otc)$",
                             "附件名应带 CRC32: " + attachment["file_name"])

        # 内嵌字幕引用的字体名必须与附件内部名称一致
        extracted = self._extract_subtitles(job.output, subs)
        attached_names = self._attachment_family_names(job.output, info)
        referenced = self._referenced_fonts(extracted)
        self.assertTrue(referenced, "内嵌字幕应引用被改名的字体")
        for name in referenced:
            self.assertIn(name, attached_names,
                          "字幕引用的 {0} 在内嵌字体里找不到".format(name))

    def _extract_subtitles(self, mkv, subs):
        import glob
        out_dir = os.path.join(self.work, "subs")
        os.makedirs(out_dir, exist_ok=True)
        exe = os.path.join(os.path.dirname(MKVMERGE), "mkvextract.exe")
        exe = exe if os.path.exists(exe) else "mkvextract"
        args = [exe, mkv, "tracks"]
        for i, track in enumerate(subs):
            args.append("{0}:{1}".format(track["id"], os.path.join(out_dir, "t{0}.ass".format(i))))
        subprocess.run(args, capture_output=True)
        text = ""
        for path in sorted(glob.glob(os.path.join(out_dir, "*.ass"))):
            with open(path, "r", encoding="utf-8-sig", errors="replace") as fp:
                text += fp.read()
        return text

    def _attachment_family_names(self, mkv, info):
        """把 MKV 里的附件字体抽出来，返回它们内部 Family 名的集合。"""
        from fontTools.ttLib import TTFont

        out_dir = os.path.join(self.work, "attach")
        os.makedirs(out_dir, exist_ok=True)
        exe = os.path.join(os.path.dirname(MKVMERGE), "mkvextract.exe")
        if not os.path.exists(exe):
            exe = "mkvextract"

        args = [exe, mkv, "attachments"]
        targets = []
        for index, attachment in enumerate(info.get("attachments", []), 1):
            target = os.path.join(out_dir, "att{0}".format(index))
            args.append("{0}:{1}".format(attachment["id"], target))
            targets.append(target)
        if len(args) > 3:
            subprocess.run(args, capture_output=True)

        names = set()
        for target in targets:
            if not os.path.exists(target):
                continue
            try:
                font = TTFont(target)
            except Exception:
                continue
            for record in font["name"].names:
                if record.nameID == 1:
                    names.add(record.toUnicode())
        return names

    def _referenced_fonts(self, text):
        import re
        found = set()
        for match in re.finditer(r"^Style:[^,]*,\s*([^,]+),", text, re.MULTILINE):
            found.add(match.group(1).strip())
        for match in re.finditer(r"\\fn([^\\}]+)", text):
            found.add(match.group(1).strip())
        return {f for f in found if "." in f}

    def test_dry_run_writes_nothing(self):
        options = core.Options()
        options.font_dirs = [TEST_FONTS]
        options.system_fonts = False
        options.output_dir = self.work
        options.suffix = ".dry"
        options.dry_run = True
        summary = core.run([TEST_VIDEO], options)
        self.assertEqual(summary["dry_run"], 1)
        self.assertFalse(os.path.exists(os.path.join(self.work, "Show EP01.dry.mkv")))

    def test_missing_subtitle_is_skipped(self):
        options = core.Options()
        options.system_fonts = False
        options.output_dir = self.work
        summary = core.run([os.path.join(ASSETS, "batch", "NoSubtitle.mkv")], options)
        self.assertEqual(summary["skipped"], 1, summary)

    def test_missing_font_still_muxes(self):
        options = core.Options()
        options.font_dirs = [BATCH_FONTS]
        options.system_fonts = False
        options.output_dir = self.work
        summary = core.run([os.path.join(ASSETS, "batch", "MissingFont.mkv")], options)
        job = summary["jobs"][0]
        self.assertEqual(job.status, "ok", job.message)
        self.assertIn("GhostFont NoSuch", job.missing_fonts)

    def test_output_name_collision_avoided(self):
        options = core.Options()
        options.font_dirs = [TEST_FONTS]
        options.system_fonts = False
        options.output_dir = self.work
        options.suffix = ".dup"
        video = TEST_VIDEO
        first = core.run([video], options)
        second = core.run([video], options)
        self.assertNotEqual(first["jobs"][0].output, second["jobs"][0].output,
                            "第二次不应覆盖第一次的输出")


# ==========================================================================
# 进度解析与实时输出
# ==========================================================================
class TestProgress(unittest.TestCase):
    def test_parse_both_formats(self):
        from subfontmkv.mux import parse_progress

        self.assertEqual(parse_progress("Progress: 42%"), 42)
        self.assertEqual(parse_progress("#GUI#progress 7%"), 7)
        self.assertEqual(parse_progress("Progress: 100%"), 100)
        self.assertEqual(parse_progress("Progress: 0%"), 0)

    def test_non_progress_lines(self):
        from subfontmkv.mux import parse_progress

        for line in ("mkvmerge v26.0.0 ('In The Game') 64-bit", "",
                     "'file.mkv': Using the demultiplexer", "Multiplexing took 0 seconds."):
            self.assertIsNone(parse_progress(line), line)

    def test_progress_is_clamped(self):
        from subfontmkv.mux import parse_progress

        self.assertEqual(parse_progress("Progress: 250%"), 100)
        self.assertEqual(parse_progress("Progress: -5%"), 0)

    @unittest.skipIf(MKVMERGE is None, "未安装 mkvmerge")
    @unittest.skipUnless(HAS_ASSETS, ASSETS_HINT)
    def test_muxer_reports_progress(self):
        """on_progress 必须在进程结束前被调用，而不是最后一次性给出。"""
        import time

        from subfontmkv.mux import MkvmergeMuxer

        muxer = MkvmergeMuxer(MKVMERGE)
        video = os.path.join(ASSETS, "Show EP01.mkv")
        sub = os.path.join(ASSETS, "Show EP01.chs.ass")
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out.mkv")
            events = []
            t0 = time.time()
            muxer.mux(video=video, output=out,
                      subtitles=[(sub, "chi", "chs")], attachments=(),
                      on_progress=lambda pct, line: events.append((time.time() - t0, pct)))
            elapsed = time.time() - t0
            self.assertTrue(os.path.exists(out), "应生成输出")
            self.assertTrue(events, "应至少上报一次进度")

            percents = [p for _t, p in events]
            self.assertEqual(max(percents), 100, percents)
            self.assertEqual(percents, sorted(percents), "进度必须单调不减: %r" % percents)
            # 关键：第一条进度必须早于进程结束时刻
            self.assertLess(events[0][0], elapsed,
                            "进度应实时上报（第一条 %.3fs < 总耗时 %.3fs）" % (events[0][0], elapsed))

    @unittest.skipIf(MKVMERGE is None, "未安装 mkvmerge")
    def test_run_command_streams_lines(self):
        """run_command 的 on_line 应在运行过程中被调用。"""
        from subfontmkv.mux import run_command

        lines = []
        run_command([MKVMERGE, "--version"], capture=True,
                    on_line=lambda line, stream: lines.append(line))
        self.assertTrue(any("mkvmerge" in ln for ln in lines), lines)


# ==========================================================================
# 辅助函数
# ==========================================================================
class TestCollectVideos(unittest.TestCase):
    def test_skips_own_outputs_when_scanning(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("Show.mkv", "Show.subfont.mkv", "Other.subfont.mkv", "Keep.mkv"):
                with open(os.path.join(tmp, name), "wb") as fp:
                    fp.write(b"x")
            found = core.collect_videos([tmp], recursive=False, suffix=".subfont")
            names = sorted(os.path.basename(p) for p in found)
            self.assertEqual(names, ["Keep.mkv", "Show.mkv"], names)

    def test_explicit_file_is_always_processed(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "Show.subfont.mkv")
            with open(target, "wb") as fp:
                fp.write(b"x")
            found = core.collect_videos([target], recursive=False, suffix=".subfont")
            self.assertEqual(found, [os.path.abspath(target)],
                             "显式指定的文件应照做，不做过滤")

    def test_no_suffix_disables_filtering(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("A.mkv", "A.subfont.mkv"):
                with open(os.path.join(tmp, name), "wb") as fp:
                    fp.write(b"x")
            found = core.collect_videos([tmp], recursive=False, suffix="")
            self.assertEqual(len(found), 2)


class TestCliDispatch(unittest.TestCase):
    def test_gui_subcommand(self):
        from subfontmkv import cli, gui

        calls = []
        original = gui.launch
        gui.launch = lambda argv=None: (calls.append(argv), 0)[1]
        try:
            self.assertEqual(cli.main(["gui", "a.mkv"]), 0)
            self.assertEqual(calls, [["a.mkv"]])
            self.assertEqual(cli.main(["界面"]), 0)
            self.assertEqual(calls[-1], [])
        finally:
            gui.launch = original

    def test_options_from_args(self):
        from subfontmkv import cli

        parser = cli.build_parser()
        args = parser.parse_args(["--no-subset", "--no-system-fonts", "--suffix", ".x",
                                  "--font-dir", "a", "--font-dir", "b", "--dry-run", "v.mkv"])
        options = cli.options_from_args(args)
        self.assertFalse(options.subset)
        self.assertFalse(options.system_fonts)
        self.assertEqual(options.suffix, ".x")
        self.assertEqual(options.font_dirs, ["a", "b"])
        self.assertTrue(options.dry_run)
        self.assertTrue(options.attach_full_fonts, "no-subset 应同时允许内嵌完整字体")

    def test_json_report_shape(self):
        from subfontmkv import cli, core

        job = core.Job(TEST_VIDEO)
        job.status = "ok"
        job.output = job.video
        summary = core.new_summary(1)
        summary["ok"] = 1
        summary["jobs"] = [job]
        report = cli._json_report(summary)
        self.assertEqual(report["tool"], "subfontmkv")
        self.assertEqual(report["ok"], 1)
        self.assertEqual(len(report["files"]), 1)
        json.dumps(report)   # 必须可序列化


class TestHelpers(unittest.TestCase):
    def test_extension_predicates(self):
        self.assertTrue(is_video("a.mkv"))
        self.assertTrue(is_video("a.MP4"))
        self.assertFalse(is_video("a.ass"))
        self.assertTrue(is_subtitle("a.ass"))
        self.assertTrue(is_subtitle("a.srt"))

    def test_sanitize_filename_keeps_cjk(self):
        self.assertEqual(fonts.sanitize_filename("微软雅黑"), "微软雅黑")
        self.assertNotIn("/", fonts.sanitize_filename("a/b:c*d"))

    def test_language_regex_accepts_iso(self):
        from subfontmkv.mux import RE_LANGUAGE
        for code in ("chi", "jpn", "eng", "zh", "und"):
            self.assertTrue(RE_LANGUAGE.match(code), code)
        self.assertFalse(RE_LANGUAGE.match("zh-Hans"))


if __name__ == "__main__":
    print("mkvmerge:", MKVMERGE or "未找到（端到端测试将跳过）")
    print("模式:", "quick" if QUICK else "完整")
    print("-" * 70)
    unittest.main(verbosity=2)