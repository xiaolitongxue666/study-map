#!/usr/bin/env python3
"""从目录页文字里抽出章节框架。

不打开 PDF，也不保留正文。一条记录只有层级、标题和页码。
转曲软件留下的「页面_001」不是目录，直接丢掉。
"""

from __future__ import annotations

import re

CANDIDATE_PAGES = 12
TEXT_LAYER_CHARS = 80

CORE_EDITIONS = {
    ("语文", "统编版"),
    ("数学", "人教版"),
    ("英语", "人教版"),
}
CORE_ROLES = {"同步练习", "专项"}

_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")
_FAKE_TITLE = re.compile(r"^(?:\d+_)?(?:转曲_)?页面[_-]?\d+$")
_PAGE_STAMP = re.compile(r"_\d+$")
_PAGE_STAMP_MIN = 8
_LESSON = re.compile(
    r"第\s*[0-9一二三四五六七八九十百零]+\s*课时"
    r"|第\s*[0-9一二三四五六七八九十百零]+\s*[课节]"
    r"|Lesson\s*\d+",
    re.IGNORECASE,
)
_UNIT = re.compile(
    r"第\s*[0-9一二三四五六七八九十百零]+\s*单元|Unit\s*\d+",
    re.IGNORECASE,
)
_HAS_WORD = re.compile(r"[A-Za-z\u4e00-\u9fff]")
_NUMBERED_ITEM = re.compile(r"^[0-9]+[\s.、．]")
_PAGE_HEADING = re.compile(r"^## 第 \d+ 页\s*$", re.MULTILINE)
_TRAILING_PAGE = re.compile(r"(\d{1,4})\s*$")
_TRAILING_LEADERS = re.compile(r"[\s.\u00b7\u2026\u2027\u30fb．。·…\-—_]+$")


def is_core_workbook(relative: str) -> bool:
    """课桌「练习」「提高」会打开的核心版 PDF。"""
    parts = tuple(part for part in relative.replace("\\", "/").split("/") if part)
    if len(parts) < 7 or parts[0] != "小学":
        return False
    if (parts[1], parts[2]) not in CORE_EDITIONS:
        return False
    return parts[5] in CORE_ROLES and parts[-1].lower().endswith(".pdf")


def is_fake_title(title: str) -> bool:
    compact = re.sub(r"\s+", "", title)
    if _FAKE_TITLE.fullmatch(compact):
        return True
    if "转曲" in compact and "页面" in compact:
        return True
    return bool(re.fullmatch(r"\d+_页面_\d+", compact))


def is_page_stamp_outline(entries: list[dict]) -> bool:
    """整组书签都是「书名_页码」时不是目录。不满 8 条不判，避免误伤短标题。"""
    if len(entries) < _PAGE_STAMP_MIN:
        return False
    return all(_PAGE_STAMP.search(str(entry.get("title", "")).strip()) for entry in entries)


def page_has_toc(text: str) -> bool:
    compact = text.replace(" ", "").replace("\u3000", "")
    return "目录" in compact


def has_text_layer(pages: list[str]) -> bool:
    return sum(len(page.strip()) for page in pages) >= TEXT_LAYER_CHARS


def entries_from_bookmarks(toc: list) -> list[dict]:
    entries = []
    for item in toc:
        if len(item) < 3:
            continue
        try:
            level = int(item[0])
            page = int(item[2])
        except (TypeError, ValueError):
            continue
        title = str(item[1]).strip()
        if page < 1 or len(title) < 2 or title.isdigit() or is_fake_title(title):
            continue
        if _HAS_WORD.search(title) is None:
            continue
        entries.append({"level": max(1, level), "title": title, "page": page})
    return entries


def parse_toc_pages(pages: list[str]) -> list[dict]:
    entries = []
    for page in pages:
        if not page_has_toc(page):
            continue
        for line in page.splitlines():
            parsed = parse_toc_line(line)
            if parsed is not None:
                entries.append(parsed)
    return entries


def parse_toc_line(line: str) -> dict | None:
    text = line.translate(_FULLWIDTH_DIGITS).strip()
    if not text:
        return None
    compact = text.replace(" ", "").replace("\u3000", "")
    if compact in {"目录", "Contents", "contents"}:
        return None
    match = _TRAILING_PAGE.search(text)
    if match is None:
        return None
    page = int(match.group(1))
    if page < 1:
        return None
    title = _TRAILING_LEADERS.sub("", text[: match.start()]).strip()
    title = re.sub(r"\s+", " ", title)
    if len(title) < 2 or title.isdigit() or is_fake_title(title):
        return None
    if title.replace(" ", "") == "目录":
        return None
    return {"level": entry_level(title), "title": title, "page": page}


def entry_level(title: str) -> int:
    if _LESSON.search(title) or _NUMBERED_ITEM.match(title):
        return 2
    if _UNIT.search(title):
        return 1
    return 1


def pages_from_markdown(markdown: str) -> list[str]:
    """mini-ocr 的 Markdown 按「## 第 N 页」切开，只留每页正文。"""
    matches = list(_PAGE_HEADING.finditer(markdown))
    if not matches:
        return [markdown] if markdown.strip() else []
    pages = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        pages.append(markdown[start:end])
    return pages


def clamp_entries(entries: list[dict], page_count: int) -> list[dict]:
    if page_count < 1:
        return []
    return [entry for entry in entries if 1 <= int(entry["page"]) <= page_count]
