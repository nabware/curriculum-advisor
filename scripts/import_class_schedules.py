#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.core.database import get_database_path


def parse_term_from_filename(file_name: str) -> str:
    lower_name = file_name.lower()
    match = re.search(r"(spring|summer|fall|winter)[_\s-]?(\d{4})", lower_name)
    if not match:
        return Path(file_name).stem
    return f"{match.group(1).capitalize()} {match.group(2)}"


def html_to_text(html_text: str) -> str:
    cleaned = re.sub(r"<script\b[^>]*>.*?</script>", " ", html_text, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"<style\b[^>]*>.*?</style>", " ", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)

    replacements = {
        "&nbsp;": " ",
        "&amp;": "&",
        "&lt;": "<",
        "&gt;": ">",
        "&quot;": '"',
        "&#39;": "'",
    }
    for entity, replacement in replacements.items():
        cleaned = cleaned.replace(entity, replacement)

    return re.sub(r"\s+", " ", cleaned).strip()


def extract_anchor_text(block: str, id_prefix: str) -> str | None:
    match = re.search(
        rf'id="{re.escape(id_prefix)}\$\d+"[^>]*>\s*(.*?)\s*</a>',
        block,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    text = html_to_text(html.unescape(match.group(1)))
    return text or None


def extract_span_text(block: str, id_prefix: str) -> str | None:
    match = re.search(
        rf'id="{re.escape(id_prefix)}\$\d+"[^>]*>\s*(.*?)\s*</span>',
        block,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    text = html_to_text(html.unescape(match.group(1)))
    return text or None


def parse_schedule_rows(html_text: str, term: str, source_file: str) -> list[dict[str, str | None]]:
    """Extract normalized class schedule rows from PeopleSoft class-search HTML."""
    course_pattern = re.compile(
        r'Collapse section\s+([A-Z]{2,6}\s+\d+[A-Z]*)\s+-\s+([^"<]+)',
        flags=re.IGNORECASE,
    )

    rows: list[dict[str, str | None]] = []
    course_matches = list(course_pattern.finditer(html_text))

    for idx, course_match in enumerate(course_matches):
        course_code = re.sub(r"\s+", " ", html.unescape(course_match.group(1))).strip().upper()
        course_title = html_to_text(html.unescape(course_match.group(2)))

        block_start = course_match.end()
        block_end = course_matches[idx + 1].start() if idx + 1 < len(course_matches) else len(html_text)
        block = html_text[block_start:block_end]

        meeting_row_pattern = re.compile(
            r'<tr\s+id="trSSR_CLSRCH_MTG1\$[^\"]+".*?>\s*(.*?)\s*</tr>',
            flags=re.IGNORECASE | re.DOTALL,
        )
        meeting_rows = list(meeting_row_pattern.finditer(block))

        if not meeting_rows:
            rows.append(
                {
                    "term": term,
                    "course_code": course_code,
                    "course_title": course_title,
                    "class_number": None,
                    "section": None,
                    "days_times": None,
                    "room": None,
                    "instructor": None,
                    "meeting_dates": None,
                    "status": None,
                    "source_file": source_file,
                }
            )
            continue

        for meeting_row in meeting_rows:
            row_html = meeting_row.group(1)
            status_match = re.search(
                r'DERIVED_CLSRCH_SSR_STATUS_LONG\$\d+.*?<img[^>]*alt="([^"]+)"',
                row_html,
                flags=re.IGNORECASE | re.DOTALL,
            )
            status = html_to_text(html.unescape(status_match.group(1))) if status_match else None

            rows.append(
                {
                    "term": term,
                    "course_code": course_code,
                    "course_title": course_title,
                    "class_number": extract_anchor_text(row_html, "MTG_CLASS_NBR"),
                    "section": extract_anchor_text(row_html, "MTG_CLASSNAME"),
                    "days_times": extract_span_text(row_html, "MTG_DAYTIME"),
                    "room": extract_span_text(row_html, "MTG_ROOM"),
                    "instructor": extract_span_text(row_html, "MTG_INSTR"),
                    "meeting_dates": extract_span_text(row_html, "MTG_TOPIC"),
                    "status": status,
                    "source_file": source_file,
                }
            )

    return rows


def init_schema(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS class_schedule_courses;")
    conn.execute("DROP TABLE IF EXISTS class_schedules;")
    conn.execute(
        """
        CREATE TABLE class_schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            term TEXT NOT NULL,
            course_code TEXT NOT NULL,
            course_title TEXT,
            class_number TEXT,
            section TEXT,
            days_times TEXT,
            room TEXT,
            instructor TEXT,
            meeting_dates TEXT,
            status TEXT,
            source_file TEXT NOT NULL,
            imported_at TEXT NOT NULL
        );
        """
    )


def upsert_file(conn: sqlite3.Connection, file_path: Path, source_root: Path) -> None:
    raw_content = file_path.read_text(encoding="utf-8", errors="ignore")
    term = parse_term_from_filename(file_path.name)
    imported_at = datetime.now(timezone.utc).isoformat()

    schedule_rows = parse_schedule_rows(
        html_text=raw_content,
        term=term,
        source_file=str(file_path.relative_to(source_root)),
    )
    if not schedule_rows:
        return

    conn.executemany(
        """
        INSERT INTO class_schedules (
            term,
            course_code,
            course_title,
            class_number,
            section,
            days_times,
            room,
            instructor,
            meeting_dates,
            status,
            source_file,
            imported_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                row["term"],
                row["course_code"],
                row["course_title"],
                row["class_number"],
                row["section"],
                row["days_times"],
                row["room"],
                row["instructor"],
                row["meeting_dates"],
                row["status"],
                row["source_file"],
                imported_at,
            )
            for row in schedule_rows
        ],
    )


def import_class_schedules(source_dir: Path, db_path: Path, project_root: Path) -> int:
    html_files = sorted(source_dir.glob("*.html"))
    if not html_files:
        return 0

    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        init_schema(conn)
        for html_file in html_files:
            upsert_file(conn, html_file, source_root=project_root)
        conn.commit()

    return len(html_files)


def main() -> None:
    project_root = PROJECT_ROOT
    default_source_dir = project_root / "data" / "raw" / "class_schedules"
    default_db = get_database_path()

    parser = argparse.ArgumentParser(
        description="Import class schedule HTML files into SQLite."
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=default_source_dir,
        help=f"Directory containing class schedule HTML files. Default: {default_source_dir}",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=default_db,
        help=f"SQLite database path. Default: {default_db}",
    )
    args = parser.parse_args()

    imported_count = import_class_schedules(
        source_dir=args.source_dir,
        db_path=args.db_path,
        project_root=project_root,
    )

    print(f"Imported {imported_count} class schedule files into {args.db_path}")


if __name__ == "__main__":
    main()
