#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
from collections import Counter
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.core.database import get_database_path
from app.services.llama_sentiment_service import summarize_review_texts
from rmp_client import RMPClient


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalize_name(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip().lower()


def name_tokens(value: str | None) -> list[str]:
    normalized = normalize_name(value)
    if not normalized:
        return []
    cleaned = re.sub(r"[^a-z\s-]", " ", normalized)
    return [token for token in re.split(r"[\s-]+", cleaned) if token]


def last_name_key(value: str | None) -> str | None:
    tokens = name_tokens(value)
    if not tokens:
        return None
    return tokens[-1]


def last_name_first_initial_key(value: str | None) -> str | None:
    tokens = name_tokens(value)
    if len(tokens) < 2:
        return None
    return f"{tokens[-1]}|{tokens[0][0]}"


def name_similarity(a: str, b: str) -> float:
    tokens_a = set(re.sub(r"[^a-z ]", "", a.lower()).split())
    tokens_b = set(re.sub(r"[^a-z ]", "", b.lower()).split())
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / max(len(tokens_a), len(tokens_b))


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


TAG_SENTIMENT_WEIGHTS: dict[str, float] = {
    "amazing lectures": 1.0,
    "clear grading criteria": 0.85,
    "gives good feedback": 0.75,
    "accessible outside class": 0.6,
    "caring": 0.55,
    "respected": 0.5,
    "engaging lectures": 0.5,
    "lecture slides": 0.3,
    "tough grader": -0.85,
    "lots of homework": -0.5,
    "graded by few things": -0.45,
    "test heavy": -0.4,
    "participation matters": -0.2,
}
TAG_SCORE_BLEND = 0.08
TAG_EVIDENCE_SATURATION = 8.0


def normalize_tag(value: str | None) -> str:
    return normalize_space(value or "").lower()


def extract_tags_from_json(tags_json: object) -> list[str]:
    raw_tags: object = tags_json
    if isinstance(tags_json, str):
        try:
            raw_tags = json.loads(tags_json)
        except json.JSONDecodeError:
            raw_tags = []

    if not isinstance(raw_tags, list):
        return []

    tags = [normalize_tag(str(tag)) for tag in raw_tags]
    return [tag for tag in tags if tag]


def calculate_tag_signal(review_records: list[dict[str, object]]) -> dict[str, float | int]:
    matched_tags: list[str] = []
    for record in review_records:
        matched_tags.extend(extract_tags_from_json(record.get("tags_json")))

    if not matched_tags:
        return {
            "tag_count": 0,
            "tag_positive_count": 0,
            "tag_negative_count": 0,
            "tag_sentiment_score": 0.0,
            "tag_sentiment_adjustment": 0.0,
            "tag_adjusted_sentiment_score": 0.0,
        }

    tag_counts = Counter(tag for tag in matched_tags if tag in TAG_SENTIMENT_WEIGHTS)
    if not tag_counts:
        return {
            "tag_count": 0,
            "tag_positive_count": 0,
            "tag_negative_count": 0,
            "tag_sentiment_score": 0.0,
            "tag_sentiment_adjustment": 0.0,
            "tag_adjusted_sentiment_score": 0.0,
        }

    weighted_sum = 0.0
    weighted_total = 0.0
    positive_count = 0
    negative_count = 0
    for tag, count in tag_counts.items():
        weight = TAG_SENTIMENT_WEIGHTS[tag]
        weighted_sum += weight * count
        weighted_total += abs(weight) * count
        if weight > 0:
            positive_count += count
        elif weight < 0:
            negative_count += count

    raw_tag_score = (weighted_sum / weighted_total) if weighted_total > 0 else 0.0
    evidence_weight = min(1.0, len(tag_counts) / TAG_EVIDENCE_SATURATION)
    tag_sentiment_score = raw_tag_score * evidence_weight
    tag_sentiment_adjustment = tag_sentiment_score * TAG_SCORE_BLEND

    return {
        "tag_count": int(sum(tag_counts.values())),
        "tag_positive_count": positive_count,
        "tag_negative_count": negative_count,
        "tag_sentiment_score": tag_sentiment_score,
        "tag_sentiment_adjustment": tag_sentiment_adjustment,
        "tag_adjusted_sentiment_score": 0.0,
    }


def apply_tag_adjustment(base_score: float, tag_adjustment: float) -> float:
    return clamp(base_score + tag_adjustment, 0.0, 1.0)


def calculate_sentiment_features(
    rating: float,
    difficulty: float | None,
    would_take_again_pct: float | None,
    num_ratings: int,
    *,
    prior_weight: int,
    prior_rating_mean: float,
) -> dict[str, float]:
    review_count = max(0, int(num_ratings))
    confidence_weight = review_count / (review_count + prior_weight) if review_count > 0 else 0.0

    rating_clamped = clamp(float(rating), 0.0, 5.0)
    rating_shrunk = (
        (review_count * rating_clamped + prior_weight * prior_rating_mean)
        / (review_count + prior_weight)
        if review_count > 0
        else prior_rating_mean
    )
    rating_score = rating_shrunk / 5.0

    difficulty_score: float | None = None
    if difficulty is not None:
        difficulty_clamped = clamp(float(difficulty), 1.0, 5.0)
        difficulty_score = 1.0 - ((difficulty_clamped - 1.0) / 4.0)

    would_take_again_score: float | None = None
    if would_take_again_pct is not None:
        wta_clamped = clamp(float(would_take_again_pct), 0.0, 100.0)
        would_take_again_score = wta_clamped / 100.0

    weighted_sum = 0.0
    weighted_total = 0.0

    weighted_sum += 0.60 * rating_score
    weighted_total += 0.60

    if would_take_again_score is not None:
        weighted_sum += 0.25 * would_take_again_score
        weighted_total += 0.25

    if difficulty_score is not None:
        weighted_sum += 0.15 * difficulty_score
        weighted_total += 0.15

    base_sentiment_score = (weighted_sum / weighted_total) if weighted_total > 0 else 0.0
    confidence_adjusted_sentiment_score = base_sentiment_score * confidence_weight

    return {
        "confidence_weight": confidence_weight,
        "rating_shrunk": rating_shrunk,
        "rating_score": rating_score,
        "difficulty_score": difficulty_score if difficulty_score is not None else -1.0,
        "would_take_again_score": would_take_again_score if would_take_again_score is not None else -1.0,
        "base_sentiment_score": base_sentiment_score,
        "confidence_adjusted_sentiment_score": confidence_adjusted_sentiment_score,
    }


def ensure_sentiment_feature_columns(conn: sqlite3.Connection) -> None:
    existing_columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(professor_sentiment_features)").fetchall()
    }
    required_columns = {
        "tag_count": "INTEGER",
        "tag_positive_count": "INTEGER",
        "tag_negative_count": "INTEGER",
        "tag_sentiment_score": "REAL",
        "tag_sentiment_adjustment": "REAL",
        "tag_adjusted_sentiment_score": "REAL",
    }
    for column_name, column_type in required_columns.items():
        if column_name not in existing_columns:
            conn.execute(f"ALTER TABLE professor_sentiment_features ADD COLUMN {column_name} {column_type}")


def fetch_professor_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT professor_name
        FROM professor_profiles
        WHERE professor_name IS NOT NULL
          AND TRIM(professor_name) != ''
        ORDER BY professor_name
        """
    ).fetchall()
    return [str(row[0]).strip() for row in rows]


def fetch_existing_rows(conn: sqlite3.Connection) -> dict[str, dict[str, object]]:
    rows = conn.execute(
        """
        SELECT *
        FROM professor_sentiment_features
        """
    ).fetchall()
    return {normalize_name(str(row["professor_name"] or "")): dict(row) for row in rows}


def build_name_indexes(
    rows: list[dict[str, object]],
) -> tuple[dict[str, dict[str, object]], dict[str, list[dict[str, object]]], dict[str, list[dict[str, object]]]]:
    by_full: dict[str, dict[str, object]] = {}
    by_last_initial: dict[str, list[dict[str, object]]] = {}
    by_last_name: dict[str, list[dict[str, object]]] = {}

    for row in rows:
        name = str(row.get("professor_name") or "")
        full_key = normalize_name(name)
        if full_key and full_key not in by_full:
            by_full[full_key] = row

        initial_key = last_name_first_initial_key(name)
        if initial_key:
            by_last_initial.setdefault(initial_key, []).append(row)

        last_key = last_name_key(name)
        if last_key:
            by_last_name.setdefault(last_key, []).append(row)

    return by_full, by_last_initial, by_last_name


def resolve_existing_row(
    professor_name: str,
    by_full: dict[str, dict[str, object]],
    by_last_initial: dict[str, list[dict[str, object]]],
    by_last_name: dict[str, list[dict[str, object]]],
) -> dict[str, object] | None:
    full_key = normalize_name(professor_name)
    if full_key and full_key in by_full:
        return by_full[full_key]

    initial_key = last_name_first_initial_key(professor_name)
    if initial_key:
        matches = by_last_initial.get(initial_key, [])
        if len(matches) == 1:
            return matches[0]

    last_key = last_name_key(professor_name)
    if last_key:
        matches = by_last_name.get(last_key, [])
        if len(matches) == 1:
            return matches[0]

    best_row: dict[str, object] | None = None
    best_score = 0.0
    for row in by_full.values():
        candidate_name = str(row.get("professor_name") or "")
        score = name_similarity(professor_name, candidate_name)
        if score > best_score:
            best_score = score
            best_row = row

    if best_row is not None and best_score >= 0.4:
        return best_row

    return None


def resolve_live_professor(client: RMPClient, professor_name: str, school_id: str) -> object | None:
    search_result = client.search_professors(professor_name, school_id=school_id, page_size=10)
    professors = list(search_result.professors)
    if not professors:
        search_result = client.search_professors(professor_name, page_size=10)
        professors = list(search_result.professors)

    if not professors:
        return None

    target_name = professor_name.strip().casefold()
    for professor in professors:
        if getattr(professor, "name", "").strip().casefold() == target_name:
            return professor

    return max(
        professors,
        key=lambda professor: name_similarity(professor_name, getattr(professor, "name", "")),
    )


def extract_professor_summary(professor: object) -> dict[str, object]:
    tags = getattr(professor, "tags", None)
    rating_distribution = getattr(professor, "rating_distribution", None)
    school = getattr(professor, "school", None)

    return {
        "professor_name": getattr(professor, "name", None),
        "rmp_professor_id": getattr(professor, "id", None),
        "department": getattr(professor, "department", None),
        "school_name": getattr(school, "name", None),
        "school_id": getattr(school, "id", None),
        "overall_rating": getattr(professor, "overall_rating", None),
        "num_ratings": getattr(professor, "num_ratings", None),
        "percent_take_again": getattr(professor, "percent_take_again", None),
        "level_of_difficulty": getattr(professor, "level_of_difficulty", None),
        "tags_json": json.dumps(tags or []),
        "rating_distribution_json": json.dumps(rating_distribution or []),
        "source_url": f"https://www.ratemyprofessors.com/professor/{getattr(professor, 'id', '')}",
    }


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS professor_rmp_profiles (
            professor_name TEXT PRIMARY KEY,
            rmp_professor_id TEXT,
            department TEXT,
            school_name TEXT,
            school_id TEXT,
            overall_rating REAL,
            num_ratings INTEGER,
            percent_take_again REAL,
            level_of_difficulty REAL,
            tags_json TEXT,
            rating_distribution_json TEXT,
            source_url TEXT,
            fetched_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS professor_rmp_reviews (
            professor_name TEXT NOT NULL,
            review_hash TEXT NOT NULL,
            review_date TEXT,
            review_text TEXT NOT NULL,
            quality REAL,
            difficulty REAL,
            course_raw TEXT,
            tags_json TEXT,
            details_json TEXT,
            thumbs_up INTEGER,
            thumbs_down INTEGER,
            source_url TEXT,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (professor_name, review_hash)
        );

        CREATE TABLE IF NOT EXISTS professor_sentiment_features (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            professor_name TEXT NOT NULL UNIQUE,
            source TEXT NOT NULL,
            rating REAL,
            difficulty REAL,
            would_take_again_pct REAL,
            review_count INTEGER NOT NULL,
            confidence_weight REAL NOT NULL,
            rating_shrunk REAL NOT NULL,
            rating_score REAL NOT NULL,
            difficulty_score REAL,
            would_take_again_score REAL,
            tag_count INTEGER,
            tag_positive_count INTEGER,
            tag_negative_count INTEGER,
            tag_sentiment_score REAL,
            tag_sentiment_adjustment REAL,
            tag_adjusted_sentiment_score REAL,
            base_sentiment_score REAL NOT NULL,
            confidence_adjusted_sentiment_score REAL NOT NULL,
            llm_sentiment_score REAL,
            llm_sentiment_label TEXT,
            llm_sentiment_summary TEXT,
            llm_sentiment_pros_json TEXT,
            llm_sentiment_cons_json TEXT,
            final_sentiment_score REAL NOT NULL,
            rmp_url TEXT,
            imported_at TEXT NOT NULL
        );
        """
    )


def ensure_review_cache_columns(conn: sqlite3.Connection) -> None:
    existing_columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(review_cache)").fetchall()
    }
    required_columns = {
        "review_date": "TEXT",
        "quality": "REAL",
        "difficulty": "REAL",
        "course_raw": "TEXT",
        "tags_json": "TEXT",
        "details_json": "TEXT",
        "thumbs_up": "INTEGER",
        "thumbs_down": "INTEGER",
    }
    for column_name, column_type in required_columns.items():
        if column_name not in existing_columns:
            conn.execute(f"ALTER TABLE review_cache ADD COLUMN {column_name} {column_type}")


def clamp_text(value: object | None) -> str | None:
    if value is None:
        return None
    cleaned = normalize_space(str(value))
    return cleaned or None


def fetch_reviews_for_professor(
    client: RMPClient,
    professor_id: str,
    max_reviews_per_professor: int,
) -> list[dict[str, object]]:
    ratings = list(client.iter_professor_ratings(professor_id, page_size=100))
    records: list[dict[str, object]] = []

    for rating in ratings:
        comment = clamp_text(getattr(rating, "comment", None))
        if not comment:
            continue

        details = getattr(rating, "details", None)
        if isinstance(details, dict):
            details_json = json.dumps(details)
        else:
            details_json = json.dumps({})

        tags = getattr(rating, "tags", None)
        tags_json = json.dumps(tags or [])

        records.append(
            {
                "review_date": getattr(rating, "date", None).isoformat() if getattr(rating, "date", None) else None,
                "review_text": comment,
                "quality": getattr(rating, "quality", None),
                "difficulty": getattr(rating, "difficulty", None),
                "course_raw": getattr(rating, "course_raw", None),
                "tags_json": tags_json,
                "details_json": details_json,
                "thumbs_up": getattr(rating, "thumbs_up", None),
                "thumbs_down": getattr(rating, "thumbs_down", None),
            }
        )

    if max_reviews_per_professor > 0:
        return records[:max_reviews_per_professor]
    return records


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def upsert_summary_rows(conn: sqlite3.Connection, rows: list[dict[str, object]]) -> None:
    conn.execute("DELETE FROM professor_rmp_profiles")
    conn.executemany(
        """
        INSERT INTO professor_rmp_profiles (
            professor_name,
            rmp_professor_id,
            department,
            school_name,
            school_id,
            overall_rating,
            num_ratings,
            percent_take_again,
            level_of_difficulty,
            tags_json,
            rating_distribution_json,
            source_url,
            fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                row["professor_name"],
                row["rmp_professor_id"],
                row["department"],
                row["school_name"],
                row["school_id"],
                row["overall_rating"],
                row["num_ratings"],
                row["percent_take_again"],
                row["level_of_difficulty"],
                row["tags_json"],
                row["rating_distribution_json"],
                row["source_url"],
                row["fetched_at"],
            )
            for row in rows
        ],
    )


def upsert_sentiment_rows(
    conn: sqlite3.Connection,
    rows: list[dict[str, object]],
) -> None:
    conn.execute("DELETE FROM professor_sentiment_features")
    conn.executemany(
        """
        INSERT INTO professor_sentiment_features (
            professor_name,
            source,
            rating,
            difficulty,
            would_take_again_pct,
            review_count,
            confidence_weight,
            rating_shrunk,
            rating_score,
            difficulty_score,
            would_take_again_score,
            tag_count,
            tag_positive_count,
            tag_negative_count,
            tag_sentiment_score,
            tag_sentiment_adjustment,
            tag_adjusted_sentiment_score,
            base_sentiment_score,
            confidence_adjusted_sentiment_score,
            llm_sentiment_score,
            llm_sentiment_label,
            llm_sentiment_summary,
            llm_sentiment_pros_json,
            llm_sentiment_cons_json,
            final_sentiment_score,
            rmp_url,
            imported_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                row["professor_name"],
                row["source"],
                row["rating"],
                row["difficulty"],
                row["would_take_again_pct"],
                row["review_count"],
                row["confidence_weight"],
                row["rating_shrunk"],
                row["rating_score"],
                row["difficulty_score"],
                row["would_take_again_score"],
                row["tag_count"],
                row["tag_positive_count"],
                row["tag_negative_count"],
                row["tag_sentiment_score"],
                row["tag_sentiment_adjustment"],
                row["tag_adjusted_sentiment_score"],
                row["base_sentiment_score"],
                row["confidence_adjusted_sentiment_score"],
                row["llm_sentiment_score"],
                row["llm_sentiment_label"],
                row["llm_sentiment_summary"],
                row["llm_sentiment_pros_json"],
                row["llm_sentiment_cons_json"],
                row["final_sentiment_score"],
                row["rmp_url"],
                row["imported_at"],
            )
            for row in rows
        ],
    )


def refresh(args: argparse.Namespace) -> None:
    imported_at = utc_now_iso()
    with sqlite3.connect(args.db_path) as main_conn, sqlite3.connect(args.cache_db) as cache_conn:
        main_conn.row_factory = sqlite3.Row
        cache_conn.row_factory = sqlite3.Row
        ensure_schema(main_conn)

        professor_names = fetch_professor_names(main_conn)
        if args.professor_name:
            target = normalize_name(args.professor_name)
            professor_names = [name for name in professor_names if target in normalize_name(name)]
        if args.limit > 0:
            professor_names = professor_names[: args.limit]
        existing_rows = fetch_existing_rows(main_conn)
        existing_by_full, existing_by_last_initial, existing_by_last_name = build_name_indexes(
            list(existing_rows.values())
        )

        cache_conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS crawl_state (
                professor_name TEXT PRIMARY KEY,
                source_url TEXT,
                status TEXT NOT NULL,
                error_message TEXT,
                fetched_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS review_cache (
                professor_name TEXT NOT NULL,
                review_hash TEXT NOT NULL,
                review_text TEXT NOT NULL,
                review_date TEXT,
                quality REAL,
                difficulty REAL,
                course_raw TEXT,
                tags_json TEXT,
                details_json TEXT,
                thumbs_up INTEGER,
                thumbs_down INTEGER,
                source_url TEXT,
                fetched_at TEXT NOT NULL,
                PRIMARY KEY (professor_name, review_hash)
            );
            """
        )
        ensure_review_cache_columns(cache_conn)
        ensure_sentiment_feature_columns(main_conn)

        main_conn.execute("DELETE FROM professor_rmp_profiles")
        main_conn.execute("DELETE FROM professor_rmp_reviews")
        main_conn.execute("DELETE FROM professor_sentiment_features")

        client = RMPClient()
        summary_rows: list[dict[str, object]] = []
        review_rows: list[dict[str, object]] = []
        snippet_rows: list[dict[str, object]] = []
        profile_rows: list[dict[str, object]] = []
        sentiment_rows: list[dict[str, object]] = []
        report_rows: list[dict[str, object]] = []

        try:
            for index, professor_name in enumerate(professor_names, start=1):
                live_professor = resolve_live_professor(client, professor_name, args.school_id)
                if live_professor is None:
                    fallback_row = resolve_existing_row(
                        professor_name,
                        existing_by_full,
                        existing_by_last_initial,
                        existing_by_last_name,
                    )
                    if fallback_row:
                        profile_rows.append(
                            {
                                "professor_name": professor_name,
                                "rmp_professor_id": None,
                                "department": None,
                                "school_name": None,
                                "school_id": None,
                                "overall_rating": fallback_row["rating"],
                                "num_ratings": fallback_row["review_count"],
                                "percent_take_again": fallback_row["would_take_again_pct"],
                                "level_of_difficulty": fallback_row["difficulty"],
                                "tags_json": json.dumps([]),
                                "rating_distribution_json": json.dumps([]),
                                "source_url": fallback_row.get("rmp_url"),
                                "fetched_at": imported_at,
                            }
                        )
                        sentiment_features = {
                            "confidence_weight": float(fallback_row["confidence_weight"]),
                            "rating_shrunk": float(fallback_row["rating_shrunk"]),
                            "rating_score": float(fallback_row["rating_score"]),
                            "difficulty_score": fallback_row["difficulty_score"],
                            "would_take_again_score": fallback_row["would_take_again_score"],
                            "tag_count": int(fallback_row.get("tag_count") or 0),
                            "tag_positive_count": int(fallback_row.get("tag_positive_count") or 0),
                            "tag_negative_count": int(fallback_row.get("tag_negative_count") or 0),
                            "tag_sentiment_score": float(fallback_row.get("tag_sentiment_score") or 0.0),
                            "tag_sentiment_adjustment": float(fallback_row.get("tag_sentiment_adjustment") or 0.0),
                            "tag_adjusted_sentiment_score": float(
                                fallback_row["tag_adjusted_sentiment_score"]
                                if fallback_row.get("tag_adjusted_sentiment_score") is not None
                                else fallback_row["confidence_adjusted_sentiment_score"]
                            ),
                            "base_sentiment_score": float(fallback_row["base_sentiment_score"]),
                            "confidence_adjusted_sentiment_score": float(
                                fallback_row["confidence_adjusted_sentiment_score"]
                            ),
                            "llm_sentiment_score": fallback_row["llm_sentiment_score"],
                            "llm_sentiment_label": fallback_row["llm_sentiment_label"],
                            "llm_sentiment_summary": fallback_row["llm_sentiment_summary"],
                            "llm_sentiment_pros_json": fallback_row["llm_sentiment_pros_json"],
                            "llm_sentiment_cons_json": fallback_row["llm_sentiment_cons_json"],
                            "final_sentiment_score": float(fallback_row["final_sentiment_score"]),
                        }
                        sentiment_rows.append(
                            {
                                "professor_name": professor_name,
                                "source": fallback_row["source"],
                                "rating": fallback_row["rating"],
                                "difficulty": fallback_row["difficulty"],
                                "would_take_again_pct": fallback_row["would_take_again_pct"],
                                "review_count": fallback_row["review_count"],
                                "confidence_weight": sentiment_features["confidence_weight"],
                                "rating_shrunk": sentiment_features["rating_shrunk"],
                                "rating_score": sentiment_features["rating_score"],
                                "difficulty_score": sentiment_features["difficulty_score"],
                                "would_take_again_score": sentiment_features["would_take_again_score"],
                                "tag_count": sentiment_features["tag_count"],
                                "tag_positive_count": sentiment_features["tag_positive_count"],
                                "tag_negative_count": sentiment_features["tag_negative_count"],
                                "tag_sentiment_score": sentiment_features["tag_sentiment_score"],
                                "tag_sentiment_adjustment": sentiment_features["tag_sentiment_adjustment"],
                                "tag_adjusted_sentiment_score": sentiment_features["tag_adjusted_sentiment_score"],
                                "base_sentiment_score": sentiment_features["base_sentiment_score"],
                                "confidence_adjusted_sentiment_score": sentiment_features[
                                    "confidence_adjusted_sentiment_score"
                                ],
                                "llm_sentiment_score": sentiment_features["llm_sentiment_score"],
                                "llm_sentiment_label": sentiment_features["llm_sentiment_label"],
                                "llm_sentiment_summary": sentiment_features["llm_sentiment_summary"],
                                "llm_sentiment_pros_json": sentiment_features["llm_sentiment_pros_json"],
                                "llm_sentiment_cons_json": sentiment_features["llm_sentiment_cons_json"],
                                "final_sentiment_score": sentiment_features["final_sentiment_score"],
                                "rmp_url": fallback_row.get("rmp_url"),
                                "imported_at": imported_at,
                            }
                        )
                        report_rows.append(
                            {
                                "professor_name": professor_name,
                                "status": "fallback_existing",
                                "reported_num_ratings": fallback_row["review_count"],
                                "fetched_review_count": 0,
                                "overall_rating": fallback_row["rating"],
                                "source_url": fallback_row.get("rmp_url"),
                            }
                        )
                    else:
                        report_rows.append(
                            {
                                "professor_name": professor_name,
                                "status": "no_match",
                                "reported_num_ratings": 0,
                                "fetched_review_count": 0,
                                "overall_rating": None,
                                "source_url": None,
                            }
                        )
                    continue

                summary = extract_professor_summary(live_professor)
                review_records = fetch_reviews_for_professor(
                    client,
                    str(summary["rmp_professor_id"]),
                    args.max_reviews_per_professor,
                )

                review_texts = [str(record["review_text"]) for record in review_records if record.get("review_text")]
                llm_payload: dict[str, object] | None = None
                if review_texts and args.sentiment_llm_endpoint:
                    llm_payload = summarize_review_texts(
                        review_texts[: max(1, min(len(review_texts), args.sentiment_llm_max_snippets))],
                        endpoint=args.sentiment_llm_endpoint,
                        model=args.sentiment_llm_model,
                        api_key=args.sentiment_llm_api_key,
                        timeout=args.sentiment_llm_timeout,
                    )

                tag_signal = calculate_tag_signal(review_records)

                features = calculate_sentiment_features(
                    rating=float(summary["overall_rating"] or 0.0),
                    difficulty=float(summary["level_of_difficulty"])
                    if summary["level_of_difficulty"] is not None
                    else None,
                    would_take_again_pct=float(summary["percent_take_again"])
                    if summary["percent_take_again"] is not None
                    else None,
                    num_ratings=int(summary["num_ratings"] or 0),
                    prior_weight=args.prior_weight,
                    prior_rating_mean=args.prior_rating_mean,
                )

                base_sentiment_score = features["confidence_adjusted_sentiment_score"]
                tag_adjusted_sentiment_score = apply_tag_adjustment(
                    base_sentiment_score,
                    float(tag_signal["tag_sentiment_adjustment"]),
                )
                final_sentiment_score = tag_adjusted_sentiment_score
                llm_sentiment_score = None
                llm_sentiment_label = None
                llm_sentiment_summary = None
                llm_sentiment_pros_json = None
                llm_sentiment_cons_json = None
                if llm_payload:
                    llm_sentiment_summary = str(llm_payload.get("summary") or "").strip() or None
                    llm_sentiment_pros_json = json.dumps(llm_payload.get("pros") or [])
                    llm_sentiment_cons_json = json.dumps(llm_payload.get("cons") or [])
                    final_sentiment_score = tag_adjusted_sentiment_score

                profile_rows.append(
                    {
                        **summary,
                        "fetched_at": imported_at,
                    }
                )

                sentiment_rows.append(
                    {
                        "professor_name": summary["professor_name"],
                        "source": "ratemyprofessors_live",
                        "rating": float(summary["overall_rating"]) if summary["overall_rating"] is not None else None,
                        "difficulty": float(summary["level_of_difficulty"]) if summary["level_of_difficulty"] is not None else None,
                        "would_take_again_pct": float(summary["percent_take_again"]) if summary["percent_take_again"] is not None else None,
                        "review_count": int(summary["num_ratings"] or 0),
                        "confidence_weight": features["confidence_weight"],
                        "rating_shrunk": features["rating_shrunk"],
                        "rating_score": features["rating_score"],
                        "difficulty_score": None if features["difficulty_score"] < 0 else features["difficulty_score"],
                        "would_take_again_score": None if features["would_take_again_score"] < 0 else features["would_take_again_score"],
                        "tag_count": tag_signal["tag_count"],
                        "tag_positive_count": tag_signal["tag_positive_count"],
                        "tag_negative_count": tag_signal["tag_negative_count"],
                        "tag_sentiment_score": tag_signal["tag_sentiment_score"],
                        "tag_sentiment_adjustment": tag_signal["tag_sentiment_adjustment"],
                        "tag_adjusted_sentiment_score": tag_adjusted_sentiment_score,
                        "base_sentiment_score": features["base_sentiment_score"],
                        "confidence_adjusted_sentiment_score": base_sentiment_score,
                        "llm_sentiment_score": llm_sentiment_score,
                        "llm_sentiment_label": llm_sentiment_label,
                        "llm_sentiment_summary": llm_sentiment_summary,
                        "llm_sentiment_pros_json": llm_sentiment_pros_json,
                        "llm_sentiment_cons_json": llm_sentiment_cons_json,
                        "final_sentiment_score": final_sentiment_score,
                        "rmp_url": summary["source_url"],
                        "imported_at": imported_at,
                    }
                )

                for record in review_records:
                    review_text = str(record["review_text"])
                    review_hash = hashlib.sha256(
                        json.dumps(
                            {
                                "review_text": review_text,
                                "review_date": record.get("review_date"),
                                "quality": record.get("quality"),
                                "difficulty": record.get("difficulty"),
                                "course_raw": record.get("course_raw"),
                                "tags_json": record.get("tags_json"),
                                "details_json": record.get("details_json"),
                                "thumbs_up": record.get("thumbs_up"),
                                "thumbs_down": record.get("thumbs_down"),
                            },
                            sort_keys=True,
                            default=str,
                        ).encode("utf-8")
                    ).hexdigest()

                    review_row = {
                        "professor_name": summary["professor_name"],
                        "review_hash": review_hash,
                        "review_date": record.get("review_date"),
                        "review_text": review_text,
                        "quality": record.get("quality"),
                        "difficulty": record.get("difficulty"),
                        "course_raw": record.get("course_raw"),
                        "tags_json": record.get("tags_json"),
                        "details_json": record.get("details_json"),
                        "thumbs_up": record.get("thumbs_up"),
                        "thumbs_down": record.get("thumbs_down"),
                        "source_url": summary["source_url"],
                        "fetched_at": imported_at,
                    }
                    review_rows.append(review_row)
                    snippet_rows.append(
                        {
                            "professor_name": summary["professor_name"],
                            "review_text": review_text,
                        }
                    )

                report_rows.append(
                    {
                        "professor_name": summary["professor_name"],
                        "status": "ok",
                        "reported_num_ratings": summary["num_ratings"],
                        "fetched_review_count": len(review_records),
                        "overall_rating": summary["overall_rating"],
                        "source_url": summary["source_url"],
                    }
                )

                print(
                    f"[{index}/{len(professor_names)}] {summary['professor_name']}: "
                    f"rating={summary['overall_rating']}, reviews={len(review_records)}"
                )
        finally:
            client.close()

        upsert_summary_rows(main_conn, profile_rows)
        upsert_sentiment_rows(main_conn, sentiment_rows)
        main_conn.execute("DELETE FROM professor_rmp_reviews")
        main_conn.executemany(
            """
            INSERT INTO professor_rmp_reviews (
                professor_name,
                review_hash,
                review_date,
                review_text,
                quality,
                difficulty,
                course_raw,
                tags_json,
                details_json,
                thumbs_up,
                thumbs_down,
                source_url,
                fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row["professor_name"],
                    row["review_hash"],
                    row["review_date"],
                    row["review_text"],
                    row["quality"],
                    row["difficulty"],
                    row["course_raw"],
                    row["tags_json"],
                    row["details_json"],
                    row["thumbs_up"],
                    row["thumbs_down"],
                    row["source_url"],
                    row["fetched_at"],
                )
                for row in review_rows
            ],
        )
        main_conn.commit()

        cache_conn.execute("DELETE FROM crawl_state")
        cache_conn.execute("DELETE FROM review_cache")
        cache_conn.executemany(
            """
            INSERT INTO crawl_state (
                professor_name, source_url, status, error_message, fetched_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    row["professor_name"],
                    row["source_url"],
                    row["status"],
                    row.get("error_message"),
                    imported_at,
                )
                for row in report_rows
            ],
        )

        cache_conn.executemany(
            """
            INSERT INTO review_cache (
                professor_name,
                review_hash,
                review_text,
                review_date,
                quality,
                difficulty,
                course_raw,
                tags_json,
                details_json,
                thumbs_up,
                thumbs_down,
                source_url,
                fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row["professor_name"],
                    row["review_hash"],
                    row["review_text"],
                    row["review_date"],
                    row["quality"],
                    row["difficulty"],
                    row["course_raw"],
                    row["tags_json"],
                    row["details_json"],
                    row["thumbs_up"],
                    row["thumbs_down"],
                    row["source_url"],
                    row["fetched_at"],
                )
                for row in review_rows
            ],
        )
        cache_conn.commit()

    write_csv(
        args.review_snippets_csv,
        ["professor_name", "review_text"],
        snippet_rows,
    )
    write_csv(
        args.review_records_csv,
        [
            "professor_name",
            "review_hash",
            "review_date",
            "review_text",
            "quality",
            "difficulty",
            "course_raw",
            "tags_json",
            "details_json",
            "thumbs_up",
            "thumbs_down",
            "source_url",
            "fetched_at",
        ],
        review_rows,
    )
    write_csv(
        args.summary_csv,
        [
            "professor_name",
            "rmp_professor_id",
            "department",
            "school_name",
            "school_id",
            "overall_rating",
            "num_ratings",
            "percent_take_again",
            "level_of_difficulty",
            "tags_json",
            "rating_distribution_json",
            "source_url",
            "fetched_at",
        ],
        profile_rows,
    )
    write_csv(
        args.report_csv,
        [
            "professor_name",
            "status",
            "reported_num_ratings",
            "fetched_review_count",
            "overall_rating",
            "source_url",
        ],
        report_rows,
    )

    print(
        "Refresh complete: "
        f"professors={len(profile_rows)}, reviews={len(review_rows)}, db={args.db_path}, cache={args.cache_db}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refresh the local professor RMP data from ratemyprofessors-client."
    )
    parser.add_argument("--db-path", type=Path, default=get_database_path())
    parser.add_argument(
        "--cache-db",
        type=Path,
        default=PROJECT_ROOT / "data" / "seed" / "professor_review_cache.db",
    )
    parser.add_argument(
        "--review-snippets-csv",
        type=Path,
        default=PROJECT_ROOT / "data" / "seed" / "professor_review_snippets.csv",
    )
    parser.add_argument(
        "--review-records-csv",
        type=Path,
        default=PROJECT_ROOT / "data" / "processed" / "professor_review_records.csv",
    )
    parser.add_argument(
        "--summary-csv",
        type=Path,
        default=PROJECT_ROOT / "data" / "processed" / "professor_rmp_profiles.csv",
    )
    parser.add_argument(
        "--report-csv",
        type=Path,
        default=PROJECT_ROOT / "data" / "processed" / "professor_rmp_refresh_report.csv",
    )
    parser.add_argument("--school-id", type=str, default="880")
    parser.add_argument(
        "--professor-name",
        type=str,
        default=None,
        help="Optional professor name filter for testing a subset of the database",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional limit on the number of professors to refresh",
    )
    parser.add_argument("--max-reviews-per-professor", type=int, default=0)
    parser.add_argument("--prior-weight", type=int, default=10)
    parser.add_argument("--prior-rating-mean", type=float, default=3.8)
    parser.add_argument(
        "--sentiment-llm-endpoint",
        type=str,
        default=None,
    )
    parser.add_argument("--sentiment-llm-model", type=str, default="llama3.1")
    parser.add_argument("--sentiment-llm-api-key", type=str, default=None)
    parser.add_argument("--sentiment-llm-timeout", type=int, default=30)
    parser.add_argument("--sentiment-llm-max-snippets", type=int, default=8)
    parser.add_argument("--sentiment-llm-weight", type=float, default=0.35)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    refresh(args)


if __name__ == "__main__":
    main()