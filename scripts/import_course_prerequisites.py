#!/usr/bin/env python3
"""Import course prerequisites from SFSU catalog HTML into a structured DAG table.

Prereq sentences in the catalog look like:
  - "Prerequisite: CSC 101 with a grade of C or better."
  - "Prerequisites: CSC 210 or CSC 215; concurrent enrollment in CSC 220."
  - "Prerequisites: CSC 220 and CSC 317 with grades of C or better."
  - "Prerequisite: CSC 411 (may be taken concurrently)."

The parser produces a DNF representation:
  - Multiple `clause_index` values are AND'd together (all clauses must be satisfied)
  - Within a single `clause_index`, multiple `prereq_course_code` rows are OR'd
  - `concurrent_allowed=1` means the prereq can also be satisfied by concurrent enrollment
  - `recommended_only=1` means the catalog says "recommended" — not a hard block

Non-course prereqs ("upper-division standing", "permission of instructor") are stored
in `course_prerequisite_notes` for transparency but never block recommendations.
"""
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

DEFAULT_INPUT_DIR = PROJECT_ROOT / "data" / "raw" / "class_descriptions"

COURSE_CODE_PATTERN = re.compile(r"\b([A-Z]{2,6})[\s\u00a0]+(\d{2,3}[A-Z]{0,3})\b")
COURSE_BLOCK_PATTERN = re.compile(
    r'<div class="courseblock">(.*?)</div>',
    flags=re.IGNORECASE | re.DOTALL,
)
COURSE_TITLE_PATTERN = re.compile(
    r'<p class="courseblocktitle"><strong>(.*?)</strong></p>',
    flags=re.IGNORECASE | re.DOTALL,
)
PREREQ_BLOCK_PATTERN = re.compile(
    r'<p class="courseblockextra">\s*Prerequisites?:\s*(.*?)</p>',
    flags=re.IGNORECASE | re.DOTALL,
)


def html_to_text(value: str) -> str:
    cleaned = re.sub(r"<script\b[^>]*>.*?</script>", " ", value, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"<style\b[^>]*>.*?</style>", " ", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = html.unescape(cleaned)
    cleaned = cleaned.replace("\u00a0", " ")
    return re.sub(r"\s+", " ", cleaned).strip()


def normalize_code(dept: str, number: str) -> str:
    return f"{dept.strip().upper()} {number.strip().upper()}"


def extract_course_code(title_text: str) -> str | None:
    match = COURSE_CODE_PATTERN.match(title_text)
    if not match:
        return None
    return normalize_code(match.group(1), match.group(2))


def trim_prereq_sentence(text: str) -> str:
    """Strip trailing 'with a grade of C or better' style boilerplate from the prereq text."""
    cleaned = text.strip().rstrip(".")
    cleaned = re.sub(
        r"\s+with\s+(a\s+)?grades?\s+of\s+C[^.;]*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\s+or\s+(graduate|equivalent|consent|permission)[^.;]*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.strip(" .;,")


def parse_prereq_clauses(prereq_text: str) -> tuple[list[list[dict[str, object]]], list[str]]:
    """Return (clauses, freeform_notes).

    Each clause is a list of dicts: {course_code, concurrent_allowed, recommended_only}.
    All clauses must be satisfied (AND); within a clause, alternatives are OR'd.
    Free-form notes capture non-course prereq language we intentionally don't enforce.
    """
    text = trim_prereq_sentence(prereq_text)
    if not text:
        return [], []

    notes: list[str] = []
    clauses: list[list[dict[str, object]]] = []

    segments = re.split(r"\s*;\s*", text)
    for raw_segment in segments:
        segment = raw_segment.strip()
        if not segment:
            continue

        recommended_only = bool(
            re.search(r"\b(is\s+)?recommended\b", segment, flags=re.IGNORECASE)
            and "required" not in segment.lower()
        )

        course_matches = list(COURSE_CODE_PATTERN.finditer(segment))
        if not course_matches:
            collapsed = re.sub(r"\s+", " ", segment).strip()
            if collapsed:
                notes.append(collapsed)
            continue

        current_clause: list[dict[str, object]] = []
        seen_codes_in_clause: set[str] = set()
        last_end = 0

        def flush_current() -> None:
            nonlocal current_clause, seen_codes_in_clause
            if current_clause:
                clauses.append(current_clause)
                current_clause = []
                seen_codes_in_clause = set()

        for index, match in enumerate(course_matches):
            connector_text = segment[last_end : match.start()].lower()
            last_end = match.end()
            code = normalize_code(match.group(1), match.group(2))

            preceding_window = segment[max(0, match.start() - 40) : match.start()].lower()
            following_window = segment[match.end() : match.end() + 50].lower()
            local_concurrent = bool(
                re.search(r"concurrent\s+enrollment\s+in[^.]{0,30}$", preceding_window)
                or re.search(r"^[\s\*]*\(may\s+be\s+taken\s+concurrently\)", following_window)
            )

            entry = {
                "course_code": code,
                "concurrent_allowed": local_concurrent,
                "recommended_only": recommended_only,
            }

            if index == 0:
                current_clause.append(entry)
                seen_codes_in_clause.add(code)
                continue

            if re.search(r"\bor\b", connector_text):
                if code not in seen_codes_in_clause:
                    current_clause.append(entry)
                    seen_codes_in_clause.add(code)
            else:
                flush_current()
                current_clause.append(entry)
                seen_codes_in_clause.add(code)

        flush_current()

    unique_clauses: list[list[dict[str, object]]] = []
    seen_clause_keys: set[tuple[str, ...]] = set()
    for clause in clauses:
        key = tuple(sorted({entry["course_code"] for entry in clause}))
        if not key or key in seen_clause_keys:
            continue
        seen_clause_keys.add(key)
        unique_clauses.append(clause)

    return unique_clauses, notes


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS course_prerequisites;
        DROP TABLE IF EXISTS course_prerequisite_notes;

        CREATE TABLE course_prerequisites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_code TEXT NOT NULL,
            clause_index INTEGER NOT NULL,
            prereq_course_code TEXT NOT NULL,
            concurrent_allowed INTEGER NOT NULL DEFAULT 0,
            recommended_only INTEGER NOT NULL DEFAULT 0,
            raw_text TEXT,
            source TEXT NOT NULL DEFAULT 'catalog',
            imported_at TEXT NOT NULL
        );

        CREATE INDEX idx_course_prerequisites_course
            ON course_prerequisites(course_code);
        CREATE INDEX idx_course_prerequisites_prereq
            ON course_prerequisites(prereq_course_code);

        CREATE TABLE course_prerequisite_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_code TEXT NOT NULL,
            note_text TEXT NOT NULL,
            imported_at TEXT NOT NULL
        );
        """
    )


def import_file(conn: sqlite3.Connection, html_path: Path, *, dry_run: bool) -> dict[str, int]:
    raw_html = html_path.read_text(encoding="utf-8", errors="ignore")
    blocks = COURSE_BLOCK_PATTERN.findall(raw_html)
    counts = {"courses_seen": 0, "courses_with_prereqs": 0, "rows_inserted": 0, "notes_inserted": 0}

    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for block in blocks:
        title_match = COURSE_TITLE_PATTERN.search(block)
        if not title_match:
            continue
        title_text = html_to_text(title_match.group(1))
        course_code = extract_course_code(title_text)
        if not course_code:
            continue
        counts["courses_seen"] += 1

        prereq_match = PREREQ_BLOCK_PATTERN.search(block)
        if not prereq_match:
            continue

        prereq_text = html_to_text(prereq_match.group(1))
        if not prereq_text:
            continue

        clauses, notes = parse_prereq_clauses(prereq_text)
        if not clauses and not notes:
            continue
        counts["courses_with_prereqs"] += 1

        if dry_run:
            continue

        for clause_index, clause in enumerate(clauses):
            for entry in clause:
                conn.execute(
                    """
                    INSERT INTO course_prerequisites (
                        course_code, clause_index, prereq_course_code,
                        concurrent_allowed, recommended_only, raw_text, source, imported_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        course_code,
                        clause_index,
                        entry["course_code"],
                        1 if entry["concurrent_allowed"] else 0,
                        1 if entry["recommended_only"] else 0,
                        prereq_text,
                        "catalog",
                        timestamp,
                    ),
                )
                counts["rows_inserted"] += 1

        for note in notes:
            conn.execute(
                """
                INSERT INTO course_prerequisite_notes (course_code, note_text, imported_at)
                VALUES (?, ?, ?)
                """,
                (course_code, note, timestamp),
            )
            counts["notes_inserted"] += 1

    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help=f"Directory of catalog HTML files (default: {DEFAULT_INPUT_DIR})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and report but do not write to SQLite",
    )
    args = parser.parse_args()

    input_dir: Path = args.input_dir
    if not input_dir.exists():
        print(f"Input directory not found: {input_dir}", file=sys.stderr)
        return 1

    html_files = sorted(input_dir.glob("*.html"))
    if not html_files:
        print(f"No .html files in {input_dir}", file=sys.stderr)
        return 1

    db_path = get_database_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        if not args.dry_run:
            ensure_schema(conn)

        totals = {"courses_seen": 0, "courses_with_prereqs": 0, "rows_inserted": 0, "notes_inserted": 0}
        for html_path in html_files:
            counts = import_file(conn, html_path, dry_run=args.dry_run)
            print(
                f"{html_path.name}: courses_seen={counts['courses_seen']}, "
                f"with_prereqs={counts['courses_with_prereqs']}, "
                f"rows={counts['rows_inserted']}, notes={counts['notes_inserted']}"
            )
            for key in totals:
                totals[key] += counts[key]

        if not args.dry_run:
            conn.commit()

    print(
        "TOTAL: "
        f"courses_seen={totals['courses_seen']}, "
        f"with_prereqs={totals['courses_with_prereqs']}, "
        f"rows={totals['rows_inserted']}, notes={totals['notes_inserted']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
