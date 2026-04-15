from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import Any


DB_PATH = "data/seed/curriculum_advisor.db"


@dataclass
class RecommendationRequest:
    degree_name: str
    term: str | None = None
    max_units: float | None = None


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def list_degrees() -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT
                id,
                degree_name,
                total_units_required
            FROM degree_programs
            ORDER BY degree_name
            """
        ).fetchall()

        return [
            {
                "id": row["id"],
                "degree_name": row["degree_name"],
                "total_units_required": row["total_units_required"],
            }
            for row in rows
        ]
    finally:
        conn.close()


def recommend_courses(payload: RecommendationRequest | dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload, dict):
        payload = RecommendationRequest(
            degree_name=payload["degree_name"],
            term=payload.get("term"),
            max_units=payload.get("max_units"),
        )

    conn = get_connection()
    try:
        degree = _get_degree(conn, payload.degree_name)
        if not degree:
            raise ValueError(f"Degree not found: {payload.degree_name}")

        groups = _get_requirement_groups(conn, degree["id"])
        raw_candidates = _build_group_candidates(conn, groups, payload.term)
        selected = _select_courses_by_group(raw_candidates)
        selected = _apply_conflict_filter(selected)
        selected = _apply_unit_cap(selected, payload.max_units)
        result = _build_response(selected, degree)

        return result
    finally:
        conn.close()


def _get_degree(conn: sqlite3.Connection, degree_name: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT id, degree_name, total_units_required
        FROM degree_programs
        WHERE degree_name = ?
        """,
        (degree_name,),
    ).fetchone()


def _get_requirement_groups(conn: sqlite3.Connection, degree_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
            id,
            group_name,
            min_units,
            max_units
        FROM requirement_groups
        WHERE degree_id = ?
        ORDER BY id
        """,
        (degree_id,),
    ).fetchall()


def _build_group_candidates(
    conn: sqlite3.Connection,
    groups: list[sqlite3.Row],
    term: str | None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    for group in groups:
        group_courses = _get_group_course_candidates(conn, group["id"], term)
        if not group_courses:
            continue

        candidates.append(
            {
                "group_id": group["id"],
                "group_name": group["group_name"],
                "courses": group_courses,
            }
        )

    return candidates


def _get_group_course_candidates(
    conn: sqlite3.Connection,
    group_id: int,
    term: str | None,
) -> list[dict[str, Any]]:
    params: list[Any] = [group_id]
    term_sql = ""

    if term:
        term_sql = "AND t.term_code = ?"
        params.append(term)

    rows = conn.execute(
        f"""
        SELECT
            c.id AS course_id,
            c.course_code,
            c.course_title,
            c.description,
            COALESCE(c.min_units, c.max_units, 3) AS units,
            co.id AS offering_id,
            t.term_code,
            co.class_number,
            co.section,
            co.days_times,
            co.room,
            co.meeting_dates,
            co.status,
            p.display_name AS professor_name,
            p.title AS professor_title,
            p.image_src AS professor_image_src,
            p.profile_url AS professor_profile_url
        FROM requirement_group_courses_v2 rgc
        JOIN courses c
            ON c.id = rgc.course_id
        LEFT JOIN course_offerings co
            ON co.course_id = c.id
        LEFT JOIN terms t
            ON t.id = co.term_id
        LEFT JOIN offering_instructors oi
            ON oi.offering_id = co.id
        LEFT JOIN professors p
            ON p.id = oi.professor_id
        WHERE rgc.group_id = ?
          {term_sql}
        ORDER BY
            CASE
                WHEN co.status = 'Open' THEN 0
                WHEN co.status = 'Closed' THEN 2
                ELSE 1
            END,
            c.course_code,
            co.section
        """,
        params,
    ).fetchall()

    result: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any]] = set()

    for row in rows:
        key = (row["course_id"], row["offering_id"])
        if key in seen:
            continue
        seen.add(key)

        result.append(
            {
                "course_id": row["course_id"],
                "course_code": row["course_code"],
                "course_title": row["course_title"],
                "description": row["description"],
                "units": float(row["units"] or 3),
                "offering_id": row["offering_id"],
                "term": row["term_code"],
                "class_number": row["class_number"],
                "section": row["section"],
                "days_times": row["days_times"],
                "room": row["room"],
                "meeting_dates": row["meeting_dates"],
                "status": row["status"],
                "professor": {
                    "name": row["professor_name"],
                    "title": row["professor_title"],
                    "image_src": row["professor_image_src"],
                    "profile_url": row["professor_profile_url"],
                }
                if row["professor_name"]
                else None,
            }
        )

    return result


def _select_courses_by_group(group_candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []

    for group in group_candidates:
        courses = group["courses"]
        if not courses:
            continue

        # Pick the first viable course per group.
        # You can later expand this to satisfy min_units/max_units.
        chosen = courses[0].copy()
        chosen["requirement_group"] = group["group_name"]
        selected.append(chosen)

    return selected


def _apply_conflict_filter(selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    accepted: list[dict[str, Any]] = []

    for candidate in selected:
        if not _has_conflict(candidate, accepted):
            accepted.append(candidate)

    return accepted


def _has_conflict(course: dict[str, Any], accepted: list[dict[str, Any]]) -> bool:
    current_slots = _parse_days_times(course.get("days_times"))

    if not current_slots:
        return False

    for existing in accepted:
        existing_slots = _parse_days_times(existing.get("days_times"))
        if _slots_overlap(current_slots, existing_slots):
            return True

    return False


def _apply_unit_cap(
    selected: list[dict[str, Any]],
    max_units: float | None,
) -> list[dict[str, Any]]:
    if max_units is None:
        return selected

    total = 0.0
    result: list[dict[str, Any]] = []

    for item in selected:
        units = float(item.get("units") or 0)
        if total + units <= max_units:
            result.append(item)
            total += units

    return result


def _build_response(selected: list[dict[str, Any]], degree: sqlite3.Row) -> dict[str, Any]:
    total_units_selected = sum(float(item.get("units") or 0) for item in selected)

    return {
        "degree": {
            "id": degree["id"],
            "degree_name": degree["degree_name"],
            "total_units_required": degree["total_units_required"],
        },
        "recommendations": selected,
        "progress": {
            "total_units_selected": total_units_selected,
            "total_units_required": degree["total_units_required"],
        },
        "schedule_overview": _build_schedule_overview(selected),
    }


def _build_schedule_overview(selected: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    overview: dict[str, list[dict[str, Any]]] = {
        "Mon": [],
        "Tue": [],
        "Wed": [],
        "Thu": [],
        "Fri": [],
        "Sat": [],
        "Sun": [],
    }

    for item in selected:
        slots = _parse_days_times(item.get("days_times"))
        for slot in slots:
            overview[slot["day"]].append(
                {
                    "course_code": item["course_code"],
                    "course_title": item["course_title"],
                    "start": slot["start"],
                    "end": slot["end"],
                    "section": item.get("section"),
                    "room": item.get("room"),
                }
            )

    for day in overview:
        overview[day].sort(key=lambda x: x["start"])

    return overview


DAY_TOKEN_MAP = {
    "M": "Mon",
    "T": "Tue",
    "W": "Wed",
    "R": "Thu",
    "F": "Fri",
    "S": "Sat",
    "U": "Sun",
}


def _parse_days_times(days_times: str | None) -> list[dict[str, str]]:
    """
    Examples handled:
    - MW 10:00AM-11:15AM
    - TR 1:00PM-2:15PM
    - F 08:00AM-10:45AM
    """
    if not days_times:
        return []

    text = days_times.strip()
    match = re.match(
        r"^([MTWRFSU]+)\s+(\d{1,2}:\d{2}[AP]M)-(\d{1,2}:\d{2}[AP]M)$",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return []

    day_tokens = match.group(1).upper()
    start = _to_24h(match.group(2).upper())
    end = _to_24h(match.group(3).upper())

    result: list[dict[str, str]] = []
    for token in day_tokens:
        day = DAY_TOKEN_MAP.get(token)
        if day:
            result.append({"day": day, "start": start, "end": end})

    return result


def _to_24h(value: str) -> str:
    hour_minute = value[:-2]
    suffix = value[-2:]

    hour_str, minute_str = hour_minute.split(":")
    hour = int(hour_str)
    minute = int(minute_str)

    if suffix == "AM":
        if hour == 12:
            hour = 0
    elif suffix == "PM":
        if hour != 12:
            hour += 12

    return f"{hour:02d}:{minute:02d}"


def _slots_overlap(
    slots_a: list[dict[str, str]],
    slots_b: list[dict[str, str]],
) -> bool:
    for a in slots_a:
        for b in slots_b:
            if a["day"] != b["day"]:
                continue
            if a["start"] < b["end"] and b["start"] < a["end"]:
                return True
    return False