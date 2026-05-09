"""Conversational orchestrator that wires the LLM intent extractor to the
deterministic AdvisorService and adds per-course natural-language rationales.

Design goals (CPU-friendly demo):
  - One small LLM call per turn for intent (Llama 3.2 3B by default).
  - One additional LLM call per turn for short per-course rationales.
  - If Ollama is unreachable, falls back to keyword intent parsing and to
    pre-computed `recommendation_rationale_template` rows in SQLite.
  - The deterministic prereq filter inside AdvisorService still owns correctness;
    the LLM never authors course codes that bypass it.
"""
from __future__ import annotations

import os
import re
import sqlite3
from typing import Any

from app.core.database import get_database_path
from app.models.schemas import (
    AdvisorRequest,
    AdvisorResponse,
    BlockedTimeWindow,
    ChatRequest,
    ChatResponse,
    ChatState,
    ChatTurn,
    RecommendedCourse,
)
from app.services.advisor_service import AdvisorService
from app.services.llama_sentiment_service import (
    extract_chat_intent,
    generate_course_rationales,
)


_DEFAULT_OLLAMA_ENDPOINT = "http://localhost:11434/v1/chat/completions"
_DEFAULT_CHAT_MODEL = "llama3.2:3b"


def _ollama_endpoint() -> str:
    return os.environ.get("CURRICULUM_ADVISOR_CHAT_ENDPOINT", _DEFAULT_OLLAMA_ENDPOINT)


def _chat_model() -> str:
    return os.environ.get("CURRICULUM_ADVISOR_CHAT_MODEL", _DEFAULT_CHAT_MODEL)


def _runtime_rationales_enabled() -> bool:
    """Per-course LLM rationales add ~10s on CPU. Off by default for demo speed.

    Set CURRICULUM_ADVISOR_RUNTIME_RATIONALES=1 to enable LLM-generated
    per-course explanations (will fall back to pre-built templates either way).
    """
    raw = os.environ.get("CURRICULUM_ADVISOR_RUNTIME_RATIONALES", "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _fast_intent_enabled() -> bool:
    """Skip the LLM intent call when the regex extractor already produced a
    confident result (both major and term resolved). Saves ~5-10s on CPU.

    Set CURRICULUM_ADVISOR_FAST_INTENT=0 to always call the LLM.
    """
    raw = os.environ.get("CURRICULUM_ADVISOR_FAST_INTENT", "1").strip().lower()
    return raw in {"1", "true", "yes", "on"}


COURSE_CODE_REGEX = re.compile(r"\b([A-Z]{2,6})\s+(\d{2,4}[A-Z]{0,3})\b")
# Department codes that look like words but aren't real SFSU departments —
# guards against accidentally matching things like 'FALL 2026'.
_NON_DEPARTMENT_TOKENS = {
    "FALL",
    "SPRING",
    "SUMMER",
    "WINTER",
    "TERM",
    "YEAR",
    "BS",
    "BA",
    "MS",
    "MA",
    "PHD",
    "GPA",
}


def _normalize_state(state: ChatState) -> ChatState:
    return ChatState(
        major=(state.major or "").strip() or None,
        term=(state.term or "").strip() or None,
        completed_courses=sorted(
            {str(code).strip().upper() for code in state.completed_courses if str(code).strip()}
        ),
        transcript_text=state.transcript_text,
        preferences_text=(state.preferences_text or "").strip() or None,
        prefer_high_rated_professors=bool(state.prefer_high_rated_professors),
        prefer_light_workload=bool(state.prefer_light_workload),
        max_units_per_semester=state.max_units_per_semester,
        blocked_time_windows=list(state.blocked_time_windows),
    )


def _list_degree_names() -> list[str]:
    try:
        with sqlite3.connect(get_database_path()) as conn:
            rows = conn.execute(
                "SELECT degree_name FROM degree_programs ORDER BY degree_name"
            ).fetchall()
        return [row[0] for row in rows if row and row[0]]
    except sqlite3.OperationalError:
        return []


def _load_template_rationales(course_codes: list[str]) -> dict[str, str]:
    if not course_codes:
        return {}
    placeholders = ",".join(["?"] * len(course_codes))
    try:
        with sqlite3.connect(get_database_path()) as conn:
            cursor = conn.execute(
                f"""
                SELECT UPPER(course_code), recommendation_rationale_template
                FROM course_descriptions
                WHERE UPPER(course_code) IN ({placeholders})
                  AND recommendation_rationale_template IS NOT NULL
                """,
                [code.upper() for code in course_codes],
            )
            return {str(row[0]): str(row[1]) for row in cursor.fetchall() if row[0] and row[1]}
    except sqlite3.OperationalError:
        return {}


_DAY_KEYWORDS = {
    "monday": "Monday",
    "mondays": "Monday",
    "mon": "Monday",
    "tuesday": "Tuesday",
    "tuesdays": "Tuesday",
    "tue": "Tuesday",
    "tues": "Tuesday",
    "wednesday": "Wednesday",
    "wednesdays": "Wednesday",
    "wed": "Wednesday",
    "thursday": "Thursday",
    "thursdays": "Thursday",
    "thu": "Thursday",
    "thur": "Thursday",
    "thurs": "Thursday",
    "friday": "Friday",
    "fridays": "Friday",
    "fri": "Friday",
}


def _extract_blocked_time_windows(text: str) -> list[dict[str, str]]:
    """Heuristic extraction of blocked-time windows from natural language.

    Recognizes phrasings like:
      - "I can't make Tuesdays" / "no Tuesdays"
      - "I can't do anything before 11am on Mondays"
      - "I have to leave by 4pm on Wednesday"
      - "no Friday afternoons"

    Day-only mentions are interpreted as the entire 8 AM - 9 PM window.
    Time-only mentions ("before 11am", "after 5pm") apply to all five
    weekdays. Combined day+time mentions narrow the window appropriately.
    """
    if not text:
        return []
    lower = text.lower()
    # Skip extraction unless the message is clearly about availability.
    availability_signal = re.search(
        r"\b(can(?:'|\s+|\u2019)?t|cannot|can\s*not|won(?:'|\s+|\u2019)?t|"
        r"unavailable|busy|no(?:t)?\s+free|not\s+available|"
        r"before|after|until|by|leave\s+by|until|prior\s+to|"
        r"need\s+to\s+leave|need\s+to\s+(?:be\s+)?(?:home|out|done))\b",
        lower,
    )
    explicit_no_day = re.search(
        r"\bno\s+(monday|tuesday|wednesday|thursday|friday)s?\b", lower
    )
    if not availability_signal and not explicit_no_day:
        return []

    detected_days: list[str] = []
    seen: set[str] = set()
    for token, canonical in _DAY_KEYWORDS.items():
        if re.search(rf"\b{token}\b", lower) and canonical not in seen:
            detected_days.append(canonical)
            seen.add(canonical)
    if not detected_days:
        # No specific day mentioned. Apply across all weekdays.
        detected_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

    # Detect time-of-day window. Defaults to entire school day.
    start_time = "8:00AM"
    end_time = "9:00PM"

    def _format_clock(hour: int, minute: int) -> str:
        period = "AM" if hour < 12 else "PM"
        display_hour = hour % 12 or 12
        return f"{display_hour}:{minute:02d}{period}"

    def _parse_clock(match_hour: str, match_minute: str | None, match_period: str | None) -> tuple[int, int] | None:
        try:
            hour = int(match_hour)
        except ValueError:
            return None
        minute = int(match_minute) if match_minute else 0
        period = (match_period or "").lower()
        if period == "pm" and hour < 12:
            hour += 12
        elif period == "am" and hour == 12:
            hour = 0
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None
        return hour, minute

    before_match = re.search(
        r"\b(?:before|by|until|prior\s+to|need\s+to\s+leave\s+by|leave\s+by|done\s+by)\s+"
        r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|noon|midnight)?",
        lower,
    )
    after_match = re.search(
        r"\bafter\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm|noon|midnight)?",
        lower,
    )
    if "noon" in lower and "before noon" in lower:
        end_time = "12:00PM"
        start_time = "8:00AM"
    elif before_match:
        period = before_match.group(3)
        if period == "noon":
            end_time = "12:00PM"
        elif period == "midnight":
            end_time = "11:59PM"
        else:
            parsed = _parse_clock(before_match.group(1), before_match.group(2), period)
            if parsed:
                hour, minute = parsed
                end_time = _format_clock(hour, minute)
                start_time = "8:00AM"
    elif after_match:
        period = after_match.group(3)
        if period == "noon":
            start_time = "12:00PM"
            end_time = "9:00PM"
        elif period == "midnight":
            start_time = "11:59PM"
            end_time = "11:59PM"
        else:
            parsed = _parse_clock(after_match.group(1), after_match.group(2), period)
            if parsed:
                hour, minute = parsed
                start_time = _format_clock(hour, minute)
                end_time = "9:00PM"
    elif re.search(r"\bmorning(s)?\b", lower):
        start_time = "8:00AM"
        end_time = "12:00PM"
    elif re.search(r"\bafternoon(s)?\b", lower):
        start_time = "12:00PM"
        end_time = "5:00PM"
    elif re.search(r"\bevening(s)?\b|\bnight(s)?\b", lower):
        start_time = "5:00PM"
        end_time = "9:00PM"

    return [
        {"day": day, "start": start_time, "end": end_time}
        for day in detected_days
    ]


def _fallback_intent(message: str, state: ChatState, available_degrees: list[str]) -> dict[str, Any]:
    text = (message or "").strip()
    lower_text = text.lower()

    detected_codes: list[str] = []
    for dept, num in COURSE_CODE_REGEX.findall(text.upper()):
        if dept in _NON_DEPARTMENT_TOKENS:
            continue
        detected_codes.append(f"{dept} {num}")

    detected_term = None
    term_match = re.search(r"\b(spring|summer|fall|winter)\s+(20\d{2})\b", text, flags=re.IGNORECASE)
    if term_match:
        detected_term = f"{term_match.group(1).capitalize()} {term_match.group(2)}"

    detected_major: str | None = None
    if state.major:
        detected_major = state.major
    else:
        for degree in available_degrees:
            if degree.lower() in lower_text:
                detected_major = degree
                break
        if not detected_major:
            wants_master = bool(
                re.search(r"\b(ms|mscs|msdsai|master|graduate)\b", lower_text)
            )
            wants_dsai = "dsai" in lower_text or "data science" in lower_text
            wants_cs = (
                "computer science" in lower_text
                or re.search(r"\b(b\s*s\s*cs|bscs|cs|cscs)\b", lower_text)
                or "bachelor of science in computer science" in lower_text
            )
            if wants_dsai:
                for degree in available_degrees:
                    if "data science" in degree.lower():
                        detected_major = degree
                        break
            elif wants_cs and wants_master:
                for degree in available_degrees:
                    if "computer science" in degree.lower() and "master" in degree.lower():
                        detected_major = degree
                        break
            elif wants_cs:
                for degree in available_degrees:
                    if "computer science" in degree.lower() and "master" not in degree.lower():
                        detected_major = degree
                        break

    prefer_light_workload = bool(re.search(r"light\s+workload|easier\s+classes|less\s+work", lower_text))
    prefer_high_rated = bool(
        re.search(
            r"high.?rated|highly.?rated|well.?rated|top.?rated|"
            r"(?:great|good|excellent|amazing|positive|favorable|loved|top|best)"
            r"\s+(?:professor|prof|profs|teacher|instructor|review|reviews|rating|ratings)|"
            r"favor\s+(?:highly|good|great).*professor",
            lower_text,
        )
    )

    max_units_match = re.search(r"\b(\d{1,2})\s*(?:units|credits?)\b", lower_text)
    max_units = int(max_units_match.group(1)) if max_units_match else None

    intent = "recommend"
    if not detected_major and not state.major and not detected_term and not state.term and not detected_codes:
        if re.match(r"^\s*(hi|hello|hey|thanks?|thank you|cool|nice)\b", lower_text):
            intent = "smalltalk"

    missing: list[str] = []
    if intent == "recommend":
        if not (detected_major or state.major):
            missing.append("major")
        if not (detected_term or state.term):
            missing.append("term")

    reply_parts: list[str] = []
    if intent == "smalltalk":
        reply_parts.append("Happy to help! Tell me your major, the term you're planning, and any preferences.")
    else:
        if missing:
            need = " and ".join(missing)
            reply_parts.append(f"Got it. To recommend courses I still need your {need}.")
        else:
            reply_parts.append("Got it. Pulling a sentiment-aware plan that respects your prereqs.")

    # Always pass the full message as preferences_text so the downstream
    # AdvisorService preference parser can extract topic hints ("AI elective",
    # "operating systems", etc.) and additional sentiment cues. Previously we
    # dropped this whenever a major or course code was detected, which lost
    # everything the student said about what they actually wanted.
    detected_blocked_windows = _extract_blocked_time_windows(text)

    return {
        "major": detected_major,
        "term": detected_term,
        "max_units_per_semester": max_units,
        "completed_courses": detected_codes,
        "preferences_text": text or None,
        "prefer_high_rated_professors": prefer_high_rated,
        "prefer_light_workload": prefer_light_workload,
        "blocked_time_windows": detected_blocked_windows,
        "intent": intent,
        "missing_required_fields": missing,
        "assistant_reply": " ".join(reply_parts),
    }


def _merge_intent_into_state(state: ChatState, intent: dict[str, Any]) -> ChatState:
    completed_set = {code.strip().upper() for code in state.completed_courses if code.strip()}
    for code in intent.get("completed_courses") or []:
        completed_set.add(str(code).strip().upper())

    new_major = intent.get("major") or state.major
    new_term = intent.get("term") or state.term
    new_max_units = intent.get("max_units_per_semester") or state.max_units_per_semester

    # Accumulate preferences across turns so Turn 1's "AI elective" preference
    # isn't lost when Turn 2 only adds "I can't make Tuesdays". Avoid
    # appending if the new text is already a substring of the previous.
    new_prefs_text = state.preferences_text
    incoming_prefs = (intent.get("preferences_text") or "").strip()
    if incoming_prefs:
        existing = (state.preferences_text or "").strip()
        if not existing:
            new_prefs_text = incoming_prefs
        elif incoming_prefs in existing or existing in incoming_prefs:
            new_prefs_text = existing if len(existing) >= len(incoming_prefs) else incoming_prefs
        else:
            new_prefs_text = (existing + "\n" + incoming_prefs).strip()

    # Merge blocked-time windows by (day, start, end) so Turn 2's "Tuesdays"
    # adds to (rather than replaces) anything already in state.
    seen_windows: set[tuple[str, str, str]] = set()
    merged_windows: list[BlockedTimeWindow] = []
    for window in list(state.blocked_time_windows):
        key = (window.day.strip(), window.start.strip(), window.end.strip())
        if key in seen_windows:
            continue
        seen_windows.add(key)
        merged_windows.append(window)
    for window_dict in intent.get("blocked_time_windows") or []:
        if not isinstance(window_dict, dict):
            continue
        day = str(window_dict.get("day") or "").strip()
        start = str(window_dict.get("start") or "").strip()
        end = str(window_dict.get("end") or "").strip()
        if not day or not start or not end:
            continue
        key = (day, start, end)
        if key in seen_windows:
            continue
        seen_windows.add(key)
        merged_windows.append(BlockedTimeWindow(day=day, start=start, end=end))

    return ChatState(
        major=new_major,
        term=new_term,
        completed_courses=sorted(completed_set),
        transcript_text=state.transcript_text,
        preferences_text=new_prefs_text,
        prefer_high_rated_professors=bool(intent.get("prefer_high_rated_professors") or state.prefer_high_rated_professors),
        prefer_light_workload=bool(intent.get("prefer_light_workload") or state.prefer_light_workload),
        max_units_per_semester=new_max_units,
        blocked_time_windows=merged_windows,
    )


def _attach_rationales(
    advisor: AdvisorResponse,
    state: ChatState,
    *,
    chat_endpoint: str | None,
    chat_model: str,
) -> str:
    """Fill `course.rationale` for every recommendation. Returns rationale source label."""
    if not advisor.recommendations:
        return "none"

    course_summaries = [
        {
            "course_code": course.course_code,
            "title": course.title,
            "group_name": course.group_name,
            "units": course.units,
            "prerequisite_text": course.prerequisite_text,
            "professor_name": course.professor_name,
            "professor_sentiment_score": course.professor_sentiment_score,
            "rmp_rating": course.rmp_rating,
            "rmp_difficulty": course.rmp_difficulty,
        }
        for course in advisor.recommendations
    ]
    student_context = {
        "major": state.major,
        "term": state.term,
        "completed_courses": list(state.completed_courses),
        "preferences_text": state.preferences_text,
    }

    llm_rationales: dict[str, str] | None = None
    if chat_endpoint:
        try:
            llm_rationales = generate_course_rationales(
                course_summaries,
                student_context,
                endpoint=chat_endpoint,
                model=chat_model,
                timeout=20,
            )
        except Exception:
            llm_rationales = None

    template_rationales: dict[str, str] = {}
    missing_codes = [
        course.course_code
        for course in advisor.recommendations
        if not (llm_rationales and course.course_code.upper() in llm_rationales)
    ]
    if missing_codes:
        template_rationales = _load_template_rationales(missing_codes)

    used_llm = False
    used_template = False
    for course in advisor.recommendations:
        code_upper = course.course_code.upper()
        text: str | None = None
        if llm_rationales and code_upper in llm_rationales:
            text = llm_rationales[code_upper]
            used_llm = True
        elif code_upper in template_rationales:
            text = template_rationales[code_upper]
            used_template = True
        course.rationale = text

    if used_llm and used_template:
        return "llm+template"
    if used_llm:
        return "llm"
    if used_template:
        return "template"
    return "none"


def _compose_assistant_reply(
    intent: dict[str, Any],
    advisor: AdvisorResponse | None,
    intent_source: str,
    rationale_source: str,
    missing_required_fields: list[str] | None = None,
) -> str:
    base = (intent.get("assistant_reply") or "").strip()
    missing = list(missing_required_fields or [])

    if advisor is None:
        # The LLM sometimes hallucinates a "Here are your classes" reply even when
        # we lack the info needed to produce them. Override with an honest prompt.
        if missing:
            need = " and ".join(missing)
            hint = ""
            if "major" in missing:
                hint = " For example: 'BSCS', 'MSCS', or 'MS DSAI'."
            return (
                f"I still need your {need} before I can recommend courses.{hint}"
            ).strip()
        return base or "I need a bit more information before I can recommend courses."

    course_codes = [course.course_code for course in advisor.recommendations]
    if not course_codes:
        return (
            "I couldn't find any takeable courses for that combination. "
            "Try a different term or relax a constraint."
        )

    summary = (
        f"Here are {len(course_codes)} courses ({', '.join(course_codes)}) "
        f"totaling {advisor.total_units_selected} units."
    )

    extras: list[str] = []
    if advisor.prerequisite_blocked_courses:
        extras.append(
            f"Skipped {len(advisor.prerequisite_blocked_courses)} courses with unmet prereqs (deterministic check)."
        )
    if rationale_source.startswith("llm"):
        extras.append("Each recommendation includes a short reason generated for your situation.")

    # Only include the LLM's friendly preamble if it doesn't claim we already produced
    # something we didn't (e.g., "Here are 3 courses" when course_codes is empty above).
    parts = [base, summary] + extras
    return " ".join(part for part in parts if part).strip()


class ChatService:
    @staticmethod
    def respond(payload: ChatRequest) -> ChatResponse:
        normalized_state = _normalize_state(payload.state)
        available_degrees = _list_degree_names()

        endpoint = _ollama_endpoint()
        chat_model = _chat_model()

        intent: dict[str, Any] | None = None
        intent_source = "fallback"

        # Fast-intent path: when the regex extractor already resolves both
        # `major` and `term`, skip the LLM intent call entirely (~5-10s win
        # on CPU). The LLM still runs whenever the regex is uncertain.
        regex_intent = _fallback_intent(payload.message, normalized_state, available_degrees)
        regex_has_major = bool(regex_intent.get("major") or normalized_state.major)
        regex_has_term = bool(regex_intent.get("term") or normalized_state.term)
        regex_is_smalltalk = (regex_intent.get("intent") or "").lower() == "smalltalk"

        if _fast_intent_enabled() and (
            (regex_has_major and regex_has_term) or regex_is_smalltalk
        ):
            intent = regex_intent
            intent_source = "regex"
        else:
            try:
                intent = extract_chat_intent(
                    payload.message,
                    available_degrees=available_degrees,
                    history=[turn.model_dump() for turn in payload.history],
                    known_state=normalized_state.model_dump(),
                    endpoint=endpoint,
                    model=chat_model,
                    timeout=15,
                )
                if intent:
                    intent_source = "llm"
            except Exception:
                intent = None

            if intent is None:
                intent = regex_intent

        merged_state = _merge_intent_into_state(normalized_state, intent)

        # Decide whether to call the advisor: skip on smalltalk or when required fields are missing.
        intent_kind = (intent.get("intent") or "recommend").lower()
        # The LLM occasionally hallucinates a field as "missing" even when it
        # extracted that field successfully (e.g. extracts term="Fall 2026" but
        # still puts "term" in missing_required_fields). Authoritative source of
        # truth is `merged_state` — recompute from there.
        missing_required: list[str] = []
        if not merged_state.major:
            missing_required.append("major")
        if not merged_state.term:
            missing_required.append("term")

        advisor: AdvisorResponse | None = None
        rationale_source = "none"

        if intent_kind in {"recommend", "update_state"} and not missing_required:
            advisor_request = AdvisorRequest(
                major=merged_state.major or "",
                completed_courses=merged_state.completed_courses,
                preferences_text=merged_state.preferences_text,
                transcript_text=merged_state.transcript_text,
                blocked_time_windows=list(merged_state.blocked_time_windows),
                interests=[],
                career_goals=[],
                prefer_light_workload=merged_state.prefer_light_workload,
                prefer_high_rated_professors=merged_state.prefer_high_rated_professors,
                max_units_per_semester=merged_state.max_units_per_semester or 12,
                term=merged_state.term,
            )
            advisor = AdvisorService.recommend(advisor_request)
            # Default: skip the per-course LLM rationale call (~10s on CPU)
            # and use pre-built templates for fast responses. Set
            # CURRICULUM_ADVISOR_RUNTIME_RATIONALES=1 to opt into LLM
            # rationales for the demo "wow" moment.
            rationale_endpoint = endpoint if _runtime_rationales_enabled() else None
            rationale_source = _attach_rationales(
                advisor,
                merged_state,
                chat_endpoint=rationale_endpoint,
                chat_model=chat_model,
            )

        reply = _compose_assistant_reply(
            intent, advisor, intent_source, rationale_source, missing_required
        )

        return ChatResponse(
            reply=reply,
            intent=intent_kind,
            state=merged_state,
            advisor=advisor,
            rationale_source=rationale_source,
            intent_source=intent_source,
            missing_required_fields=missing_required,
        )

    @staticmethod
    def warmup() -> None:
        """One-shot call to load the chat model into Ollama memory at startup."""
        endpoint = _ollama_endpoint()
        if not endpoint:
            return
        try:
            extract_chat_intent(
                "hi",
                available_degrees=_list_degree_names(),
                endpoint=endpoint,
                model=_chat_model(),
                timeout=60,
            )
        except Exception:
            pass
