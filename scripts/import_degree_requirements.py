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


def parse_program_name(html_text: str, fallback_name: str) -> str:
    title_match = re.search(r"<title>(.*?)</title>", html_text, flags=re.IGNORECASE | re.DOTALL)
    if not title_match:
        return fallback_name

    title_text = re.sub(r"\s+", " ", title_match.group(1)).strip()
    return title_text.split("|", maxsplit=1)[0].strip() or fallback_name


def html_to_text(html_text: str) -> str:
    # Remove script/style blocks first so they do not pollute extracted text.
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


def get_degree_section_html(html_text: str) -> str:
    """Narrow parsing to the actual degree requirement section of the bulletin page."""
    section_start_match = re.search(r'id="degreerequirementstext"', html_text, flags=re.IGNORECASE)
    section = html_text[section_start_match.start() :] if section_start_match else html_text

    # Prefer the first degree title block (typically includes "units minimum").
    degree_heading_match = re.search(
        r"<h2[^>]*>.*?units\s+minimum.*?</h2>",
        section,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if degree_heading_match:
        section = section[degree_heading_match.start() :]

    # Stop before side rail content when present.
    side_title_match = re.search(r"<h2\s+class=\"side-title\"", section, flags=re.IGNORECASE)
    if side_title_match:
        section = section[: side_title_match.start()]

    return section


def find_course_group(html_text: str, position: int) -> str | None:
    """Find the nearest h3 requirement group before a course occurrence."""
    prefix = html_text[:position]

    h3_matches = list(
        re.finditer(r"<h3[^>]*>(.*?)</h3>", prefix, flags=re.IGNORECASE | re.DOTALL)
    )
    last_h3 = h3_matches[-1] if h3_matches else None

    if last_h3:
        return html_to_text(last_h3.group(1)) or None

    return None


def parse_requirement_groups(html_text: str) -> list[str]:
    """Extract requirement groups from h3 headings only."""
    groups: list[str] = []

    heading_pattern = re.compile(
        r"<h3[^>]*>(.*?)</h3>",
        flags=re.IGNORECASE | re.DOTALL,
    )

    for heading_match in heading_pattern.finditer(html_text):
        heading_text = html_to_text(heading_match.group(1))
        if not heading_text:
            continue

        groups.append(heading_text)

    deduped: list[str] = []
    seen: set[str] = set()
    for item in groups:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)

    return deduped


def parse_degree_total_units(raw_html: str, degree_name: str) -> int | None:
    """Extract total units from the degree header on the bulletin page."""

    def normalize(value: str) -> str:
        lowered = value.lower()
        lowered = re.sub(r"[^a-z0-9\s]", " ", lowered)
        return re.sub(r"\s+", " ", lowered).strip()

    normalized_degree = normalize(degree_name)
    major_phrase = re.sub(r"^(bachelor|master)\s+of\s+science\s+in\s+", "", normalized_degree).strip()

    headings = re.findall(r"<h2[^>]*>(.*?)</h2>", raw_html, flags=re.IGNORECASE | re.DOTALL)
    for heading_html in headings:
        heading_text = html_to_text(html.unescape(heading_html))
        if not heading_text:
            continue

        normalized_heading = normalize(heading_text)
        if "units" not in normalized_heading:
            continue

        # Prefer headings that reference the degree name or major phrase.
        if normalized_degree not in normalized_heading and (
            not major_phrase or major_phrase not in normalized_heading
        ):
            continue

        units_match = re.search(r"\b(\d+)\s+units?\b", normalized_heading, flags=re.IGNORECASE)
        if not units_match:
            continue

        try:
            return int(units_match.group(1))
        except ValueError:
            continue

    return None


def parse_course_rows(
    html_text: str,
) -> list[tuple[str, str, str | None, str | None]]:
    """Extract (course_group, course_code, course_name, units) from bulletin HTML."""
    results: list[tuple[str, str, str | None, str | None]] = []

    anchor_pattern = re.compile(
        r'class="bubblelink code"[^>]*>([^<]+)</a>',
        flags=re.IGNORECASE,
    )

    for match in anchor_pattern.finditer(html_text):
        raw_code = html.unescape(match.group(1)).replace("\xa0", " ")
        course_code = re.sub(r"\s+", " ", raw_code).strip()
        if not course_code:
            continue

        title: str | None = None
        units: str | None = None

        # Most course listings are in table rows and include title + units in nearby cells.
        window = html_text[match.end() : match.end() + 650]
        title_match = re.search(r"</td>\s*<td>(.*?)</td>", window, flags=re.IGNORECASE | re.DOTALL)
        if title_match:
            title = html_to_text(title_match.group(1)) or None
            units_match = re.search(
                r'<td\s+class="hourscol">(.*?)</td>',
                window,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if units_match:
                units = html_to_text(units_match.group(1)) or None
        else:
            # Inline references still often include a short title right after the link.
            inline_title = re.search(r"^\s*([^<]{2,120})<", window)
            if inline_title:
                maybe_title = html_to_text(inline_title.group(1))
                title = maybe_title or None

        course_group = find_course_group(html_text, match.start())
        results.append((course_group or "", course_code, title, units))

    # Deduplicate while preserving order.
    deduped: list[tuple[str, str, str | None, str | None]] = []
    seen: set[tuple[str, str, str | None, str | None]] = set()
    for item in results:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)

    return deduped


def init_schema(conn: sqlite3.Connection) -> None:
    # Rebuild derived tables from source on each import.
    conn.execute("DROP TABLE IF EXISTS degree_requirements;")
    conn.execute(
        """
        CREATE TABLE degree_requirements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            degree TEXT NOT NULL,
            degree_total_units INTEGER,
            course_group TEXT,
            course_code TEXT,
            course_name TEXT,
            units TEXT,
            source_file TEXT NOT NULL,
            imported_at TEXT NOT NULL
        );
        """
    )


def upsert_file(conn: sqlite3.Connection, file_path: Path, source_root: Path) -> None:
    raw_content = file_path.read_text(encoding="utf-8", errors="ignore")
    degree_name = parse_program_name(raw_content, fallback_name=file_path.stem)
    imported_at = datetime.now(timezone.utc).isoformat()

    source_rel_path = str(file_path.relative_to(source_root))

    section_html = get_degree_section_html(raw_content)
    degree_total_units = parse_degree_total_units(raw_content, degree_name)
    course_rows = parse_course_rows(section_html)
    requirement_groups = parse_requirement_groups(section_html)

    def is_valid_requirement_group(group_name: str | None) -> bool:
        if not group_name:
            return False
        normalized = group_name.strip()
        if not normalized:
            return False
        if not re.search(r"\bunits?\b", normalized, flags=re.IGNORECASE):
            return False
        return not (
            normalized == degree_name
            or "(B.S.)" in normalized
            or normalized.startswith("Master of Science in")
        )

    # Keep one row per (group, code) and prefer richer title/units.
    course_index: dict[tuple[str, str], tuple[str | None, str | None]] = {}
    for course_group, course_code, course_name, units in course_rows:
        if not course_group:
            continue
        if not is_valid_requirement_group(course_group):
            # Ignore top-level degree title buckets.
            continue
        if (course_name is None or not str(course_name).strip()) and (
            units is None or not str(units).strip()
        ):
            # Ignore non-specific inline mentions that do not carry class details.
            continue
        key = (course_group, course_code)
        existing = course_index.get(key)
        if existing is None:
            course_index[key] = (course_name, units)
            continue

        existing_name, existing_units = existing
        better_name = existing_name if existing_name else course_name
        better_units = existing_units if existing_units else units
        course_index[key] = (better_name, better_units)

    # Preserve prose-only requirement groups (e.g., "Electives (6 units)")
    # by emitting group-only rows with null course fields.
    existing_group_keys = {group for (group, _code) in course_index}
    for course_group in requirement_groups:
        if not is_valid_requirement_group(course_group):
            continue
        if course_group in existing_group_keys:
            continue
        course_index[(course_group, "")] = (None, None)

    conn.executemany(
        """
        INSERT INTO degree_requirements (
            degree,
            degree_total_units,
            course_group,
            course_code,
            course_name,
            units,
            source_file,
            imported_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                degree_name,
                degree_total_units,
                course_group,
                (course_code or None),
                course_name,
                units,
                source_rel_path,
                imported_at,
            )
            for (course_group, course_code), (course_name, units) in sorted(
                course_index.items(),
                key=lambda item: (
                    item[0][0],
                    item[0][1],
                ),
            )
        ],
    )


def import_degree_requirements(source_dir: Path, db_path: Path, project_root: Path) -> int:
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
    default_source_dir = project_root / "data" / "raw" / "degree_requirements"
    default_db = get_database_path()

    parser = argparse.ArgumentParser(
        description="Import degree requirement HTML files into SQLite."
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=default_source_dir,
        help=f"Directory containing degree requirement HTML files. Default: {default_source_dir}",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=default_db,
        help=f"SQLite database path. Default: {default_db}",
    )
    args = parser.parse_args()

    imported_count = import_degree_requirements(
        source_dir=args.source_dir,
        db_path=args.db_path,
        project_root=project_root,
    )

    print(f"Imported {imported_count} degree requirement files into {args.db_path}")


if __name__ == "__main__":
    main()
