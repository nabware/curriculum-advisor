from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter

from app.core.database import get_database_path


def _name_similarity(a: str, b: str) -> float:
    """Simple token overlap ratio."""
    tokens_a = set(re.sub(r"[^a-z ]", "", a.lower()).split())
    tokens_b = set(re.sub(r"[^a-z ]", "", b.lower()).split())
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / max(len(tokens_a), len(tokens_b))


def _load_local_rmp_rows() -> list[dict[str, object]]:
    conn = sqlite3.connect(get_database_path())
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT
                professor_name,
                rating,
                difficulty,
                would_take_again_pct,
                review_count,
                rmp_url
            FROM professor_sentiment_features
            WHERE rating IS NOT NULL
            """
        ).fetchall()
    finally:
        conn.close()

    return [dict(row) for row in rows]


def _load_professor_tags(professor_name: str) -> list[str]:
    conn = sqlite3.connect(get_database_path())
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT tags_json
            FROM professor_rmp_reviews
            WHERE professor_name = ?
              AND tags_json IS NOT NULL
              AND TRIM(tags_json) != ''
            """,
            (professor_name,),
        ).fetchall()
    finally:
        conn.close()

    tags: list[str] = []
    for row in rows:
        raw_tags = row["tags_json"]
        try:
            parsed = json.loads(raw_tags)
        except Exception:
            continue
        if not isinstance(parsed, list):
            continue
        for tag in parsed:
            cleaned = str(tag or "").strip()
            if cleaned:
                tags.append(cleaned)
    return tags


def _tag_tone(tag: str) -> str:
    normalized = re.sub(r"\s+", " ", tag.strip().lower())
    positive_tags = {
        "amazing lectures",
        "clear grading criteria",
        "gives good feedback",
        "accessible outside class",
        "caring",
        "respected",
        "engaging lectures",
        "lecture slides",
    }
    negative_tags = {
        "tough grader",
        "lots of homework",
        "graded by few things",
        "test heavy",
        "participation matters",
    }
    if normalized in positive_tags:
        return "green"
    if normalized in negative_tags:
        return "red"
    return "yellow"


def fetch_professor_rating(
    professor_name: str,
) -> dict | None:
    """
    Returns a dict with locally stored RMP data for the best-matching professor, or None.

    Keys: rating, difficulty, num_ratings, would_take_again_pct, rmp_url
    """
    if not professor_name or not professor_name.strip():
        return None

    best_row: dict[str, object] | None = None
    best_score = 0.0
    for row in _load_local_rmp_rows():
        stored_name = str(row.get("professor_name") or "")
        score = _name_similarity(professor_name, stored_name)
        if score > best_score:
            best_score = score
            best_row = row

    if best_row is None or best_score < 0.4:
        return None

    num_ratings = int(best_row.get("review_count") or 0)
    if num_ratings == 0:
        return None

    stored_professor_name = str(best_row.get("professor_name") or professor_name)
    tag_counter = Counter(_load_professor_tags(stored_professor_name))
    if tag_counter:
        top_tag, top_tag_count = tag_counter.most_common(1)[0]
        top_tag_tone = _tag_tone(top_tag)
    else:
        top_tag = None
        top_tag_count = None
        top_tag_tone = None

    return {
        "professor_name": stored_professor_name,
        "rating": round(float(best_row.get("rating")), 1) if best_row.get("rating") is not None else None,
        "difficulty": round(float(best_row.get("difficulty")), 1) if best_row.get("difficulty") is not None else None,
        "num_ratings": num_ratings,
        "would_take_again_pct": round(float(best_row.get("would_take_again_pct")), 1)
        if best_row.get("would_take_again_pct") is not None
        else None,
                "top_tag": top_tag,
                "top_tag_count": top_tag_count,
                "top_tag_tone": top_tag_tone,
        "rmp_url": str(best_row.get("rmp_url") or "https://www.ratemyprofessors.com"),
    }