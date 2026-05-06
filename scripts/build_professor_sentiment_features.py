#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.core.database import get_database_path
from app.services.llama_sentiment_service import summarize_review_texts


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


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

    weighted_sum = 0.60 * rating_score
    weighted_total = 0.60

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


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
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


def fetch_professor_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
            p.professor_name,
            p.overall_rating,
            p.num_ratings,
            p.percent_take_again,
            p.level_of_difficulty,
            p.source_url
        FROM professor_rmp_profiles p
        ORDER BY p.professor_name
        """
    ).fetchall()


def fetch_review_texts(conn: sqlite3.Connection, professor_name: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT review_text
        FROM professor_rmp_reviews
        WHERE professor_name = ?
          AND review_text IS NOT NULL
          AND TRIM(review_text) != ''
        ORDER BY fetched_at DESC, review_hash
        """,
        (professor_name,),
    ).fetchall()
    return [str(row[0]).strip() for row in rows if row[0] and str(row[0]).strip()]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build professor sentiment features directly from professor_rmp_reviews and store them in SQLite."
    )
    parser.add_argument("--db-path", type=Path, default=get_database_path())
    parser.add_argument("--professor-name", type=str, default=None, help="Optional professor name substring filter")
    parser.add_argument("--limit", type=int, default=0, help="Optional max number of professors to rebuild")
    parser.add_argument("--prior-weight", type=int, default=10)
    parser.add_argument("--prior-rating-mean", type=float, default=3.8)
    parser.add_argument(
        "--sentiment-llm-endpoint",
        type=str,
        default="http://localhost:11434/v1/chat/completions",
        help="Local Ollama or compatible HTTP endpoint",
    )
    parser.add_argument("--sentiment-llm-model", type=str, default="llama3.1")
    parser.add_argument("--sentiment-llm-api-key", type=str, default=None)
    parser.add_argument("--sentiment-llm-timeout", type=int, default=30)
    parser.add_argument("--sentiment-llm-max-snippets", type=int, default=8)
    parser.add_argument("--sentiment-llm-weight", type=float, default=0.35)
    args = parser.parse_args()

    imported_at = datetime.now(timezone.utc).isoformat()
    sentiment_llm_endpoint = args.sentiment_llm_endpoint or None

    with sqlite3.connect(args.db_path) as conn:
        conn.row_factory = sqlite3.Row
        ensure_schema(conn)

        professor_rows = fetch_professor_rows(conn)
        if args.professor_name:
            needle = args.professor_name.strip().lower()
            professor_rows = [row for row in professor_rows if needle in str(row["professor_name"] or "").lower()]
        if args.limit > 0:
            professor_rows = professor_rows[: args.limit]

        conn.execute("DELETE FROM professor_sentiment_features")

        inserted_rows: list[dict[str, object]] = []
        llm_summarized = 0

        for row in professor_rows:
            professor_name = str(row["professor_name"] or "").strip()
            if not professor_name:
                continue

            review_texts = fetch_review_texts(conn, professor_name)
            llm_payload: dict[str, object] | None = None
            if review_texts and sentiment_llm_endpoint:
                snippet_count = max(1, min(len(review_texts), args.sentiment_llm_max_snippets))
                llm_payload = summarize_review_texts(
                    review_texts[:snippet_count],
                    endpoint=sentiment_llm_endpoint,
                    model=args.sentiment_llm_model,
                    api_key=args.sentiment_llm_api_key,
                    timeout=args.sentiment_llm_timeout,
                )
                if llm_payload:
                    llm_summarized += 1

            features = calculate_sentiment_features(
                rating=float(row["overall_rating"] or 0.0),
                difficulty=float(row["level_of_difficulty"]) if row["level_of_difficulty"] is not None else None,
                would_take_again_pct=float(row["percent_take_again"]) if row["percent_take_again"] is not None else None,
                num_ratings=int(row["num_ratings"] or 0),
                prior_weight=args.prior_weight,
                prior_rating_mean=args.prior_rating_mean,
            )

            base_sentiment_score = features["confidence_adjusted_sentiment_score"]
            final_sentiment_score = base_sentiment_score
            llm_sentiment_score = None
            llm_sentiment_label = None
            llm_sentiment_summary = None
            llm_sentiment_pros_json = None
            llm_sentiment_cons_json = None

            if llm_payload:
                llm_sentiment_summary = str(llm_payload.get("summary") or "").strip() or None
                llm_sentiment_pros_json = json.dumps(llm_payload.get("pros") or [])
                llm_sentiment_cons_json = json.dumps(llm_payload.get("cons") or [])
                final_sentiment_score = base_sentiment_score

            db_row = {
                "professor_name": professor_name,
                "source": "ratemyprofessors_live",
                "rating": row["overall_rating"],
                "difficulty": row["level_of_difficulty"],
                "would_take_again_pct": row["percent_take_again"],
                "review_count": int(row["num_ratings"] or 0),
                "confidence_weight": features["confidence_weight"],
                "rating_shrunk": features["rating_shrunk"],
                "rating_score": features["rating_score"],
                "difficulty_score": None if features["difficulty_score"] < 0 else features["difficulty_score"],
                "would_take_again_score": None if features["would_take_again_score"] < 0 else features["would_take_again_score"],
                "base_sentiment_score": features["base_sentiment_score"],
                "confidence_adjusted_sentiment_score": base_sentiment_score,
                "llm_sentiment_score": llm_sentiment_score,
                "llm_sentiment_label": llm_sentiment_label,
                "llm_sentiment_summary": llm_sentiment_summary,
                "llm_sentiment_pros_json": llm_sentiment_pros_json,
                "llm_sentiment_cons_json": llm_sentiment_cons_json,
                "final_sentiment_score": final_sentiment_score,
                "rmp_url": row["source_url"],
                "imported_at": imported_at,
            }

            conn.execute(
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
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    db_row["professor_name"],
                    db_row["source"],
                    db_row["rating"],
                    db_row["difficulty"],
                    db_row["would_take_again_pct"],
                    db_row["review_count"],
                    db_row["confidence_weight"],
                    db_row["rating_shrunk"],
                    db_row["rating_score"],
                    db_row["difficulty_score"],
                    db_row["would_take_again_score"],
                    db_row["base_sentiment_score"],
                    db_row["confidence_adjusted_sentiment_score"],
                    db_row["llm_sentiment_score"],
                    db_row["llm_sentiment_label"],
                    db_row["llm_sentiment_summary"],
                    db_row["llm_sentiment_pros_json"],
                    db_row["llm_sentiment_cons_json"],
                    db_row["final_sentiment_score"],
                    db_row["rmp_url"],
                    db_row["imported_at"],
                ),
            )
            inserted_rows.append(db_row)

        conn.commit()

    print(
        "Built professor_sentiment_features: "
        f"candidates={len(professor_rows)}, inserted={len(inserted_rows)}, "
        f"llm_summarized={llm_summarized}, db={args.db_path}"
    )


if __name__ == "__main__":
    main()