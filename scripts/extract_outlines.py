#!/usr/bin/env python3
"""从资料库 PDF 抽出目录框架，写到 downloads/_index/pdf_outlines.json。

只保留层级、标题和页码，不保留正文。公开仓库不收这份索引。

前 12 页有文字层时，只解析含「目录」的页。没有文字层时，把这 12 页
做成一本短 PDF，交给旁边的 mini-ocr。识别结果用完就删，不写进
mini-ocr 的 cache/ 或 output/。

整组书签都是「书名_页码」时不当目录，改走文字层或 OCR。
已经写过的路径一律跳过，包括 source 为 none 的，中断后可以续跑。
要重试没有目录的书，加 --retry-none。逐页书签要先从索引里删掉路径，
再跑同一条命令，否则会被当成已经写过。

用法（必须用 mini-ocr 的 Python，系统 Python 没有 PyMuPDF）：

    python scripts/extract_outlines.py --core
    python scripts/extract_outlines.py --core --limit 1
    python scripts/extract_outlines.py --all
"""

from __future__ import annotations

import argparse
import shutil
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from downloads import common  # noqa: E402
import pdf_outline  # noqa: E402

LIBRARY = common.DOWNLOADS_ROOT / "library"
INDEX_PATH = common.DOWNLOADS_ROOT / "_index" / "pdf_outlines.json"
OCR_WORK = common.DOWNLOADS_ROOT / "_index" / "ocr-work"
MINI_OCR_ROOT = common.REPO_ROOT.parent / "mini-ocr"
SLICE_NAME = "toc.pdf"


def main() -> int:
    common.reconfigure_stdout()
    args = _parser().parse_args()
    if args.core == args.all:
        print("要指定 --core 或 --all 里的一个")
        return 2
    if not LIBRARY.is_dir():
        print(f"没有资料库目录：{LIBRARY}")
        return 1
    _silence_mupdf()
    records = _load_records()
    by_path = {item["path"]: item for item in records}
    pending = []
    for relative, path in _targets(args.core):
        existing = by_path.get(relative)
        if existing is not None and not (args.retry_none and existing.get("source") == "none"):
            continue
        pending.append((relative, path))
    if args.limit > 0:
        pending = pending[: args.limit]
    done = 0
    for relative, path in pending:
        try:
            record = extract_record(path, relative)
        except Exception as exc:
            print(f"失败 {relative}: {exc}")
            traceback.print_exc()
            continue
        by_path[relative] = record
        _write_index(list(by_path.values()))
        done += 1
        print(
            f"{done} {record['source']} 条目 {len(record['entries'])}  "
            f"{record['pages']}页  {relative}"
        )
    print(f"本轮写入 {done}  索引 {len(by_path)}  → {INDEX_PATH}")
    return 0


def extract_record(path: Path, relative: str) -> dict:
    import pymupdf

    document = pymupdf.open(path)
    try:
        page_count = document.page_count
        limit = min(pdf_outline.CANDIDATE_PAGES, page_count)
        texts = []
        for index in range(limit):
            try:
                texts.append(document[index].get_text("text") or "")
            except Exception:
                texts.append("")
        bookmarks = pdf_outline.entries_from_bookmarks(document.get_toc() or [])
    finally:
        document.close()

    if pdf_outline.is_page_stamp_outline(bookmarks):
        bookmarks = []
    if bookmarks:
        return _record(relative, page_count, "text", pdf_outline.clamp_entries(bookmarks, page_count))
    if pdf_outline.has_text_layer(texts):
        entries = pdf_outline.clamp_entries(pdf_outline.parse_toc_pages(texts), page_count)
        source = "text" if entries else "none"
        return _record(relative, page_count, source, entries)

    markdown = ocr_candidate_pages(path, limit)
    pages = pdf_outline.pages_from_markdown(markdown)
    entries = pdf_outline.clamp_entries(pdf_outline.parse_toc_pages(pages), page_count)
    source = "ocr" if entries else "none"
    return _record(relative, page_count, source, entries)


def ocr_candidate_pages(path: Path, page_count: int) -> str:
    """识别前若干页。工作目录在 downloads/_index/ocr-work，用完删掉 Markdown。"""
    import pymupdf

    if not (MINI_OCR_ROOT / "mini_ocr").is_dir():
        raise RuntimeError(f"找不到 mini-ocr：{MINI_OCR_ROOT}")
    if str(MINI_OCR_ROOT) not in sys.path:
        sys.path.insert(0, str(MINI_OCR_ROOT))
    from dataclasses import replace

    from mini_ocr.config import PathConfig, load_config
    from mini_ocr.pipeline.runner import process_pdf

    OCR_WORK.mkdir(parents=True, exist_ok=True)
    slice_path = OCR_WORK / SLICE_NAME
    output_dir = OCR_WORK / "output"
    if output_dir.exists():
        shutil.rmtree(output_dir)
    source = pymupdf.open(path)
    try:
        short = pymupdf.open()
        try:
            last = min(page_count, source.page_count) - 1
            if last < 0:
                return ""
            short.insert_pdf(source, from_page=0, to_page=last)
            short.save(slice_path)
        finally:
            short.close()
    finally:
        source.close()

    loaded = load_config(MINI_OCR_ROOT / "config.yaml")
    config = replace(
        loaded,
        batch=replace(loaded.batch, resume=False, skip_existing=False),
        paths=PathConfig(
            input_dir=OCR_WORK / "input",
            output_dir=output_dir,
            model_dir=loaded.paths.model_dir,
            cache_dir=OCR_WORK / "cache",
            log_dir=OCR_WORK / "logs",
            database=OCR_WORK / "cache" / "mini_ocr.db",
        ),
    )
    try:
        result = process_pdf(slice_path, config)
        markdown_path = output_dir / slice_path.stem / f"{slice_path.stem}.md"
        if not markdown_path.is_file():
            raise RuntimeError(result.message or "mini-ocr 没有写出 Markdown")
        return markdown_path.read_text(encoding="utf-8")
    finally:
        if output_dir.exists():
            shutil.rmtree(output_dir, ignore_errors=True)
        if slice_path.exists():
            slice_path.unlink()


def _record(relative: str, page_count: int, source: str, entries: list[dict]) -> dict:
    return {
        "path": relative,
        "pages": page_count,
        "source": source,
        "entries": entries,
    }


def _targets(core_only: bool) -> list[tuple[str, Path]]:
    found = []
    for path in LIBRARY.rglob("*"):
        if not path.is_file() or path.suffix.lower() != ".pdf":
            continue
        relative = path.relative_to(LIBRARY).as_posix()
        if core_only and not pdf_outline.is_core_workbook(relative):
            continue
        found.append((relative, path))
    found.sort(key=lambda item: item[0])
    return found


def _load_records() -> list[dict]:
    if not INDEX_PATH.is_file():
        return []
    payload = common.read_json(INDEX_PATH, {})
    files = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(files, list):
        return []
    return [item for item in files if isinstance(item, dict) and item.get("path")]


def _write_index(records: list[dict]) -> None:
    records.sort(key=lambda item: item["path"])
    common.write_json_atomic(INDEX_PATH, {
        "generated_at": common.now_iso(),
        "root": "downloads/library",
        "files": records,
    })


def _silence_mupdf() -> None:
    import pymupdf

    tools = getattr(pymupdf, "TOOLS", None)
    if tools is not None and hasattr(tools, "mupdf_display_errors"):
        tools.mupdf_display_errors(False)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="抽出 PDF 目录框架")
    parser.add_argument("--core", action="store_true", help="统编语文、人教数学、人教英语的同步练习和专项")
    parser.add_argument("--all", action="store_true", help="资料库里全部 PDF")
    parser.add_argument("--limit", type=int, default=0, help="只处理这么多个尚未写入的文件")
    parser.add_argument("--retry-none", action="store_true", help="重跑已经记成 none 的文件")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
