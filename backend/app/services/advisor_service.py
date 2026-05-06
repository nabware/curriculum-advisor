from __future__ import annotations

import os
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
from app.services.llama_sentiment_service import parse_course_preferences_with_catalog
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
    def _resolve_numeric_name_match(
        instructor_name: str | None,
        by_full_name: dict[str, float],
        by_last_initial: dict[str, list[float]],
        by_last_name: dict[str, list[float]],
    ) -> float | None:
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
    def _clamp_01(value: float | None) -> float:
        if value is None:
            return 0.0
        return max(0.0, min(1.0, float(value)))

    @staticmethod
    def _clamp_difficulty(value: float | None) -> float:
        if value is None:
            return 0.5
        return max(0.0, min(1.0, float(value) / 5.0))

    @staticmethod
    def _normalize_phrase(value: str | None) -> str:
        if not value:
            return ""
        return re.sub(r"\s+", " ", value).strip().lower()

    @staticmethod
    def _pre_normalize_preferences(text: str | None) -> str | None:
        if not text or not text.strip():
            return text
        abbr_map = {
            r"\bai\b": "artificial intelligence",
            r"\bml\b": "machine learning",
            r"\bos\b": "operating systems",
        }
        normalized = str(text)
        for pat, repl in abbr_map.items():
            normalized = re.sub(pat, repl, normalized, flags=re.IGNORECASE)
        return normalized

    @staticmethod
    def _preference_tokens(value: str | None) -> list[str]:
        normalized = AdvisorService._normalize_phrase(value)
        if not normalized:
            return []

        tokens = [token for token in re.split(r"\s+", re.sub(r"[^a-z0-9\s-]", " ", normalized)) if token]
        return [token[:-1] if token.endswith("s") and len(token) > 3 else token for token in tokens]

    @staticmethod
    def _course_search_text(course: RecommendedCourse) -> str:
        parts = [
            course.course_code,
            course.title,
            course.group_name,
            course.description,
            course.instructor,
            course.professor_name,
        ]
        return AdvisorService._normalize_phrase(" ".join(part for part in parts if part))

    @staticmethod
    def _matches_phrase(text: str, phrase: str) -> bool:
        phrase_tokens = AdvisorService._preference_tokens(phrase)
        if not phrase_tokens:
            return False

        text_tokens = set(AdvisorService._preference_tokens(text))
        if phrase_tokens and set(phrase_tokens).issubset(text_tokens):
            return True

        normalized_phrase = AdvisorService._normalize_phrase(phrase)
        if normalized_phrase in text:
            return True
        return bool(phrase_tokens) and all(token in text_tokens for token in phrase_tokens)

    @staticmethod
    def _matches_instructor(course: RecommendedCourse, phrase: str) -> bool:
        target = AdvisorService._normalize_phrase(" ".join(filter(None, [course.instructor, course.professor_name])))
        return bool(target and AdvisorService._matches_phrase(target, phrase))

    @staticmethod
    def _build_preference_constraints(preferences_text: str | None) -> dict[str, Any]:
        if not preferences_text or not preferences_text.strip():
            return {
                "must_include_topics": [],
                "must_include_course_codes": [],
                "exclude_course_codes": [],
                "exclude_topics": [],
                "exclude_instructors": [],
                "prefer_light_workload": False,
                "prefer_high_rated_professors": False,
                "prefer_easy_teachers": False,
                "min_professor_rating": None,
                "max_professor_difficulty": None,
                "summary": "",
            }

        # Ollama-only preference path: initialize empty constraints and apply only
        # if catalog-aware Ollama parsing succeeds.
        return {
            "must_include_topics": [],
            "must_include_course_codes": [],
            "exclude_course_codes": [],
            "exclude_topics": [],
            "exclude_instructors": [],
            "prefer_light_workload": False,
            "prefer_high_rated_professors": False,
            "prefer_easy_teachers": False,
            "min_professor_rating": None,
            "max_professor_difficulty": None,
            "summary": "",
        }

    @staticmethod
    def _resolve_course_objective(
        course: RecommendedCourse,
        sentiment_score: float | None,
        prefer_light_workload: bool,
        prefer_high_rated_professors: bool,
        prefer_easy_teachers: bool,
        progress_weight_override: float | None = None,
        workload_weight_override: float | None = None,
        sentiment_weight_override: float | None = None,
        difficulty_weight_override: float | None = None,
    ) -> float:
        units = course.units or 0
        normalized_units = max(0.0, min(1.0, units / 4.0))

        progress_score = normalized_units
        workload_score = 1.0 - normalized_units
        sentiment_score_clamped = AdvisorService._clamp_01(sentiment_score)
        difficulty_score = 1.0 - AdvisorService._clamp_difficulty(course.rmp_difficulty)

        progress_weight = max(0.0, progress_weight_override if progress_weight_override is not None else 0.55)
        workload_base = max(0.0, workload_weight_override if workload_weight_override is not None else 0.30)
        sentiment_base = max(0.0, sentiment_weight_override if sentiment_weight_override is not None else 0.35)
        difficulty_base = max(0.0, difficulty_weight_override if difficulty_weight_override is not None else 0.25)

        workload_weight = workload_base if prefer_light_workload else 0.0
        sentiment_weight = sentiment_base if prefer_high_rated_professors else 0.0
        difficulty_weight = difficulty_base if prefer_easy_teachers else 0.0
        total_weight = progress_weight + workload_weight + sentiment_weight + difficulty_weight

        weighted_sum = (
            progress_weight * progress_score
            + workload_weight * workload_score
            + sentiment_weight * sentiment_score_clamped
            + difficulty_weight * difficulty_score
        )
        return weighted_sum / total_weight if total_weight > 0 else 0.0

    @staticmethod
    def _course_matches_preferences(
        course: RecommendedCourse,
        constraints: dict[str, Any],
    ) -> tuple[bool, list[str]]:
        course_text = AdvisorService._course_search_text(course)
        reasons: list[str] = []

        include_topics = [str(item).strip().lower() for item in constraints.get("must_include_topics", []) if str(item).strip()]
        if include_topics:
            matched_topics = [topic for topic in include_topics if AdvisorService._matches_phrase(course_text, topic)]
            if not matched_topics:
                return False, reasons
            reasons.append(f"matches requested topic(s): {', '.join(matched_topics)}")

        exclude_topics = [str(item).strip().lower() for item in constraints.get("exclude_topics", []) if str(item).strip()]
        if any(AdvisorService._matches_phrase(course_text, topic) for topic in exclude_topics):
            return False, reasons

        exclude_instructors = [str(item).strip().lower() for item in constraints.get("exclude_instructors", []) if str(item).strip()]
        if any(AdvisorService._matches_instructor(course, instructor) for instructor in exclude_instructors):
            return False, reasons

        exclude_course_codes = {
            str(item).strip().upper() for item in constraints.get("exclude_course_codes", []) if str(item).strip()
        }
        if course.course_code.upper() in exclude_course_codes:
            return False, reasons

        min_rating = constraints.get("min_professor_rating")
        if min_rating is not None and course.rmp_rating is not None:
            try:
                if float(course.rmp_rating) < float(min_rating):
                    return False, reasons
            except (TypeError, ValueError):
                pass

        max_difficulty = constraints.get("max_professor_difficulty")
        if max_difficulty is not None and course.rmp_difficulty is not None:
            try:
                if float(course.rmp_difficulty) > float(max_difficulty):
                    return False, reasons
            except (TypeError, ValueError):
                pass

        return True, reasons

    @staticmethod
    def _select_group_courses(
        courses: list[RecommendedCourse],
        min_units: int | None,
        max_units: int | None,
        objective_by_code: dict[str, float] | None = None,
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
                    if objective_by_code:
                        new_score = sum(
                            objective_by_code.get(item.course_code, 0.0) for item in new_selection
                        )
                        existing_score = sum(
                            objective_by_code.get(item.course_code, 0.0)
                            for item in existing_selection
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

        candidate_totals = [total for total in totals if total >= target_units]
        if max_units is not None:
            bounded = [total for total in candidate_totals if total <= max_units]
            if bounded:
                candidate_totals = bounded

        if not candidate_totals:
            candidate_totals = totals

        def _selection_rank(total: int) -> tuple[float, float, int]:
            selection = best_by_total[total]
            objective_score = (
                sum(objective_by_code.get(item.course_code, 0.0) for item in selection)
                if objective_by_code
                else 0.0
            )
            overshoot = abs(total - target_units)
            return (objective_score, -float(overshoot), -len(selection))

        if objective_by_code:
            chosen_total = max(candidate_totals, key=_selection_rank)
        else:
            chosen_total = min(candidate_totals, key=lambda total: (abs(total - target_units), total))

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
            sentiment_summary_by_professor: dict[str, str] = {}
            sentiment_by_last_initial: dict[str, list[float]] = {}
            sentiment_by_last_name: dict[str, list[float]] = {}
            try:
                sentiment_rows = conn.execute(
                    """
                    SELECT professor_name,
                           COALESCE(final_sentiment_score, confidence_adjusted_sentiment_score) AS sentiment_score,
                           llm_sentiment_summary
                    FROM professor_sentiment_features
                    """
                ).fetchall()
            except sqlite3.OperationalError:
                try:
                    sentiment_rows = conn.execute(
                        """
                        SELECT professor_name, confidence_adjusted_sentiment_score AS sentiment_score,
                               llm_sentiment_summary
                        FROM professor_sentiment_features
                        """
                    ).fetchall()
                except sqlite3.OperationalError:
                    sentiment_rows = []

            preference_constraints = AdvisorService._build_preference_constraints(payload.preferences_text)
            prefer_light_workload = payload.prefer_light_workload or bool(preference_constraints.get("prefer_light_workload"))
            prefer_high_rated_professors = payload.prefer_high_rated_professors or bool(
                preference_constraints.get("prefer_high_rated_professors")
            )
            prefer_easy_teachers = bool(preference_constraints.get("prefer_easy_teachers"))

            for row in sentiment_rows:
                professor_name = (row["professor_name"] or "").strip()
                if not professor_name:
                    continue
                score_raw = row["sentiment_score"]
                if score_raw is None:
                    continue
                score = float(score_raw)
                normalized = AdvisorService._normalize_name(professor_name)
                sentiment_by_professor[normalized] = score
                # attach any llm-provided summary
                try:
                    if isinstance(row, sqlite3.Row):
                        summary = row["llm_sentiment_summary"]
                    else:
                        summary = row[2] if len(row) > 2 else None
                except Exception:
                    summary = None
                if summary:
                    sentiment_summary_by_professor[normalized] = str(summary).strip()

                last_initial_key = AdvisorService._last_name_first_initial_key(professor_name)
                if last_initial_key:
                    sentiment_by_last_initial.setdefault(last_initial_key, []).append(score)

                last_key = AdvisorService._last_name_key(professor_name)
                if last_key:
                    sentiment_by_last_name.setdefault(last_key, []).append(score)

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
                    )
                """
                query_params.append(payload.term)

                # Fetch schedule info for all courses in this term (ignore status)
                schedule_rows = conn.execute(
                    """
                    SELECT course_code, days_times, instructor
                    FROM class_schedules
                    WHERE term = ?
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

            all_req_rows = conn.execute(
                """
                SELECT
                    rg.id AS group_id,
                    rg.group_name,
                    rgc.course_code,
                    rgc.course_name,
                    rgc.units
                FROM requirement_groups rg
                JOIN requirement_group_courses rgc ON rg.id = rgc.group_id
                WHERE rg.degree_id = ?
                ORDER BY rg.id, rgc.id
                """,
                (degree_id,),
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
                    professor_sentiment_score=AdvisorService._resolve_numeric_name_match(
                        professor_info["professor_name"] if professor_info else (schedule_info.get("instructor") if schedule_info else None),
                        sentiment_by_professor,
                        sentiment_by_last_initial,
                        sentiment_by_last_name,
                    ),
                    professor_review_summary=(
                        sentiment_summary_by_professor.get(AdvisorService._normalize_name(
                            professor_info["professor_name"] if professor_info else (schedule_info.get("instructor") if schedule_info else None)
                        )) if 'sentiment_summary_by_professor' in locals() else None
                    ),
                )
            )

        # Build per-instructor RMP cache so we only look up each name once
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
                        "rmp_top_tag": rmp.get("top_tag"),
                        "rmp_top_tag_count": rmp.get("top_tag_count"),
                        "rmp_top_tag_tone": rmp.get("top_tag_tone"),
                    })
                enriched.append(course)
            group_data["courses"] = enriched

        keyword_used_for_preferences = False
        if payload.preferences_text and payload.preferences_text.strip():
            candidate_courses: list[dict[str, Any]] = []
            seen_codes: set[str] = set()
            for group_data in grouped_rows:
                for course in group_data["courses"]:
                    code = course.course_code.strip().upper()
                    if not code or code in seen_codes:
                        continue
                    seen_codes.add(code)
                    candidate_courses.append(
                        {
                            "course_code": code,
                            "title": course.title,
                            "group_name": course.group_name,
                            "description": course.description,
                            "instructor": course.instructor or course.professor_name,
                            "rmp_rating": course.rmp_rating,
                            "rmp_difficulty": course.rmp_difficulty,
                            "professor_sentiment_score": course.professor_sentiment_score,
                        }
                    )

            # Use keyword-based preference parsing (fast, no external calls)
            llm_constraints = parse_course_preferences_with_catalog(
                payload.preferences_text,
                candidate_courses,
            )

            if llm_constraints:
                keyword_used_for_preferences = True
                preferred_codes_from_llm = [
                    str(code).strip().upper()
                    for code in llm_constraints.get("preferred_course_codes", [])
                    if str(code).strip()
                ]
                exclude_codes_from_llm = [
                    str(code).strip().upper()
                    for code in llm_constraints.get("excluded_course_codes", [])
                    if str(code).strip()
                ]

                # Guardrail: if local topic hints exist, only keep LLM-picked codes that actually match those topics.
                local_topics = [
                    str(topic).strip().lower()
                    for topic in preference_constraints.get("must_include_topics", [])
                    if str(topic).strip()
                ]
                if local_topics:
                    by_code = {str(course.get("course_code") or "").strip().upper(): course for course in candidate_courses}
                    filtered_preferred_codes: list[str] = []
                    for code in preferred_codes_from_llm:
                        course = by_code.get(code)
                        if not course:
                            continue
                        course_text = AdvisorService._normalize_phrase(
                            " ".join(
                                [
                                    str(course.get("course_code") or ""),
                                    str(course.get("title") or ""),
                                    str(course.get("group_name") or ""),
                                    str(course.get("description") or ""),
                                ]
                            )
                        )
                        if any(AdvisorService._matches_phrase(course_text, topic) for topic in local_topics):
                            filtered_preferred_codes.append(code)
                    preferred_codes_from_llm = filtered_preferred_codes

                preference_constraints["must_include_course_codes"] = preferred_codes_from_llm
                preference_constraints["exclude_course_codes"] = llm_constraints.get("excluded_course_codes", [])
                preference_constraints["exclude_course_codes"] = exclude_codes_from_llm
                if llm_constraints.get("excluded_instructors"):
                    merged_instructors = set(preference_constraints.get("exclude_instructors", []))
                    merged_instructors.update(llm_constraints.get("excluded_instructors", []))
                    preference_constraints["exclude_instructors"] = sorted(merged_instructors)
                if llm_constraints.get("must_include_topics"):
                    merged_topics = set(preference_constraints.get("must_include_topics", []))
                    merged_topics.update(llm_constraints.get("must_include_topics", []))
                    # Expand canonical topics into related synonyms so terse user tokens like
                    # 'ai' will match courses titled 'Generative AI', 'Machine Learning', etc.
                    synonyms_map = {
                        "artificial intelligence": [
                            "generative ai",
                            "machine learning",
                            "deep learning",
                            "pattern analysis",
                            "pattern analysis and machine intelligence",
                        ],
                        "machine learning": ["deep learning", "pattern analysis"],
                    }
                    expanded = set(merged_topics)
                    for t in list(merged_topics):
                        t_l = str(t).strip().lower()
                        for syn in synonyms_map.get(t_l, []):
                            expanded.add(syn)
                    preference_constraints["must_include_topics"] = sorted(expanded)
                normalized_preferences_text = AdvisorService._normalize_phrase(payload.preferences_text)
                explicit_light_workload = any(
                    token in normalized_preferences_text
                    for token in ["light workload", "easy workload", "less work", "easier classes"]
                )
                explicit_high_rating = any(
                    token in normalized_preferences_text
                    for token in ["high rated", "high-rated", "best professor", "good professor", "top professor"]
                )
                explicit_easy_teachers = any(
                    token in normalized_preferences_text
                    for token in ["difficult teacher", "hard teacher", "tough teacher", "easy teacher", "easy professor"]
                )

                if llm_constraints.get("prefer_light_workload") and explicit_light_workload:
                    preference_constraints["prefer_light_workload"] = True
                if llm_constraints.get("prefer_high_rated_professors") and explicit_high_rating:
                    preference_constraints["prefer_high_rated_professors"] = True
                if llm_constraints.get("prefer_easy_teachers") and explicit_easy_teachers:
                    preference_constraints["prefer_easy_teachers"] = True
                for key in ["min_professor_rating", "max_professor_difficulty"]:
                    if llm_constraints.get(key) is not None:
                        preference_constraints[key] = llm_constraints.get(key)
                if llm_constraints.get("summary"):
                    preference_constraints["summary"] = llm_constraints.get("summary")

                prefer_light_workload = prefer_light_workload or bool(preference_constraints.get("prefer_light_workload"))
                prefer_high_rated_professors = prefer_high_rated_professors or bool(
                    preference_constraints.get("prefer_high_rated_professors")
                )
                prefer_easy_teachers = prefer_easy_teachers or bool(preference_constraints.get("prefer_easy_teachers"))

        grouped_recommendations: list[RequirementGroupRecommendation] = []
        preference_notes: list[str] = []
        unmet_preference_notes: list[str] = []
        matched_include_topics: set[str] = set()
        matched_preferred_codes: set[str] = set()
        for group_data in grouped_rows:
            eligible_courses: list[RecommendedCourse] = []
            include_topics = [
                str(item).strip().lower()
                for item in preference_constraints.get("must_include_topics", [])
                if str(item).strip()
            ]
            preferred_codes = {
                str(item).strip().upper()
                for item in preference_constraints.get("must_include_course_codes", [])
                if str(item).strip()
            }

            filtered_constraints = dict(preference_constraints)
            filtered_constraints["must_include_topics"] = []

            for course in group_data["courses"]:
                matches, _ = AdvisorService._course_matches_preferences(course, filtered_constraints)
                if matches:
                    eligible_courses.append(course)

            if preferred_codes:
                preferred_matches = [course for course in eligible_courses if course.course_code.upper() in preferred_codes]
                if preferred_matches:
                    eligible_courses = preferred_matches
                    matched_preferred_codes.update(course.course_code.upper() for course in preferred_matches)

            if include_topics:
                topic_matches: list[RecommendedCourse] = []
                matched_topics_for_group: list[str] = []
                for course in eligible_courses:
                    course_text = AdvisorService._course_search_text(course)
                    matching_topics = [topic for topic in include_topics if AdvisorService._matches_phrase(course_text, topic)]
                    if matching_topics:
                        topic_matches.append(course)
                        matched_topics_for_group.extend(matching_topics)

                if topic_matches:
                    eligible_courses = topic_matches
                    matched_include_topics.update(matched_topics_for_group)

            if not eligible_courses:
                eligible_courses = list(group_data["courses"])
                if include_topics:
                    unmet_preference_notes.append(
                        f"No remaining courses matched the requested topic(s) in {group_data['group_name']}."
                    )

            objective_by_code: dict[str, float] = {}
            for course in eligible_courses:
                sentiment_score = AdvisorService._resolve_numeric_name_match(
                    course.professor_name or course.instructor,
                    sentiment_by_professor,
                    sentiment_by_last_initial,
                    sentiment_by_last_name,
                )
                objective_by_code[course.course_code] = AdvisorService._resolve_course_objective(
                    course,
                    sentiment_score,
                    prefer_light_workload,
                    prefer_high_rated_professors,
                    prefer_easy_teachers,
                    payload.objective_progress_weight,
                    payload.objective_workload_weight,
                    payload.objective_sentiment_weight,
                )

            if prefer_light_workload:
                preference_notes.append("preferred lighter workload courses")
            if prefer_high_rated_professors:
                preference_notes.append("preferred higher-rated professors")
            if prefer_easy_teachers:
                preference_notes.append("favored lower-difficulty professors")

            grouped_recommendations.append(
                RequirementGroupRecommendation(
                    group_name=group_data["group_name"],
                    min_units=group_data["min_units"],
                    max_units=group_data["max_units"],
                    courses=AdvisorService._select_group_courses(
                        eligible_courses,
                        group_data["min_units"],
                        group_data["max_units"],
                        objective_by_code=objective_by_code,
                    ),
                )
            )

        if preference_constraints.get("must_include_topics"):
            for topic in preference_constraints.get("must_include_topics", []):
                if topic in matched_include_topics:
                    continue

                topic_matches_catalog = any(
                    AdvisorService._matches_phrase((row["course_name"] or "") + " " + (description_lookup.get((row["course_code"] or "").strip().upper(), "")), topic)
                    for row in all_req_rows
                )
                if topic_matches_catalog:
                    unmet_preference_notes.append(
                        f"{topic.title()} is part of this degree, but it is not open in {payload.term}."
                    )
                else:
                    unmet_preference_notes.append(f"Could not find an available course matching '{topic}'.")

        if preference_constraints.get("must_include_course_codes"):
            for code in [str(item).strip().upper() for item in preference_constraints.get("must_include_course_codes", []) if str(item).strip()]:
                if code not in matched_preferred_codes:
                    unmet_preference_notes.append(f"Requested course {code} could not be included with current constraints.")

        recommendations = [course for group in grouped_recommendations for course in group.courses]

        if preference_constraints.get("must_include_topics") or preference_constraints.get("must_include_course_codes"):
            include_topics = [
                str(item).strip().lower()
                for item in preference_constraints.get("must_include_topics", [])
                if str(item).strip()
            ]
            include_codes = {
                str(item).strip().upper()
                for item in preference_constraints.get("must_include_course_codes", [])
                if str(item).strip()
            }
            prioritized_recommendations = [
                course
                for course in recommendations
                if course.course_code.upper() in include_codes or any(
                    AdvisorService._matches_phrase(AdvisorService._course_search_text(course), topic)
                    for topic in include_topics
                )
            ]
            prioritized_recommendations.extend(
                course
                for course in recommendations
                if course not in prioritized_recommendations
            )
            recommendations = prioritized_recommendations

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

        if preference_constraints.get("summary"):
            explanation += f" Preference note interpreted as: {preference_constraints['summary']}"

        if keyword_used_for_preferences:
            explanation += " Preference interpretation used keyword matching against available course catalog."

        if preference_notes:
            explanation += " " + " ".join(dict.fromkeys(preference_notes))

        if unmet_preference_notes:
            explanation += " " + " ".join(dict.fromkeys(unmet_preference_notes))

        if skipped_conflicts:
            explanation += " Some overlapping sections were removed to avoid time conflicts."

        if payload.blocked_time_windows:
            explanation += " Courses conflicting with your blocked time windows were excluded."

        if payload.transcript_text:
            transcript_count = len(AdvisorService._parse_transcript_courses(payload.transcript_text))
            if transcript_count:
                explanation += f" {transcript_count} course(s) were read from your transcript and marked as completed."

        if prefer_high_rated_professors and sentiment_by_professor:
            explanation += " Professor sentiment features were included in ranking."

        if prefer_high_rated_professors or prefer_light_workload or prefer_easy_teachers:
            explanation += " Group selections used a weighted objective over progress, workload, sentiment, and difficulty."

        if prefer_easy_teachers:
            explanation += " Lower-difficulty professors were also considered in ranking."

        if semester_capacity is not None:
            explanation += f" Limited to {semester_capacity} units for this semester."

        return AdvisorResponse(
            grouped_recommendations=grouped_recommendations,
            recommendations=recommendations,
            total_units_selected=total_units_selected,
            total_units_required=total_units_required,
            explanation=explanation,
        )
