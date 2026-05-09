"""Deterministic prerequisite validation backed by a course-dependency DAG.

Reads `course_prerequisites` (DNF representation: AND across `clause_index`,
OR within a clause). A course is takeable if every clause has at least one
satisfied alternative.

A prereq is satisfied when the alternative course is in `completed`, or in
`currently_enrolled` when the alternative carries the `concurrent_allowed` flag.
Clauses where every alternative is marked `recommended_only` are treated as
informational and never block the course.

Cycle safety: validation does not traverse beyond direct prereqs, so cycles in
the catalog (rare, but possible) cannot cause infinite recursion. The companion
`build_prerequisite_graph()` helper exposes the full edge set for callers that
want to do their own topological work (e.g. evaluation scripts).
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Iterable

from app.core.database import get_database_path


@dataclass(frozen=True)
class PrerequisiteOption:
    course_code: str
    concurrent_allowed: bool
    recommended_only: bool


@dataclass(frozen=True)
class PrerequisiteClause:
    clause_index: int
    options: tuple[PrerequisiteOption, ...]

    @property
    def is_recommendation_only(self) -> bool:
        return all(option.recommended_only for option in self.options)


@dataclass
class PrerequisiteValidationResult:
    course_code: str
    is_satisfied: bool
    unmet_clauses: list[PrerequisiteClause] = field(default_factory=list)
    satisfied_by: list[str] = field(default_factory=list)
    raw_prereq_text: str | None = None

    def unmet_summary(self) -> str:
        if self.is_satisfied or not self.unmet_clauses:
            return ""
        parts: list[str] = []
        for clause in self.unmet_clauses:
            options_text = " or ".join(
                option.course_code + ("*" if option.concurrent_allowed else "")
                for option in clause.options
            )
            if len(clause.options) > 1 and len(self.unmet_clauses) > 1:
                options_text = f"({options_text})"
            parts.append(options_text)
        return " AND ".join(parts)


def _normalize_code(value: str | None) -> str:
    return (value or "").strip().upper()


def _normalize_completed(courses: Iterable[str] | None) -> set[str]:
    if not courses:
        return set()
    return {_normalize_code(item) for item in courses if _normalize_code(item)}


class PrerequisiteService:
    """In-memory cache of prereq clauses, refreshed on each construction."""

    def __init__(self, conn: sqlite3.Connection | None = None) -> None:
        self._clauses_by_course: dict[str, list[PrerequisiteClause]] = {}
        self._raw_text_by_course: dict[str, str] = {}
        owns_conn = conn is None
        if conn is None:
            conn = sqlite3.connect(get_database_path())
            conn.row_factory = sqlite3.Row
        try:
            self._load(conn)
        finally:
            if owns_conn:
                conn.close()

    def _load(self, conn: sqlite3.Connection) -> None:
        try:
            cursor = conn.execute(
                """
                SELECT course_code, clause_index, prereq_course_code,
                       concurrent_allowed, recommended_only, raw_text
                FROM course_prerequisites
                ORDER BY course_code, clause_index, prereq_course_code
                """
            )
            rows = cursor.fetchall()
        except sqlite3.OperationalError:
            rows = []

        grouped: dict[str, dict[int, list[PrerequisiteOption]]] = {}
        for row in rows:
            # Index by column position so this works whether or not the caller
            # configured `row_factory = sqlite3.Row`.
            course_code = _normalize_code(row[0])
            prereq_code = _normalize_code(row[2])
            if not course_code or not prereq_code:
                continue
            clause_index = int(row[1])
            option = PrerequisiteOption(
                course_code=prereq_code,
                concurrent_allowed=bool(row[3]),
                recommended_only=bool(row[4]),
            )
            grouped.setdefault(course_code, {}).setdefault(clause_index, []).append(option)
            if course_code not in self._raw_text_by_course and row[5]:
                self._raw_text_by_course[course_code] = str(row[5]).strip()

        for course_code, clause_map in grouped.items():
            clauses = [
                PrerequisiteClause(clause_index=idx, options=tuple(options))
                for idx, options in sorted(clause_map.items())
            ]
            self._clauses_by_course[course_code] = clauses

    def has_prerequisites(self, course_code: str) -> bool:
        return _normalize_code(course_code) in self._clauses_by_course

    def get_clauses(self, course_code: str) -> list[PrerequisiteClause]:
        return list(self._clauses_by_course.get(_normalize_code(course_code), []))

    def get_raw_prereq_text(self, course_code: str) -> str | None:
        return self._raw_text_by_course.get(_normalize_code(course_code))

    def validate(
        self,
        course_code: str,
        completed_courses: Iterable[str] | None,
        currently_enrolled: Iterable[str] | None = None,
    ) -> PrerequisiteValidationResult:
        normalized_code = _normalize_code(course_code)
        completed = _normalize_completed(completed_courses)
        enrolled = _normalize_completed(currently_enrolled)

        clauses = self._clauses_by_course.get(normalized_code, [])
        result = PrerequisiteValidationResult(
            course_code=normalized_code,
            is_satisfied=True,
            raw_prereq_text=self._raw_text_by_course.get(normalized_code),
        )

        for clause in clauses:
            if clause.is_recommendation_only:
                continue

            satisfied_option: PrerequisiteOption | None = None
            for option in clause.options:
                if option.recommended_only:
                    continue
                if option.course_code in completed:
                    satisfied_option = option
                    break
                if option.concurrent_allowed and option.course_code in enrolled:
                    satisfied_option = option
                    break

            if satisfied_option is None:
                result.is_satisfied = False
                result.unmet_clauses.append(clause)
            else:
                result.satisfied_by.append(satisfied_option.course_code)

        return result

    def filter_takeable(
        self,
        course_codes: Iterable[str],
        completed_courses: Iterable[str] | None,
        currently_enrolled: Iterable[str] | None = None,
    ) -> tuple[list[str], list[PrerequisiteValidationResult]]:
        """Return (takeable_codes, blocked_results)."""
        completed = _normalize_completed(completed_courses)
        enrolled = _normalize_completed(currently_enrolled)
        takeable: list[str] = []
        blocked: list[PrerequisiteValidationResult] = []
        for code in course_codes:
            result = self.validate(code, completed, enrolled)
            if result.is_satisfied:
                takeable.append(_normalize_code(code))
            else:
                blocked.append(result)
        return takeable, blocked

    def build_prerequisite_graph(self) -> dict[str, set[str]]:
        """Return a flat dependency map: course_code -> set of all prereq codes (any alternative)."""
        graph: dict[str, set[str]] = {}
        for course_code, clauses in self._clauses_by_course.items():
            graph[course_code] = {
                option.course_code
                for clause in clauses
                for option in clause.options
                if not option.recommended_only
            }
        return graph

    def expand_completed_with_implied(self, completed_courses: Iterable[str] | None) -> set[str]:
        """Expand the completed-course set with transitively-implied prereqs.

        If a student completed a course, they must (by university rules) have
        completed all of that course's prereqs at some point. We walk the
        prereq graph backwards from each completed course and add every
        course that *must* have been satisfied along any path.

        For OR clauses we conservatively take the intersection across all
        alternatives — only courses required regardless of which option was
        chosen are added. This avoids over-claiming completion.

        Returns the expanded set, normalized (uppercased, single-spaced).
        """
        completed = _normalize_completed(completed_courses)
        expanded: set[str] = set(completed)
        # Iterate to a fixed point so newly implied courses can pull in their
        # own implied prereqs (e.g. CSC 415 implies CSC 230 which implies
        # MATH 226, etc.).
        changed = True
        while changed:
            changed = False
            for course_code in list(expanded):
                clauses = self._clauses_by_course.get(course_code, [])
                for clause in clauses:
                    if clause.is_recommendation_only:
                        continue
                    # Conservative: only add a course if it appears as the
                    # sole non-recommended option for this clause (i.e. the
                    # student MUST have taken it). For OR clauses with
                    # multiple real options we cannot tell which was chosen
                    # so we add nothing.
                    real_options = [opt for opt in clause.options if not opt.recommended_only]
                    if len(real_options) == 1:
                        implied_code = real_options[0].course_code
                        if implied_code and implied_code not in expanded:
                            expanded.add(implied_code)
                            changed = True
        return expanded
