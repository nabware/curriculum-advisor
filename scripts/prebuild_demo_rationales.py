#!/usr/bin/env python3
"""Precompute per-course recommendation rationale templates and store them in SQLite.

Runtime chat will call Llama 3.2 3B for fresh, student-specific rationales.
This script provides a fallback so the chat experience still feels conversational
when Ollama is unavailable. Templates are deterministic and parameter-free.

Storage:
    Adds (or refreshes) the `recommendation_rationale_template` column on
    `course_descriptions` and writes one row per known course code.

Usage:
    python scripts/prebuild_demo_rationales.py
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.core.database import get_database_path


def ensure_column(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(course_descriptions)").fetchall()}
    if "recommendation_rationale_template" not in columns:
        conn.execute(
            "ALTER TABLE course_descriptions ADD COLUMN recommendation_rationale_template TEXT"
        )


def _strip_leading_prereq_block(description: str) -> str:
    import re

    cleaned = re.sub(
        r"^\s*Prerequisites?(?:\s+for\s+[A-Z]+\s*\d+\w*)?\s*:.*?\.\s*",
        "",
        description.strip(),
        count=1,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return cleaned.strip()


def build_template(course_code: str, title: str | None, description: str | None,
                   group_name: str | None, prereq_text: str | None) -> str:
    title_clause = (title or course_code).strip()
    group_clause = f" toward your {group_name.strip()}" if group_name and group_name.strip() else ""
    prereq_clause = (
        f" Builds on {prereq_text.strip().rstrip('.')}." if prereq_text and prereq_text.strip()
        else ""
    )

    summary = ""
    if description and description.strip():
        cleaned_description = _strip_leading_prereq_block(description)
        first_sentence = cleaned_description.split(".")[0].strip()
        if len(first_sentence) > 140:
            first_sentence = first_sentence[:137].rstrip() + "..."
        if first_sentence:
            summary = f" {first_sentence}."

    return (
        f"{course_code} ({title_clause}) is a strong fit{group_clause}.{summary}{prereq_clause}"
    ).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=get_database_path())
    args = parser.parse_args()

    if not args.db_path.exists():
        print(f"Database not found: {args.db_path}", file=sys.stderr)
        return 1

    with sqlite3.connect(args.db_path) as conn:
        ensure_column(conn)

        course_rows = conn.execute(
            """
            SELECT cd.course_code, cd.description, rgc.course_name, rg.group_name
            FROM course_descriptions cd
            LEFT JOIN requirement_group_courses rgc
                ON UPPER(rgc.course_code) = UPPER(cd.course_code)
            LEFT JOIN requirement_groups rg
                ON rg.id = rgc.group_id
            GROUP BY cd.course_code
            """
        ).fetchall()

        prereq_text_by_course: dict[str, str] = {}
        for row in conn.execute(
            "SELECT course_code, raw_text FROM course_prerequisites GROUP BY course_code"
        ).fetchall():
            code = (row[0] or "").strip().upper()
            if code:
                prereq_text_by_course[code] = (row[1] or "").strip()

        updates = 0
        for course_code, description, course_name, group_name in course_rows:
            normalized = (course_code or "").strip().upper()
            if not normalized:
                continue
            template = build_template(
                normalized,
                course_name or normalized,
                description,
                group_name,
                prereq_text_by_course.get(normalized),
            )
            conn.execute(
                "UPDATE course_descriptions SET recommendation_rationale_template = ? "
                "WHERE UPPER(course_code) = ?",
                (template, normalized),
            )
            updates += 1

        conn.commit()
        print(f"Wrote {updates} rationale template(s) into course_descriptions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
