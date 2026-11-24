#!/usr/bin/env python3
"""目录行解析。不打开真实 PDF。"""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))

import pdf_outline


class FakeBookmarkTests(unittest.TestCase):
    def test_curved_page_labels_are_dropped(self):
        toc = [
            [1, "义务教育体育与健康课程标准（2022年版）-转曲_页面_001", 1],
            [1, "1_页面_02", 2],
            [1, "页面_003", 3],
            [1, "第一单元 准备课", 4],
        ]
        entries = pdf_outline.entries_from_bookmarks(toc)
        self.assertEqual(entries, [{"level": 1, "title": "第一单元 准备课", "page": 4}])

    def test_digit_only_bookmarks_are_dropped(self):
        toc = [[1, "00", 2], [1, "10", 12], [1, "第一单元 准备课", 4]]
        titles = [item["title"] for item in pdf_outline.entries_from_bookmarks(toc)]
        self.assertEqual(titles, ["第一单元 准备课"])

    def test_page_stamp_set_is_not_an_outline(self):
        stamps = [{"level": 1, "title": f"练习帮_{index}", "page": index} for index in range(1, 10)]
        self.assertTrue(pdf_outline.is_page_stamp_outline(stamps))
        mixed = stamps[:3] + [{"level": 1, "title": "第一单元", "page": 4}]
        self.assertFalse(pdf_outline.is_page_stamp_outline(mixed))
        self.assertFalse(pdf_outline.is_page_stamp_outline(stamps[:3]))


class TocLineTests(unittest.TestCase):
    def test_dotted_unit_and_numbered_lesson(self):
        page = "\n".join([
            "目录",
            "第一单元 大青树下的小学 …… 4",
            "1 古诗三首 ............ 6",
            "正文不是目录",
        ])
        other = "第一单元 不会被读到 9"
        entries = pdf_outline.parse_toc_pages([other, page])
        self.assertEqual(entries, [
            {"level": 1, "title": "第一单元 大青树下的小学", "page": 4},
            {"level": 2, "title": "1 古诗三首", "page": 6},
        ])

    def test_spaced_toc_heading_and_fullwidth_digits(self):
        page = "目 录\n第１课 古诗三首 ８"
        entries = pdf_outline.parse_toc_pages([page])
        self.assertEqual(entries, [{"level": 2, "title": "第1课 古诗三首", "page": 8}])

    def test_spaced_lesson_heading_is_level_two(self):
        parsed = pdf_outline.parse_toc_line("第 2课时 比多少 4")
        self.assertEqual(parsed, {"level": 2, "title": "第 2课时 比多少", "page": 4})

    def test_contents_heading_is_not_an_entry(self):
        self.assertIsNone(pdf_outline.parse_toc_line("目录 1"))
        self.assertIsNone(pdf_outline.parse_toc_line("2024"))


class MarkdownPagesTests(unittest.TestCase):
    def test_splits_on_page_headings(self):
        markdown = "## 第 1 页\n封面\n\n## 第 2 页\n目录\n第一单元 准备课 3\n"
        pages = pdf_outline.pages_from_markdown(markdown)
        self.assertEqual(len(pages), 2)
        entries = pdf_outline.parse_toc_pages(pages)
        self.assertEqual(entries, [{"level": 1, "title": "第一单元 准备课", "page": 3}])


class CoreSelectionTests(unittest.TestCase):
    def test_core_practice_and_stretch_only(self):
        self.assertTrue(pdf_outline.is_core_workbook(
            "小学/语文/统编版/三年级/上册/同步练习/53天天练/a.pdf"
        ))
        self.assertTrue(pdf_outline.is_core_workbook(
            "小学/数学/人教版/一年级/上册/专项/口算/b.pdf"
        ))
        self.assertTrue(pdf_outline.is_core_workbook(
            "小学/英语/人教版/三年级/上册/同步练习/练习帮/PEP版/c.pdf"
        ))
        self.assertFalse(pdf_outline.is_core_workbook(
            "小学/数学/人教版/一年级/上册/试卷/53全优卷/d.pdf"
        ))
        self.assertFalse(pdf_outline.is_core_workbook(
            "小学/数学/北师大版/一年级/上册/同步练习/练习/e.pdf"
        ))
        self.assertFalse(pdf_outline.is_core_workbook(
            "小学/数学/人教版/一年级/上册/教材解读/全解/f.pdf"
        ))


class ClampTests(unittest.TestCase):
    def test_page_past_the_end_is_dropped(self):
        entries = [{"level": 1, "title": "第一单元", "page": 90}]
        self.assertEqual(pdf_outline.clamp_entries(entries, 40), [])
        self.assertEqual(
            pdf_outline.clamp_entries([{"level": 1, "title": "第一单元", "page": 4}], 40),
            [{"level": 1, "title": "第一单元", "page": 4}],
        )


if __name__ == "__main__":
    unittest.main()
