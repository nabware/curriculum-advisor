#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.core.database import get_database_path
from app.services.llama_sentiment_service import score_summary_text


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


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


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
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
        )
        """
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Regenerate professor sentiment scores from stored AI summaries."
    )
    parser.add_argument("--db-path", type=Path, default=get_database_path())
    parser.add_argument("--professor-name", type=str, default=None, help="Optional professor name substring filter")
    parser.add_argument("--limit", type=int, default=0, help="Optional max number of professors to update")
    parser.add_argument(
        "--sentiment-llm-endpoint",
        type=str,
        default="http://localhost:11434/v1/chat/completions",
        help="Local Ollama or compatible HTTP endpoint",
    )
    parser.add_argument("--sentiment-llm-model", type=str, default="llama3.1")
    parser.add_argument("--sentiment-llm-api-key", type=str, default=None)
    parser.add_argument("--sentiment-llm-timeout", type=int, default=30)
    parser.add_argument("--sentiment-llm-weight", type=float, default=0.35)
    args = parser.parse_args()

    imported_at = datetime.now(timezone.utc).isoformat()

    with sqlite3.connect(args.db_path) as conn:
        conn.row_factory = sqlite3.Row
        ensure_schema(conn)
        ensure_sentiment_feature_columns(conn)

        rows = conn.execute(
            """
            SELECT
                professor_name,
                rating,
                difficulty,
                would_take_again_pct,
                review_count,
                tag_count,
                tag_positive_count,
                tag_negative_count,
                tag_sentiment_score,
                tag_sentiment_adjustment,
                tag_adjusted_sentiment_score,
                base_sentiment_score,
                confidence_adjusted_sentiment_score,
                llm_sentiment_summary,
                final_sentiment_score
            FROM professor_sentiment_features
            ORDER BY professor_name
            """
        ).fetchall()

        if args.professor_name:
            needle = args.professor_name.strip().lower()
            rows = [row for row in rows if needle in str(row["professor_name"] or "").lower()]
        if args.limit > 0:
            rows = rows[: args.limit]

        updated_rows = 0
        for row in rows:
            professor_name = str(row["professor_name"] or "").strip()
            summary = str(row["llm_sentiment_summary"] or "").strip()
            if not professor_name or not summary:
                continue

            score_payload = score_summary_text(
                summary,
                rating=float(row["rating"] or 0.0),
                difficulty=float(row["difficulty"]) if row["difficulty"] is not None else None,
                would_take_again_pct=float(row["would_take_again_pct"]) if row["would_take_again_pct"] is not None else None,
                review_count=int(row["review_count"] or 0),
                endpoint=args.sentiment_llm_endpoint,
                model=args.sentiment_llm_model,
                api_key=args.sentiment_llm_api_key,
                timeout=args.sentiment_llm_timeout,
            )
            if not score_payload:
                continue

            llm_sentiment_score = clamp(float(score_payload["sentiment_score"]), 0.0, 1.0)
            llm_sentiment_label = str(score_payload["sentiment_label"])
            tag_adjusted_base = row["tag_adjusted_sentiment_score"]
            if tag_adjusted_base is None:
                tag_adjusted_base = row["confidence_adjusted_sentiment_score"]
            if tag_adjusted_base is None:
                tag_adjusted_base = row["base_sentiment_score"]
            base_sentiment_score = float(tag_adjusted_base if tag_adjusted_base is not None else 0.0)
            final_sentiment_score = (
                (1.0 - args.sentiment_llm_weight) * base_sentiment_score
                + args.sentiment_llm_weight * llm_sentiment_score
            )
            conn.execute(
                """
                UPDATE professor_sentiment_features
                SET llm_sentiment_score = ?,
                    llm_sentiment_label = ?,
                    final_sentiment_score = ?,
                    imported_at = ?
                WHERE professor_name = ?
                """,
                (
                    llm_sentiment_score,
                    llm_sentiment_label,
                    final_sentiment_score,
                    imported_at,
                    professor_name,
                ),
            )
            updated_rows += 1

        conn.commit()

    print(
        "Updated professor_sentiment_features scores: "
        f"candidates={len(rows)}, updated={updated_rows}, db={args.db_path}"
    )


if __name__ == "__main__":
    main()
