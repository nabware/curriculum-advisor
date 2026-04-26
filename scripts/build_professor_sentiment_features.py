#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.core.database import get_database_path
from app.services.rmp_service import fetch_professor_rating


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


def build_db_row(
    *,
    professor_name: str,
    imported_at: str,
    prior_weight: int,
    prior_rating_mean: float,
    rmp: dict | None,
) -> dict[str, object] | None:
    if rmp:
        rating = rmp.get("rating")
        review_count = rmp.get("num_ratings")
        if rating is not None and review_count:
            difficulty = rmp.get("difficulty")
            would_take_again_pct = rmp.get("would_take_again_pct")
            features = calculate_sentiment_features(
                rating=float(rating),
                difficulty=float(difficulty) if difficulty is not None else None,
                would_take_again_pct=float(would_take_again_pct)
                if would_take_again_pct is not None
                else None,
                num_ratings=int(review_count),
                prior_weight=prior_weight,
                prior_rating_mean=prior_rating_mean,
            )
            return {
                "professor_name": professor_name,
                "source": "ratemyprofessors",
                "rating": float(rating),
                "difficulty": float(difficulty) if difficulty is not None else None,
                "would_take_again_pct": float(would_take_again_pct)
                if would_take_again_pct is not None
                else None,
                "review_count": int(review_count),
                "confidence_weight": features["confidence_weight"],
                "rating_shrunk": features["rating_shrunk"],
                "rating_score": features["rating_score"],
                "difficulty_score": None
                if features["difficulty_score"] < 0
                else features["difficulty_score"],
                "would_take_again_score": None
                if features["would_take_again_score"] < 0
                else features["would_take_again_score"],
                "base_sentiment_score": features["base_sentiment_score"],
                "confidence_adjusted_sentiment_score": features[
                    "confidence_adjusted_sentiment_score"
                ],
                "rmp_url": rmp.get("rmp_url"),
                "imported_at": imported_at,
            }

    fallback_features = calculate_sentiment_features(
        rating=prior_rating_mean,
        difficulty=None,
        would_take_again_pct=None,
        num_ratings=0,
        prior_weight=prior_weight,
        prior_rating_mean=prior_rating_mean,
    )
    return {
        "professor_name": professor_name,
        "source": "prior_only",
        "rating": None,
        "difficulty": None,
        "would_take_again_pct": None,
        "review_count": 0,
        "confidence_weight": fallback_features["confidence_weight"],
        "rating_shrunk": fallback_features["rating_shrunk"],
        "rating_score": fallback_features["rating_score"],
        "difficulty_score": None,
        "would_take_again_score": None,
        "base_sentiment_score": fallback_features["base_sentiment_score"],
        "confidence_adjusted_sentiment_score": fallback_features[
            "confidence_adjusted_sentiment_score"
        ],
        "rmp_url": None,
        "imported_at": imported_at,
    }


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS professor_sentiment_features;

        CREATE TABLE professor_sentiment_features (
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
            rmp_url TEXT,
            imported_at TEXT NOT NULL
        );
        """
    )


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


def write_csv(output_path: Path, rows: list[dict[str, object]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "professor_name",
        "source",
        "rating",
        "difficulty",
        "would_take_again_pct",
        "review_count",
        "confidence_weight",
        "rating_shrunk",
        "rating_score",
        "difficulty_score",
        "would_take_again_score",
        "base_sentiment_score",
        "confidence_adjusted_sentiment_score",
        "rmp_url",
        "imported_at",
    ]

    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    default_db = get_database_path()
    default_csv = PROJECT_ROOT / "data" / "processed" / "professor_sentiment_features.csv"

    parser = argparse.ArgumentParser(
        description="Build professor sentiment features and store them in SQLite + optional CSV."
    )
    parser.add_argument("--db-path", type=Path, default=default_db)
    parser.add_argument("--export-csv", type=Path, default=default_csv)
    parser.add_argument("--prior-weight", type=int, default=10)
    parser.add_argument("--prior-rating-mean", type=float, default=3.8)
    args = parser.parse_args()

    imported_at = datetime.now(timezone.utc).isoformat()

    with sqlite3.connect(args.db_path) as conn:
        init_schema(conn)
        professor_names = fetch_professor_names(conn)

        inserted_rows: list[dict[str, object]] = []
        matched = 0
        fallback = 0

        for professor_name in professor_names:
            rmp = fetch_professor_rating(professor_name)
            db_row = build_db_row(
                professor_name=professor_name,
                imported_at=imported_at,
                prior_weight=args.prior_weight,
                prior_rating_mean=args.prior_rating_mean,
                rmp=rmp,
            )
            if db_row is None:
                continue

            if db_row["source"] == "ratemyprofessors":
                matched += 1
            else:
                fallback += 1

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
                    rmp_url,
                    imported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    db_row["rmp_url"],
                    db_row["imported_at"],
                ),
            )

            inserted_rows.append(db_row)

        conn.commit()

    if args.export_csv:
        write_csv(args.export_csv, inserted_rows)

    print(
        "Built professor_sentiment_features: "
        f"candidates={len(professor_names)}, inserted={len(inserted_rows)}, "
        f"matched={matched}, fallback={fallback}, "
        f"db={args.db_path}"
    )
    if args.export_csv:
        print(f"CSV export: {args.export_csv}")


if __name__ == "__main__":
    main()