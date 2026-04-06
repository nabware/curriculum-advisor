#!/usr/bin/env python3
from __future__ import annotations

import re
import sqlite3
from pathlib import Path


DB_PATH = Path(__file__).resolve().parents[1] / "data" / "seed" / "curriculum_advisor.db"


def parse_units_range(group_name: str) -> tuple[int | None, int | None]:
    match = re.search(r"\(\s*(\d+)\s*-\s*(\d+)\s*units?\)", group_name, flags=re.IGNORECASE)
    if match:
        return int(match.group(1)), int(match.group(2))

    match = re.search(r"\(\s*(\d+)\s*units?\)", group_name, flags=re.IGNORECASE)
    if match:
        units = int(match.group(1))
        return units, units

    return None, None


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS requirement_group_level_ranges;
        DROP TABLE IF EXISTS requirement_group_courses;
        DROP TABLE IF EXISTS requirement_groups;
        DROP TABLE IF EXISTS degree_programs;

        CREATE TABLE degree_programs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            degree_name TEXT NOT NULL UNIQUE,
            total_units_required INTEGER
        );

        CREATE TABLE requirement_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            degree_id INTEGER NOT NULL,
            group_name TEXT NOT NULL,
            min_units INTEGER,
            max_units INTEGER,
            FOREIGN KEY (degree_id) REFERENCES degree_programs(id) ON DELETE CASCADE,
            UNIQUE (degree_id, group_name)
        );

        CREATE TABLE requirement_group_courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            course_code TEXT NOT NULL,
            course_name TEXT,
            units TEXT,
            FOREIGN KEY (group_id) REFERENCES requirement_groups(id) ON DELETE CASCADE,
            UNIQUE (group_id, course_code)
        );
        """
    )


def build_model(conn: sqlite3.Connection) -> None:
    degree_rows = conn.execute(
        """
        SELECT degree, MAX(degree_total_units) AS degree_total_units
        FROM degree_requirements
        GROUP BY degree
        ORDER BY degree
        """
    ).fetchall()

    for degree_name, degree_total_units in degree_rows:
        conn.execute(
            "INSERT INTO degree_programs (degree_name, total_units_required) VALUES (?, ?)",
            (degree_name, degree_total_units),
        )

    group_rows = conn.execute(
        """
        SELECT degree, course_group
        FROM degree_requirements
        GROUP BY degree, course_group
        ORDER BY degree, course_group
        """
    ).fetchall()

    for degree_name, group_name in group_rows:
        degree_id = conn.execute(
            "SELECT id FROM degree_programs WHERE degree_name = ?",
            (degree_name,),
        ).fetchone()[0]

        min_units, max_units = parse_units_range(group_name)

        conn.execute(
            """
            INSERT INTO requirement_groups (
                degree_id,
                group_name,
                min_units,
                max_units
            )
            VALUES (?, ?, ?, ?)
            """,
            (degree_id, group_name, min_units, max_units),
        )

        group_id = conn.execute(
            """
            SELECT id
            FROM requirement_groups
            WHERE degree_id = ? AND group_name = ?
            """,
            (degree_id, group_name),
        ).fetchone()[0]

        course_rows = conn.execute(
            """
            SELECT course_code, course_name, units
            FROM degree_requirements
            WHERE degree = ?
              AND course_group = ?
              AND course_code IS NOT NULL
              AND TRIM(course_code) != ''
            ORDER BY course_code
            """,
            (degree_name, group_name),
        ).fetchall()

        for course_code, course_name, units in course_rows:
            conn.execute(
                """
                INSERT OR IGNORE INTO requirement_group_courses (
                    group_id,
                    course_code,
                    course_name,
                    units
                )
                VALUES (?, ?, ?, ?)
                """,
                (group_id, course_code, course_name, units),
            )


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"Database not found at {DB_PATH}")

    with sqlite3.connect(DB_PATH) as conn:
        init_schema(conn)
        build_model(conn)
        conn.commit()

        degree_count = conn.execute("SELECT COUNT(*) FROM degree_programs").fetchone()[0]
        group_count = conn.execute("SELECT COUNT(*) FROM requirement_groups").fetchone()[0]
        course_count = conn.execute("SELECT COUNT(*) FROM requirement_group_courses").fetchone()[0]

    print(
        "Built requirement model: "
        f"degrees={degree_count}, groups={group_count}, "
        f"group_courses={course_count}"
    )


if __name__ == "__main__":
    main()
