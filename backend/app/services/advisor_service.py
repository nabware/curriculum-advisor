from __future__ import annotations

from pathlib import Path
import re
import sqlite3
from typing import Any
from urllib.parse import quote

from app.core.database import get_database_path
from app.models.schemas import (
    AdvisorRequest,
    AdvisorResponse,
    BlockedTimeWindow,
    DegreeProgram,
    DegreeProgramsResponse,
    RequirementGroupRecommendation,
    RecommendedCourse,
)
from app.services.rmp_service import fetch_professor_rating


class AdvisorService:
    @staticmethod
    def _connect() -> sqlite3.Connection:
        conn = sqlite3.connect(get_database_path())
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def list_degrees() -> DegreeProgramsResponse:
        with AdvisorService._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, degree_name
                FROM degree_programs
                ORDER BY degree_name
                """
            ).fetchall()

        return DegreeProgramsResponse(
            degrees=[DegreeProgram(id=row["id"], degree_name=row["degree_name"]) for row in rows]
        )

    @staticmethod
    def _resolve_degree_id(conn: sqlite3.Connection, major: str) -> tuple[int, str] | tuple[None, None]:
        normalized_major = major.strip().lower()

        exact = conn.execute(
            """
            SELECT id, degree_name
            FROM degree_programs
            WHERE lower(degree_name) = ?
            LIMIT 1
            """,
            (normalized_major,),
        ).fetchone()
        if exact:
            return exact["id"], exact["degree_name"]

        alias_map = {
            "cs": "computer science",
            "bs cs": "bachelor of science in computer science",
            "ms cs": "master of science in computer science",
            "ms dsai": "master of science in data science and artificial intelligence",
            "dsai": "data science and artificial intelligence",
        }
        lookup_phrase = alias_map.get(normalized_major, normalized_major)

        fuzzy = conn.execute(
            """
            SELECT id, degree_name
            FROM degree_programs
            WHERE lower(degree_name) LIKE ?
            ORDER BY length(degree_name) ASC
            LIMIT 1
            """,
            (f"%{lookup_phrase}%",),
        ).fetchone()

        if not fuzzy:
            return None, None
        return fuzzy["id"], fuzzy["degree_name"]

    @staticmethod
    def _safe_units(value: str | None) -> int | None:
        if not value:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _time_to_minutes(value: str | None) -> int | None:
        if not value:
            return None

        cleaned = value.strip().upper().replace(" ", "")
        match = re.match(r"^(\d{1,2})(?::(\d{2}))?(AM|PM)$", cleaned)
        if not match:
            return None

        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        period = match.group(3)

        if hour == 12:
            hour = 0
        if period == "PM":
            hour += 12

        return hour * 60 + minute

    @staticmethod
    def _parse_days_times(days_times: str | None) -> list[tuple[str, int, int]]:
        if not days_times:
            return []

        match = re.match(r"^(?P<days>[A-Za-z]+)\s+(?P<start>[\d:APMapm]+)\s*-\s*(?P<end>[\d:APMapm]+)$", days_times.strip())
        if not match:
            return []

        start_minutes = AdvisorService._time_to_minutes(match.group("start"))
        end_minutes = AdvisorService._time_to_minutes(match.group("end"))
        if start_minutes is None or end_minutes is None or end_minutes <= start_minutes:
            return []

        day_tokens = re.findall(r"Th|Tu|We|Fr|Sa|Su|Mo|M|T|W|R|F|S|U", match.group("days"), flags=re.IGNORECASE)
        day_map = {
            "Mo": "Monday",
            "Tu": "Tuesday",
            "We": "Wednesday",
            "Th": "Thursday",
            "Fr": "Friday",
            "Sa": "Saturday",
            "Su": "Sunday",
            "M": "Monday",
            "T": "Tuesday",
            "W": "Wednesday",
            "R": "Thursday",
            "F": "Friday",
            "S": "Saturday",
            "U": "Sunday",
        }

        parsed_days: list[tuple[str, int, int]] = []
        for token in day_tokens:
            day_name = day_map.get(token.capitalize())
            if day_name:
                parsed_days.append((day_name, start_minutes, end_minutes))

        return parsed_days

    @staticmethod
    def _has_time_conflict(first: str | None, second: str | None) -> bool:
        first_slots = AdvisorService._parse_days_times(first)
        second_slots = AdvisorService._parse_days_times(second)

        for first_day, first_start, first_end in first_slots:
            for second_day, second_start, second_end in second_slots:
                if first_day != second_day:
                    continue
                if max(first_start, second_start) < min(first_end, second_end):
                    return True

        return False

    @staticmethod
    def _parse_transcript_courses(transcript_text: str | None) -> set[str]:
        """Extract course codes from pasted transcript text, e.g. 'CSC 101', 'MATH 226'."""
        if not transcript_text:
            return set()
        matches = re.findall(r"\b([A-Z]{2,6})\s*(\d{3,4}[A-Z]?)\b", transcript_text.upper())
        return {f"{dept} {num}" for dept, num in matches}

    @staticmethod
    def _conflicts_with_blocked_windows(
        days_times: str | None,
        blocked_windows: list[BlockedTimeWindow],
    ) -> bool:
        """Return True if any parsed slot from days_times overlaps a blocked window."""
        if not days_times or not blocked_windows:
            return False
        course_slots = AdvisorService._parse_days_times(days_times)
        for slot_day, slot_start, slot_end in course_slots:
            for window in blocked_windows:
                if window.day.strip().capitalize() != slot_day:
                    continue
                win_start = AdvisorService._time_to_minutes(window.start)
                win_end = AdvisorService._time_to_minutes(window.end)
                if win_start is None or win_end is None:
                    continue
                if max(slot_start, win_start) < min(slot_end, win_end):
                    return True
        return False

    @staticmethod
    def _filter_time_conflicts(courses: list[RecommendedCourse]) -> tuple[list[RecommendedCourse], list[RecommendedCourse]]:
        selected: list[RecommendedCourse] = []
        skipped: list[RecommendedCourse] = []

        for course in courses:
            if not course.days_times:
                selected.append(course)
                continue

            if any(
                existing.days_times and AdvisorService._has_time_conflict(course.days_times, existing.days_times)
                for existing in selected
            ):
                skipped.append(course)
                continue

            selected.append(course)

        return selected, skipped

    @staticmethod
    def _normalize_name(value: str | None) -> str:
        return re.sub(r"\s+", " ", (value or "")).strip().lower()

    @staticmethod
    def _name_tokens(value: str | None) -> list[str]:
        normalized = AdvisorService._normalize_name(value)
        if not normalized:
            return []
        cleaned = re.sub(r"[^a-z\s-]", " ", normalized)
        return [token for token in re.split(r"[\s-]+", cleaned) if token]

    @staticmethod
    def _last_name_key(value: str | None) -> str | None:
        tokens = AdvisorService._name_tokens(value)
        if not tokens:
            return None
        return tokens[-1]

    @staticmethod
    def _last_name_first_initial_key(value: str | None) -> str | None:
        tokens = AdvisorService._name_tokens(value)
        if len(tokens) < 2:
            return None
        return f"{tokens[-1]}|{tokens[0][0]}"

    @staticmethod
    def _resolve_professor_info(
        instructor_name: str | None,
        by_full_name: dict[str, dict[str, str | None]],
        by_last_initial: dict[str, list[dict[str, str | None]]],
        by_last_name: dict[str, list[dict[str, str | None]]],
    ) -> dict[str, str | None] | None:
        full_key = AdvisorService._normalize_name(instructor_name)
        if full_key and full_key in by_full_name:
            return by_full_name[full_key]

        last_initial_key = AdvisorService._last_name_first_initial_key(instructor_name)
        if last_initial_key:
            matches = by_last_initial.get(last_initial_key, [])
            if len(matches) == 1:
                return matches[0]

        last_key = AdvisorService._last_name_key(instructor_name)
        if last_key:
            matches = by_last_name.get(last_key, [])
            if len(matches) == 1:
                return matches[0]

        return None

    @staticmethod
    def _to_public_professor_image_url(image_src: str | None) -> str | None:
        if not image_src:
            return None

        cleaned = image_src.strip().replace("\\", "/")
        if not cleaned:
            return None

        if cleaned.startswith("./"):
            cleaned = cleaned[2:]

        if cleaned.startswith("/") or cleaned.lower().startswith("http://") or cleaned.lower().startswith("https://"):
            return cleaned

        image_root = (Path(__file__).resolve().parents[3] / "data" / "raw" / "professor_images").resolve()
        target = (image_root / cleaned).resolve()

        try:
            target.relative_to(image_root)
        except ValueError:
            return None

        if not target.exists():
            return None

        return f"/assets/professor-images/{quote(cleaned, safe='/')}"

    @staticmethod
    def _select_group_courses(
        courses: list[RecommendedCourse],
        min_units: int | None,
        max_units: int | None,
        score_by_code: dict[str, float] | None = None,
    ) -> list[RecommendedCourse]:
        if not courses:
            return []

        if min_units is None:
            target_units = max_units if max_units is not None else 0
        elif min_units == 0:
            target_units = max_units if max_units is not None else min_units
        else:
            target_units = min_units

        ordered_courses = sorted(courses, key=lambda item: item.course_code)
        best_by_total: dict[int, list[RecommendedCourse]] = {0: []}

        for course in ordered_courses:
            course_units = course.units or 0
            current_states = list(best_by_total.items())
            for total_units, selected_courses in current_states:
                new_total_units = total_units + course_units
                new_selection = selected_courses + [course]
                existing_selection = best_by_total.get(new_total_units)

                if existing_selection is None:
                    best_by_total[new_total_units] = new_selection
                    continue

                if len(new_selection) < len(existing_selection):
                    best_by_total[new_total_units] = new_selection
                    continue

                if len(new_selection) == len(existing_selection):
                    if score_by_code:
                        new_score = sum(score_by_code.get(item.course_code, 0.0) for item in new_selection)
                        existing_score = sum(
                            score_by_code.get(item.course_code, 0.0) for item in existing_selection
                        )
                        if new_score > existing_score:
                            best_by_total[new_total_units] = new_selection
                            continue

                    new_codes = tuple(item.course_code for item in new_selection)
                    existing_codes = tuple(item.course_code for item in existing_selection)
                    if new_codes < existing_codes:
                        best_by_total[new_total_units] = new_selection

        totals = sorted(best_by_total)
        if not totals:
            return []

        if target_units <= 0:
            positive_totals = [total for total in totals if total > 0]
            if positive_totals:
                target_units = min(positive_totals)
            else:
                return []

        satisfying_totals = [total for total in totals if total >= target_units]
        if satisfying_totals:
            chosen_total = min(satisfying_totals)
        else:
            chosen_total = max(totals)

        return best_by_total[chosen_total]

    @staticmethod
    def recommend(payload: AdvisorRequest) -> AdvisorResponse:
        completed = {c.strip().upper() for c in payload.completed_courses if c.strip()}
        completed |= AdvisorService._parse_transcript_courses(payload.transcript_text)
        semester_capacity = (
            payload.max_units_per_semester
            if payload.max_units_per_semester is not None and payload.max_units_per_semester > 0
            else None
        )

        with AdvisorService._connect() as conn:
            degree_id, degree_name = AdvisorService._resolve_degree_id(conn, payload.major)
            if degree_id is None:
                return AdvisorResponse(
                    grouped_recommendations=[],
                    recommendations=[],
                    total_units_selected=0,
                    total_units_required=0,
                    explanation=(
                        "Could not match the selected degree. Choose a degree from the list "
                        "and try again."
                    ),
                )

            degree_units_row = conn.execute(
                """
                SELECT total_units_required
                FROM degree_programs
                WHERE id = ?
                """,
                (degree_id,),
            ).fetchone()
            degree_total_units_required = None
            if degree_units_row is not None:
                raw_total_units = degree_units_row["total_units_required"]
                if isinstance(raw_total_units, int) and raw_total_units > 0:
                    degree_total_units_required = raw_total_units

            group_rows = conn.execute(
                """
                SELECT
                    rg.id AS group_id,
                    rg.group_name,
                    rg.min_units,
                    rg.max_units
                FROM requirement_groups rg
                WHERE rg.degree_id = ?
                ORDER BY
                    CASE
                        WHEN lower(rg.group_name) LIKE '%core%' THEN 0
                        WHEN lower(rg.group_name) LIKE '%general%' THEN 1
                        ELSE 2
                    END,
                    rg.id
                """,
                (degree_id,),
            ).fetchall()

            description_rows = conn.execute(
                """
                SELECT course_code, description
                FROM course_descriptions
                """
            ).fetchall()

            professor_rows = conn.execute(
                """
                SELECT professor_name, image_src
                FROM professor_profiles
                """
            ).fetchall()

            sentiment_by_professor: dict[str, float] = {}
            try:
                sentiment_rows = conn.execute(
                    """
                    SELECT professor_name, confidence_adjusted_sentiment_score
                    FROM professor_sentiment_features
                    """
                ).fetchall()
            except sqlite3.OperationalError:
                sentiment_rows = []

            for row in sentiment_rows:
                professor_name = (row["professor_name"] or "").strip()
                if not professor_name:
                    continue
                score_raw = row["confidence_adjusted_sentiment_score"]
                if score_raw is None:
                    continue
                sentiment_by_professor[AdvisorService._normalize_name(professor_name)] = float(score_raw)

            # Build term filter and schedule lookup if provided
            term_filter = ""
            query_params: list[Any] = [degree_id]
            schedule_lookup: dict[str, dict[str, str]] = {}  # course_code -> schedule metadata
            description_lookup = {
                (row["course_code"] or "").strip().upper(): (row["description"] or "").strip()
                for row in description_rows
                if (row["course_code"] or "").strip()
            }
            professor_by_full_name: dict[str, dict[str, str | None]] = {}
            professor_by_last_initial: dict[str, list[dict[str, str | None]]] = {}
            professor_by_last_name: dict[str, list[dict[str, str | None]]] = {}
            for row in professor_rows:
                professor_name = (row["professor_name"] or "").strip()
                if not professor_name:
                    continue

                profile_info = {
                    "professor_name": professor_name,
                    "professor_image_url": AdvisorService._to_public_professor_image_url(
                        (row["image_src"] or "").strip() or None
                    ),
                }

                full_key = AdvisorService._normalize_name(professor_name)
                if full_key and full_key not in professor_by_full_name:
                    professor_by_full_name[full_key] = profile_info

                last_initial_key = AdvisorService._last_name_first_initial_key(professor_name)
                if last_initial_key:
                    professor_by_last_initial.setdefault(last_initial_key, []).append(profile_info)

                last_key = AdvisorService._last_name_key(professor_name)
                if last_key:
                    professor_by_last_name.setdefault(last_key, []).append(profile_info)
            
            if payload.term:
                term_filter = """
                    AND EXISTS (
                        SELECT 1 FROM class_schedules cs
                        WHERE cs.course_code = rgc.course_code
                        AND cs.term = ?
                        AND cs.status = 'Open'
                    )
                """
                query_params.append(payload.term)
                
                # Fetch schedule info for all courses in this term
                schedule_rows = conn.execute(
                    """
                    SELECT course_code, days_times, instructor
                    FROM class_schedules
                    WHERE term = ? AND status = 'Open'
                    ORDER BY course_code, class_number, section, id
                    """,
                    (payload.term,),
                ).fetchall()
                for row in schedule_rows:
                    course_code = (row["course_code"] or "").strip().upper()
                    if not course_code or course_code in schedule_lookup:
                        continue
                    schedule_lookup[course_code] = {
                        "days_times": (row["days_times"] or "").strip(),
                        "instructor": (row["instructor"] or "").strip(),
                    }

            req_rows = conn.execute(
                f"""
                SELECT
                    rg.id AS group_id,
                    rgc.course_code,
                    rgc.course_name,
                    rgc.units
                FROM requirement_groups rg
                JOIN requirement_group_courses rgc ON rg.id = rgc.group_id
                WHERE rg.degree_id = ?
                {term_filter}
                ORDER BY rg.id, rgc.id
                """,
                query_params,
            ).fetchall()

        grouped_rows: list[dict[str, Any]] = [
            {
                "group_id": int(row["group_id"]),
                "group_name": (row["group_name"] or "Requirement Group").strip(),
                "min_units": row["min_units"],
                "max_units": row["max_units"],
                "courses": [],
            }
            for row in group_rows
        ]
        grouped_by_id = {group["group_id"]: group for group in grouped_rows}

        for row in req_rows:
            group_id = int(row["group_id"])
            group_entry = grouped_by_id.get(group_id)
            if not group_entry:
                continue

            course_code = (row["course_code"] or "").strip().upper()
            if not course_code or course_code in completed:
                continue

            courses = group_entry["courses"]
            assert isinstance(courses, list)
            if any(existing.course_code == course_code for existing in courses):
                continue

            group_name = str(group_entry["group_name"])
            schedule_info = schedule_lookup.get(course_code) if payload.term else None
            professor_info = None
            if schedule_info and schedule_info.get("instructor"):
                professor_info = AdvisorService._resolve_professor_info(
                    schedule_info.get("instructor"),
                    professor_by_full_name,
                    professor_by_last_initial,
                    professor_by_last_name,
                )
            courses.append(
                RecommendedCourse(
                    course_code=course_code,
                    title=(row["course_name"] or "TBD").strip(),
                    group_name=group_name,
                    units=AdvisorService._safe_units(row["units"]),
                    days_times=schedule_info["days_times"] if schedule_info else None,
                    instructor=schedule_info["instructor"] if schedule_info else None,
                    description=description_lookup.get(course_code),
                    professor_name=professor_info["professor_name"] if professor_info else (schedule_info.get("instructor") if schedule_info else None),
                    professor_image_url=professor_info["professor_image_url"] if professor_info else None,
                )
            )

        # Build per-instructor RMP cache so we only call the API once per name
        rmp_cache: dict[str, dict | None] = {}

        def _get_rmp(instructor: str | None) -> dict | None:
            if not instructor:
                return None
            if instructor not in rmp_cache:
                try:
                    rmp_cache[instructor] = fetch_professor_rating(instructor)
                except Exception:
                    rmp_cache[instructor] = None
            return rmp_cache[instructor]

        # Attach RMP data to every candidate course before group selection
        for group_data in grouped_rows:
            enriched: list[RecommendedCourse] = []
            for course in group_data["courses"]:
                rmp = _get_rmp(course.instructor or course.professor_name)
                if rmp:
                    course = course.model_copy(update={
                        "rmp_rating": rmp.get("rating"),
                        "rmp_difficulty": rmp.get("difficulty"),
                        "rmp_would_take_again_pct": rmp.get("would_take_again_pct"),
                        "rmp_url": rmp.get("rmp_url"),
                        "rmp_num_ratings": rmp.get("num_ratings"),
                    })
                enriched.append(course)
            group_data["courses"] = enriched

        grouped_recommendations: list[RequirementGroupRecommendation] = []
        for group_data in grouped_rows:
            score_by_code: dict[str, float] | None = None
            if payload.prefer_high_rated_professors:
                score_by_code = {}
                for course in group_data["courses"]:
                    sentiment_name = AdvisorService._normalize_name(
                        course.professor_name or course.instructor
                    )
                    score_by_code[course.course_code] = sentiment_by_professor.get(sentiment_name, 0.0)

            grouped_recommendations.append(
                RequirementGroupRecommendation(
                    group_name=group_data["group_name"],
                    min_units=group_data["min_units"],
                    max_units=group_data["max_units"],
                    courses=AdvisorService._select_group_courses(
                        group_data["courses"],
                        group_data["min_units"],
                        group_data["max_units"],
                        score_by_code=score_by_code,
                    ),
                )
            )

        recommendations = [course for group in grouped_recommendations for course in group.courses]

        # Remove courses that fall inside a blocked time window
        if payload.blocked_time_windows:
            blocked_filtered: list[RecommendedCourse] = []
            blocked_removed: list[RecommendedCourse] = []
            for course in recommendations:
                if AdvisorService._conflicts_with_blocked_windows(
                    course.days_times, payload.blocked_time_windows
                ):
                    blocked_removed.append(course)
                else:
                    blocked_filtered.append(course)

            if blocked_removed:
                blocked_codes = {c.course_code for c in blocked_removed}
                grouped_recommendations = [
                    RequirementGroupRecommendation(
                        group_name=g.group_name,
                        min_units=g.min_units,
                        max_units=g.max_units,
                        courses=[c for c in g.courses if c.course_code not in blocked_codes],
                    )
                    for g in grouped_recommendations
                ]
            recommendations = blocked_filtered

        recommendations, skipped_conflicts = AdvisorService._filter_time_conflicts(recommendations)
        if skipped_conflicts:
            selected_codes = {course.course_code for course in recommendations}
            grouped_recommendations = [
                RequirementGroupRecommendation(
                    group_name=group.group_name,
                    min_units=group.min_units,
                    max_units=group.max_units,
                    courses=[course for course in group.courses if course.course_code in selected_codes],
                )
                for group in grouped_recommendations
            ]

        if semester_capacity is not None and semester_capacity > 0:
            trimmed_recommendations: list[RecommendedCourse] = []
            current_units = 0

            for course in recommendations:
                course_units = course.units or 0
                if current_units + course_units <= semester_capacity:
                    trimmed_recommendations.append(course)
                    current_units += course_units

            recommendations = trimmed_recommendations
            grouped_recommendations = [
                RequirementGroupRecommendation(
                    group_name=group.group_name,
                    min_units=group.min_units,
                    max_units=group.max_units,
                    courses=[course for course in group.courses if course in recommendations],
                )
                for group in grouped_recommendations
            ]

        total_units_selected = sum(course.units or 0 for course in recommendations)
        total_units_required = degree_total_units_required or sum(
            (group.min_units or 0) if (group.min_units and group.min_units > 0) else (group.max_units or 0)
            for group in grouped_recommendations
        )

        explanation = (
            f"Baseline recommendations for a new {degree_name} student. "
            "Results are organized by requirement group so the plan reads like a degree map; "
            "transcript and scheduling constraints can be layered in later."
        )

        if skipped_conflicts:
            explanation += " Some overlapping sections were removed to avoid time conflicts."

        if payload.blocked_time_windows:
            explanation += " Courses conflicting with your blocked time windows were excluded."

        if payload.transcript_text:
            transcript_count = len(AdvisorService._parse_transcript_courses(payload.transcript_text))
            if transcript_count:
                explanation += f" {transcript_count} course(s) were read from your transcript and marked as completed."

        if payload.prefer_high_rated_professors and sentiment_by_professor:
            explanation += " Professor sentiment features were used to break ties among eligible courses."

        if semester_capacity is not None:
            explanation += f" Limited to {semester_capacity} units for this semester."

        return AdvisorResponse(
            grouped_recommendations=grouped_recommendations,
            recommendations=recommendations,
            total_units_selected=total_units_selected,
            total_units_required=total_units_required,
            explanation=explanation,
        )
