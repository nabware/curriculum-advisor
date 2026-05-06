from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any


def _build_json_schema_prompt(review_texts: list[str]) -> str:
    joined_reviews = "\n\n".join(
        f"Review {index + 1}: {_trim_text(review, 500)}"
        for index, review in enumerate(review_texts)
    )
    return (
        "Analyze the following professor reviews about TEACHING QUALITY ONLY. "
        "ONLY mention what the PROFESSOR does/teaches, not student behaviors (attendance, homework, grades, personal struggles). "
        "Extract: teaching effectiveness, clarity of explanations, classroom engagement, course organization, grading practices, accessibility/responsiveness. "
        "Return strict JSON only: "
        '{"sentiment_label":"positive|neutral|negative","sentiment_score":0.0,"summary":"...","pros":["..."],"cons":["..."]}. '
        "sentiment_score: 0.0-1.0 where 1.0 = very positive teaching. "
        "summary: 1-2 sentences about PROFESSOR'S TEACHING APPROACH AND CLASSROOM STYLE (e.g., 'Explains concepts clearly with engaging examples' or 'Lectures are organized and provides good feedback'). "
        "If attendance is mentioned, say whether attendance is important, required, or optional; do not use vague phrases like 'poor attendance'. "
        "pros: 2-3 teaching strengths (e.g., 'Clear explanations', 'Engaging classroom', 'Provides good support', 'Well-organized course'). "
        "cons: 2-3 teaching weaknesses if mentioned (e.g., 'Moves too fast', 'Limited feedback', 'Unclear expectations'). "
        "IMPORTANT: Ignore student attendance, homework difficulty, grades, or personal situations - focus only on professor's teaching qualities.\n\n"
        f"Reviews:\n{joined_reviews}"
    )


def _build_ollama_prompt(review_texts: list[str]) -> str:
    return _build_json_schema_prompt(review_texts)


def _build_chat_prompt(review_texts: list[str]) -> str:
    return _build_json_schema_prompt(review_texts)


def _build_preference_prompt(preferences_text: str) -> str:
    cleaned_preferences = _trim_text(preferences_text, 1200)
    parts = [
        "Convert this student course preference text into strict JSON only. Treat requests like 'include an operating systems class' as must-include topic hints when possible. Treat requests like 'I don't want any difficult teachers' as a preference for lower-difficulty professors.",
        "IMPORTANT: Treat common abbreviations case-insensitively as canonical topics: 'AI' or 'ai' -> 'artificial intelligence'; 'ML' or 'ml' -> 'machine learning'; 'OS' or 'os' -> 'operating systems'. Map any abbreviation used by the user to the full topic name in the output.",
        'Return exactly this JSON schema (no extra keys, no surrounding text, no markdown): {"must_include_topics":[],"exclude_topics":[],"exclude_instructors":[],"prefer_light_workload":false,"prefer_high_rated_professors":false,"prefer_easy_teachers":false,"min_professor_rating":null,"max_professor_difficulty":null,"summary":"..."}.',
        "Provide one short example below (few-shot) for clarity.",
        "Example input: 'i want ai classes'",
        'Example output: {\n  "must_include_topics": ["artificial intelligence"],\n  "exclude_topics": [],\n  "exclude_instructors": [],\n  "prefer_light_workload": false,\n  "prefer_high_rated_professors": false,\n  "prefer_easy_teachers": false,\n  "min_professor_rating": null,\n  "max_professor_difficulty": null,\n  "summary": "Prefer courses about Artificial Intelligence."\n}',
        f"Preferences:\n{cleaned_preferences}",
    ]
    return "\n\n".join(parts)


def _build_catalog_preference_prompt(
    preferences_text: str,
    candidate_courses: list[dict[str, Any]],
) -> str:
    cleaned_preferences = _trim_text(preferences_text, 1200)
    course_lines: list[str] = []
    for index, course in enumerate(candidate_courses, start=1):
        course_lines.append(
            f"{index}. code={course.get('course_code','')} | title={course.get('title','')} | "
            f"group={course.get('group_name','')} | instructor={course.get('instructor','')} | "
            f"rmp_rating={course.get('rmp_rating')} | rmp_difficulty={course.get('rmp_difficulty')} | "
            f"sentiment={course.get('professor_sentiment_score')} | description={_trim_text(str(course.get('description') or ''), 220)}"
        )
    joined_courses = "\n".join(course_lines)

    parts = [
        "You are selecting courses from a fixed candidate list. Interpret the student's preference text and return strict JSON only. Only choose course codes that appear in the candidate list.",
        "IMPORTANT: Treat common abbreviations case-insensitively as canonical topics: 'AI'->'artificial intelligence' (and include related subtopics like 'generative AI', 'machine learning', 'deep learning', 'pattern analysis'), 'ML'->'machine learning', 'OS'->'operating systems'. Map any abbreviation to the full topic name in the output.",
        "Use professor metrics when preferences mention difficult/easy/high-rated teachers.",
        'Return this schema exactly (no extra keys, no surrounding text, no markdown): {"preferred_course_codes":[],"excluded_course_codes":[],"excluded_instructors":[],"prefer_light_workload":false,"prefer_high_rated_professors":false,"prefer_easy_teachers":false,"min_professor_rating":null,"max_professor_difficulty":null,"must_include_topics":[],"summary":"..."}.',
        "summary must be one concise sentence. Provide one short example below.",
        "Example input: 'i want ai classes'",
        '{\n  "preferred_course_codes": ["CSC 665"],\n  "excluded_course_codes": [],\n  "excluded_instructors": [],\n  "prefer_light_workload": false,\n  "prefer_high_rated_professors": false,\n  "prefer_easy_teachers": false,\n  "min_professor_rating": null,\n  "max_professor_difficulty": null,\n  "must_include_topics": ["artificial intelligence"],\n  "summary": "Prefer courses about Artificial Intelligence."\n}',
        "Student Preferences:",
        cleaned_preferences,
        "Candidate Courses:",
        joined_courses,
    ]
    return "\n\n".join(parts)


def _trim_text(value: str, limit: int) -> str:
    cleaned = re.sub(r"\s+", " ", value).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _extract_json_object(text: str) -> dict[str, Any] | None:
    candidate = text.strip()
    if not candidate:
        return None

    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\s*```$", "", candidate)
        candidate = candidate.strip()

    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    # Try to locate the first balanced JSON object (handles multiple JSON objects concatenated)
    start = None
    depth = 0
    for i, ch in enumerate(candidate):
        if ch == "{":
            if start is None:
                start = i
            depth += 1
        elif ch == "}" and start is not None:
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(candidate[start : i + 1])
                    return parsed if isinstance(parsed, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


def _normalize_sentiment_text(value: str) -> str:
    cleaned = value.strip()
    cleaned = re.sub(r"(?i)\bpoor attendance\b", "attendance is important", cleaned)
    cleaned = re.sub(r"(?i)\beasy homework\b", "homework is easy", cleaned)
    cleaned = re.sub(r"(?i)\bbad grade due to midterm\b", "grades can still suffer due to the midterm", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.;")
    return cleaned


def _call_json_llm(
    prompt: str,
    *,
    endpoint: str | None,
    model: str,
    api_key: str | None = None,
    timeout: int = 30,
) -> dict[str, Any] | None:
    if not endpoint:
        return None

    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a precise sentiment analysis engine. "
                    "Respond with valid JSON only and no markdown."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "stream": False,
            "temperature": 0.0,
    }

    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return None

    content = ""
    if isinstance(response_payload, dict):
        choices = response_payload.get("choices")
        if isinstance(choices, list) and choices:
            first_choice = choices[0]
            if isinstance(first_choice, dict):
                message = first_choice.get("message")
                if isinstance(message, dict):
                    content = str(message.get("content") or "")
                else:
                    content = str(first_choice.get("text") or "")
        if not content:
            message = response_payload.get("message")
            if isinstance(message, dict):
                content = str(message.get("content") or "")
        if not content and isinstance(response_payload.get("response"), str):
            content = str(response_payload["response"])

    parsed = _extract_json_object(content)
    return parsed if parsed else None


def _build_summary_prompt(review_texts: list[str]) -> str:
    joined_reviews = "\n\n".join(
        f"Review {index + 1}: {_trim_text(review, 500)}"
        for index, review in enumerate(review_texts)
    )
    return (
        "What do the reviews generally say about this professor? "
        "Write 1-2 complete sentences that summarize the professor's teaching style, strengths, and weaknesses using only the reviews. "
        "Return strict JSON only with this schema: "
        '{"summary":"...","pros":["..."],"cons":["..."]}. '
        "Use full sentences in the summary, not fragments. "
        "Do not mention student personal habits or outcomes unless the reviews directly say the professor's policy affects the class. "
        "Focus on teaching quality, clarity, engagement, organization, accessibility, and grading practices.\n\n"
        f"Reviews:\n{joined_reviews}"
    )


def _build_score_from_summary_prompt(
    summary: str,
    *,
    rating: float,
    difficulty: float | None,
    would_take_again_pct: float | None,
    review_count: int,
) -> str:
    return (
        "You are scoring a professor based on a written summary of student reviews and some numeric RMP stats. "
        "Return strict JSON only with this schema: "
        '{"sentiment_label":"positive|neutral|negative","sentiment_score":0.0}. '
        "sentiment_score must be a number from 0.0 to 1.0 where 1.0 means very positive. "
        "Use the summary as the main evidence. "
        "Consider the numeric stats as supporting context only. "
        "Review count: "
        f"{review_count}. "
        f"Overall rating: {rating:.2f}. "
        f"Difficulty: {('n/a' if difficulty is None else f'{difficulty:.2f}')}. "
        f"Would take again: {('n/a' if would_take_again_pct is None else f'{would_take_again_pct:.1f}%')}. "
        f"Summary: {summary}"
    )


def summarize_review_texts(
    review_texts: list[str],
    *,
    endpoint: str | None,
    model: str,
    api_key: str | None = None,
    timeout: int = 30,
) -> dict[str, Any] | None:
    cleaned_reviews = [re.sub(r"\s+", " ", review).strip() for review in review_texts if review and review.strip()]
    if not cleaned_reviews:
        return None

    parsed = _call_json_llm(
        _build_summary_prompt(cleaned_reviews),
        endpoint=endpoint,
        model=model,
        api_key=api_key,
        timeout=timeout,
    )
    if not parsed:
        return None

    summary = _normalize_sentiment_text(str(parsed.get("summary") or ""))
    pros = parsed.get("pros") if isinstance(parsed.get("pros"), list) else []
    cons = parsed.get("cons") if isinstance(parsed.get("cons"), list) else []

    return {
        "summary": summary,
        "pros": [_normalize_sentiment_text(str(item)) for item in pros if str(item).strip()],
        "cons": [_normalize_sentiment_text(str(item)) for item in cons if str(item).strip()],
    }


def parse_course_preferences(
    preferences_text: str,
    *,
    endpoint: str | None,
    model: str,
    api_key: str | None = None,
    timeout: int = 5,
) -> dict[str, Any] | None:
    cleaned_preferences = re.sub(r"\s+", " ", preferences_text).strip()
    if not cleaned_preferences:
        return None

    parsed = _call_json_llm(
        _build_preference_prompt(cleaned_preferences),
        endpoint=endpoint,
        model=model,
        api_key=api_key,
        timeout=timeout,
    )
    if not parsed:
        return None

    return {
        "must_include_topics": [str(item).strip().lower() for item in parsed.get("must_include_topics", []) if str(item).strip()],
        "exclude_topics": [str(item).strip().lower() for item in parsed.get("exclude_topics", []) if str(item).strip()],
        "exclude_instructors": [str(item).strip().lower() for item in parsed.get("exclude_instructors", []) if str(item).strip()],
        "prefer_light_workload": bool(parsed.get("prefer_light_workload", False)),
        "prefer_high_rated_professors": bool(parsed.get("prefer_high_rated_professors", False)),
        "prefer_easy_teachers": bool(parsed.get("prefer_easy_teachers", False)),
        "min_professor_rating": parsed.get("min_professor_rating"),
        "max_professor_difficulty": parsed.get("max_professor_difficulty"),
        "summary": str(parsed.get("summary") or "").strip(),
    }


def parse_course_preferences_with_catalog(
    preferences_text: str,
    candidate_courses: list[dict[str, Any]],
    *,
    endpoint: str | None,
    model: str,
    api_key: str | None = None,
    timeout: int = 20,
) -> dict[str, Any] | None:
    cleaned_preferences = re.sub(r"\s+", " ", preferences_text).strip()
    if not cleaned_preferences or not candidate_courses:
        return None

    parsed = _call_json_llm(
        _build_catalog_preference_prompt(cleaned_preferences, candidate_courses),
        endpoint=endpoint,
        model=model,
        api_key=api_key,
        timeout=timeout,
    )
    if not parsed:
        return None

    valid_codes = {str(course.get("course_code") or "").strip().upper() for course in candidate_courses}

    preferred_codes = [
        code
        for code in [str(item).strip().upper() for item in parsed.get("preferred_course_codes", []) if str(item).strip()]
        if code in valid_codes
    ]
    excluded_codes = [
        code
        for code in [str(item).strip().upper() for item in parsed.get("excluded_course_codes", []) if str(item).strip()]
        if code in valid_codes
    ]

    return {
        "preferred_course_codes": preferred_codes,
        "excluded_course_codes": excluded_codes,
        "excluded_instructors": [str(item).strip().lower() for item in parsed.get("excluded_instructors", []) if str(item).strip()],
        "prefer_light_workload": bool(parsed.get("prefer_light_workload", False)),
        "prefer_high_rated_professors": bool(parsed.get("prefer_high_rated_professors", False)),
        "prefer_easy_teachers": bool(parsed.get("prefer_easy_teachers", False)),
        "min_professor_rating": parsed.get("min_professor_rating"),
        "max_professor_difficulty": parsed.get("max_professor_difficulty"),
        "must_include_topics": [str(item).strip().lower() for item in parsed.get("must_include_topics", []) if str(item).strip()],
        "summary": str(parsed.get("summary") or "").strip(),
    }


def score_summary_text(
    summary: str,
    *,
    rating: float,
    difficulty: float | None,
    would_take_again_pct: float | None,
    review_count: int,
    endpoint: str | None,
    model: str,
    api_key: str | None = None,
    timeout: int = 30,
) -> dict[str, Any] | None:
    cleaned_summary = _normalize_sentiment_text(summary)
    if not cleaned_summary:
        return None

    parsed = _call_json_llm(
        _build_score_from_summary_prompt(
            cleaned_summary,
            rating=rating,
            difficulty=difficulty,
            would_take_again_pct=would_take_again_pct,
            review_count=review_count,
        ),
        endpoint=endpoint,
        model=model,
        api_key=api_key,
        timeout=timeout,
    )
    if not parsed:
        return None

    label = str(parsed.get("sentiment_label") or "neutral").strip().lower()
    if label not in {"positive", "neutral", "negative"}:
        label = "neutral"

    try:
        score = float(parsed.get("sentiment_score", 0.5))
    except (TypeError, ValueError):
        score = 0.5
    score = max(0.0, min(1.0, score))

    return {"sentiment_label": label, "sentiment_score": score}


def _build_prompt(review_texts: list[str]) -> str:
    joined_reviews = "\n\n".join(
        f"Review {index + 1}: {_trim_text(review, 500)}"
        for index, review in enumerate(review_texts)
    )
    return (
        "Analyze the following professor reviews and return strict JSON only. "
        "Use the reviews, not any outside knowledge. "
        "Return this schema exactly: "
        '{"sentiment_label":"positive|neutral|negative","sentiment_score":0.0,"summary":"...",'
        '"pros":["..."],"cons":["..."]}. '
        "sentiment_score must be a number from 0.0 to 1.0 where 1.0 means very positive. "
        "Keep summary to one or two sentences. "
        "If the reviews are mixed, label them neutral and keep the score near 0.5.\n\n"
        f"Reviews:\n{joined_reviews}"
    )


def analyze_review_texts(
    review_texts: list[str],
    *,
    endpoint: str | None,
    model: str,
    api_key: str | None = None,
    timeout: int = 30,
) -> dict[str, Any] | None:
    cleaned_reviews = [re.sub(r"\s+", " ", review).strip() for review in review_texts if review and review.strip()]
    if not cleaned_reviews or not endpoint:
        return None

    prompt = _build_prompt(cleaned_reviews)
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a precise sentiment analysis engine. "
                    "Respond with valid JSON only and no markdown."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
    }

    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return None

    content = ""
    if isinstance(response_payload, dict):
        choices = response_payload.get("choices")
        if isinstance(choices, list) and choices:
            first_choice = choices[0]
            if isinstance(first_choice, dict):
                message = first_choice.get("message")
                if isinstance(message, dict):
                    content = str(message.get("content") or "")
                else:
                    content = str(first_choice.get("text") or "")
        if not content and isinstance(response_payload.get("response"), str):
            content = str(response_payload["response"])

    parsed = _extract_json_object(content)
    if not parsed:
        return None

    label = str(parsed.get("sentiment_label") or "neutral").strip().lower()
    if label not in {"positive", "neutral", "negative"}:
        label = "neutral"

    try:
        score = float(parsed.get("sentiment_score", 0.5))
    except (TypeError, ValueError):
        score = 0.5
    score = max(0.0, min(1.0, score))

    summary = _normalize_sentiment_text(str(parsed.get("summary") or ""))
    pros = parsed.get("pros") if isinstance(parsed.get("pros"), list) else []
    cons = parsed.get("cons") if isinstance(parsed.get("cons"), list) else []

    return {
        "sentiment_label": label,
        "sentiment_score": score,
        "summary": summary,
        "pros": [_normalize_sentiment_text(str(item)) for item in pros if str(item).strip()],
        "cons": [_normalize_sentiment_text(str(item)) for item in cons if str(item).strip()],
    }