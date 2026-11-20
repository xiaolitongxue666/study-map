#!/usr/bin/env python3
"""按课桌会用到的槽位，列出某一册要从资料库下载的系列目录。

规则与 library_query.py 相同：精确年级、空年级、「X至Y年级」会算进所问年级；
上册不进下册；空册次和「上下册」会进所问册次。课桌在「思维专题」「自然拼读」
上不按教材版本过滤，这两类目录会额外列入该学科的每一册。

用法：
    python scripts/grade_bundle.py --subject 数学 --edition 人教版 --grade 三年级 --volume 下册
    python scripts/grade_bundle.py --write
"""

from __future__ import annotations

import argparse
import json
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from downloads import common  # noqa: E402
import library_query  # noqa: E402

GRADES = ("一年级", "二年级", "三年级", "四年级", "五年级", "六年级")
VOLUMES = ("上册", "下册")
DESK_EXTRA_ROLES = ("思维专题", "自然拼读")
BUNDLE_PATH = common.REPO_ROOT / "data" / "grade_bundles.json"


def main(argv: list[str] | None = None) -> int:
    common.reconfigure_stdout()
    parser = argparse.ArgumentParser(description="列出某一册要下载的资料库目录")
    parser.add_argument("--subject", default="", help="学科，如 数学")
    parser.add_argument("--edition", default="", help="版本，如 人教版")
    parser.add_argument("--grade", default="", help="年级，如 三年级")
    parser.add_argument("--volume", default="", help="册次：上册 或 下册")
    parser.add_argument("--write", action="store_true", help="写出 data/grade_bundles.json")
    arguments = parser.parse_args(argv)

    payload = json.loads(library_query.CATALOG_PATH.read_text(encoding="utf-8"))
    series = payload.get("series", [])
    if arguments.write:
        document = build_document(series, payload.get("generated_at", ""))
        common.write_json_atomic(BUNDLE_PATH, document)
        print(
            f"{len(document['bundles'])} 个年级包  → {BUNDLE_PATH}"
        )
        return 0

    if not arguments.subject or not arguments.grade or not arguments.volume:
        print("要指定 --subject --grade --volume，或用 --write 写出全部年级包。")
        return 1
    chosen = select_records(
        series,
        arguments.subject,
        arguments.edition,
        arguments.grade,
        arguments.volume,
    )
    if not chosen:
        print("没有对上的系列。")
        return 0
    files, total = _totals(chosen)
    print(
        f"{len(chosen)} 个系列  {files} 个文件  {common.format_bytes(total)}  "
        f"（目录生成于 {payload.get('generated_at', '')}）"
    )
    for record, reason in chosen:
        label = "课桌通用" if reason == "desk" else "版本"
        print(
            f"{label}  {record.get('role') or '其他'}  "
            f"{record.get('files')} 个  "
            f"{common.format_bytes(int(record.get('bytes') or 0)):>10}  "
            f"downloads/library/{record.get('path')}"
        )
    return 0


def build_document(series: list[dict], catalog_generated_at: str) -> dict:
    pairs = sorted({
        (str(record.get("subject") or ""), str(record.get("edition") or ""))
        for record in series
        if record.get("subject") and record.get("edition")
    })
    bundles = []
    for subject, edition in pairs:
        for grade in GRADES:
            for volume in VOLUMES:
                chosen = select_records(series, subject, edition, grade, volume)
                if not chosen:
                    continue
                files, total = _totals(chosen)
                bundles.append({
                    "subject": subject,
                    "edition": edition,
                    "grade": grade,
                    "volume": volume,
                    "files": files,
                    "bytes": total,
                    "paths": [
                        {
                            "path": record.get("path") or "",
                            "files": int(record.get("files") or 0),
                            "bytes": int(record.get("bytes") or 0),
                            "role": record.get("role") or "",
                            "reason": reason,
                        }
                        for record, reason in chosen
                    ],
                })
    return {
        "generated_at": common.now_iso(),
        "catalog_generated_at": catalog_generated_at,
        "root": "downloads/library",
        "cloud_root": "study-map/downloads",
        "desk_extra_roles": list(DESK_EXTRA_ROLES),
        "bundles": bundles,
    }


def select_records(
    series: list[dict],
    subject: str,
    edition: str,
    grade: str,
    volume: str,
) -> list[tuple[dict, str]]:
    """返回 (系列, reason)。reason 为 edition 或 desk。"""
    chosen: list[tuple[dict, str]] = []
    seen: set[str] = set()
    arguments = argparse.Namespace(
        subject=subject,
        edition=edition,
        grade=grade,
        volume=volume,
        role="",
    )
    for record in series:
        if not library_query._matches(record, arguments):
            continue
        path = str(record.get("path") or "")
        if path in seen:
            continue
        chosen.append((record, "edition"))
        seen.add(path)
    if not edition:
        return chosen
    for role in DESK_EXTRA_ROLES:
        extra = argparse.Namespace(
            subject=subject,
            edition="",
            grade=grade,
            volume=volume,
            role=role,
        )
        for record in series:
            path = str(record.get("path") or "")
            if path in seen or not library_query._matches(record, extra):
                continue
            chosen.append((record, "desk"))
            seen.add(path)
    return chosen


def _totals(chosen: list[tuple[dict, str]]) -> tuple[int, int]:
    files = sum(int(record.get("files") or 0) for record, _reason in chosen)
    total = sum(int(record.get("bytes") or 0) for record, _reason in chosen)
    return files, total


if __name__ == "__main__":
    raise SystemExit(main())
