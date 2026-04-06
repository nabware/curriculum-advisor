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


def extract_course_code(title_text: str) -> str | None:
    match = re.match(r"^([A-Z]{2,6}\s+\d+[A-Z]*)\b", title_text)
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(1)).strip().upper()


def parse_course_descriptions(html_text: str) -> list[tuple[str, str, str]]:
    blocks = re.findall(r'<div class="courseblock">(.*?)</div>', html_text, flags=re.IGNORECASE | re.DOTALL)
    rows: list[tuple[str, str, str]] = []

    for block in blocks:
        title_match = re.search(
            r'<p class="courseblocktitle"><strong>(.*?)</strong></p>',
            block,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not title_match:
            continue

        title_text = html_to_text(html.unescape(title_match.group(1)))
        course_code = extract_course_code(title_text)
        if not course_code:
            continue

        description_html = block[title_match.end() :]
        description_text = html_to_text(html.unescape(description_html))
        if not description_text:
            continue

        rows.append((course_code, title_text, description_text))

    return rows


def parse_professor_profiles(html_text: str) -> list[tuple[str, str | None, str | None, str | None]]:
    blocks = re.findall(
        r'<div class="pl-component pl-component--people people">(.*?)</div>\s*</div>',
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    rows: list[tuple[str, str | None, str | None, str | None]] = []

    for block in blocks:
        name_match = re.search(
            r'<div class="people-name">\s*<strong><a href="([^"]+)"[^>]*>(.*?)</a></strong>',
            block,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not name_match:
            continue

        profile_url = html.unescape(name_match.group(1)).strip()
        name = html_to_text(html.unescape(name_match.group(2)))
        if not name:
            continue

        title_match = re.search(
            r'<div class="people-title">\s*<strong>(.*?)</strong>',
            block,
            flags=re.IGNORECASE | re.DOTALL,
        )
        title = html_to_text(html.unescape(title_match.group(1))) if title_match else None

        image_match = re.search(
            r'<div class="people-image">\s*<img[^>]*src="([^"]+)"',
            block,
            flags=re.IGNORECASE | re.DOTALL,
        )
        image_src = html.unescape(image_match.group(1)).strip() if image_match else None

        rows.append((name, title, image_src, profile_url))

    return rows


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS course_descriptions;
        DROP TABLE IF EXISTS professor_profiles;

        CREATE TABLE course_descriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_code TEXT NOT NULL UNIQUE,
            course_title TEXT NOT NULL,
            description TEXT NOT NULL,
            source_file TEXT NOT NULL,
            imported_at TEXT NOT NULL
        );

        CREATE TABLE professor_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            professor_name TEXT NOT NULL UNIQUE,
            title TEXT,
            image_src TEXT,
            profile_url TEXT,
            source_file TEXT NOT NULL,
            imported_at TEXT NOT NULL
        );
        """
    )


def import_course_descriptions(conn: sqlite3.Connection, source_file: Path, source_root: Path) -> int:
    raw_content = source_file.read_text(encoding="utf-8", errors="ignore")
    imported_at = datetime.now(timezone.utc).isoformat()
    rows = parse_course_descriptions(raw_content)

    conn.executemany(
        """
        INSERT OR REPLACE INTO course_descriptions (
            course_code,
            course_title,
            description,
            source_file,
            imported_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        [
            (
                course_code,
                course_title,
                description,
                str(source_file.relative_to(source_root)),
                imported_at,
            )
            for course_code, course_title, description in rows
        ],
    )

    return len(rows)


def import_professor_profiles(conn: sqlite3.Connection, source_file: Path, source_root: Path) -> int:
    raw_content = source_file.read_text(encoding="utf-8", errors="ignore")
    imported_at = datetime.now(timezone.utc).isoformat()
    rows = parse_professor_profiles(raw_content)

    conn.executemany(
        """
        INSERT OR REPLACE INTO professor_profiles (
            professor_name,
            title,
            image_src,
            profile_url,
            source_file,
            imported_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                professor_name,
                title,
                image_src,
                profile_url,
                str(source_file.relative_to(source_root)),
                imported_at,
            )
            for professor_name, title, image_src, profile_url in rows
        ],
    )

    return len(rows)


def main() -> None:
    project_root = PROJECT_ROOT
    default_courses_file = project_root / "data" / "raw" / "class_descriptions" / "Computer Science (CSC) _ San Francisco State University Bulletin.html"
    default_people_file = project_root / "data" / "raw" / "professor_profiles" / "People _ Department of Computer Science.html"
    default_db = get_database_path()

    parser = argparse.ArgumentParser(description="Import course descriptions and professor profiles into SQLite.")
    parser.add_argument("--courses-file", type=Path, default=default_courses_file)
    parser.add_argument("--people-file", type=Path, default=default_people_file)
    parser.add_argument("--db-path", type=Path, default=default_db)
    args = parser.parse_args()

    with sqlite3.connect(args.db_path) as conn:
        init_schema(conn)
        course_count = import_course_descriptions(conn, args.courses_file, project_root)
        professor_count = import_professor_profiles(conn, args.people_file, project_root)
        conn.commit()

    print(
        f"Imported course descriptions={course_count}, professor profiles={professor_count} into {args.db_path}"
    )


if __name__ == "__main__":
    main()