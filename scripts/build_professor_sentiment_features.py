#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
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
from app.services.llama_sentiment_service import analyze_review_texts
from app.services.rmp_service import fetch_professor_rating


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


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


def candidate_queries(professor_name: str) -> list[str]:
    name = professor_name.strip()
    if not name:
        return []

    parts = [part for part in name.split() if part]
    queries: list[str] = [name]
    if len(parts) >= 2:
        queries.append(f"{parts[0]} {parts[-1]}")
        queries.append(parts[-1])

    deduped: list[str] = []
    seen: set[str] = set()
    for query in queries:
        key = query.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(query)
    return deduped


def load_seed_rows(path: Path | None) -> list[dict[str, object]]:
    if path is None or not path.exists():
        return []

    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            name = (raw.get("professor_name") or "").strip()
            rating = (raw.get("rating") or "").strip()
            num_ratings = (raw.get("num_ratings") or "").strip()
            if not name or not rating or not num_ratings:
                continue

            difficulty = (raw.get("difficulty") or "").strip()
            would_take_again_pct = (raw.get("would_take_again_pct") or "").strip()
            rmp_url = (raw.get("rmp_url") or "").strip() or None

            rows.append(
                {
                    "professor_name": name,
                    "rating": float(rating),
                    "difficulty": float(difficulty) if difficulty else None,
                    "would_take_again_pct": float(would_take_again_pct)
                    if would_take_again_pct
                    else None,
                    "num_ratings": int(num_ratings),
                    "rmp_url": rmp_url,
                }
            )
    return rows


def load_review_rows(path: Path | None) -> list[dict[str, str]]:
    if path is None or not path.exists():
        return []

    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            name = (raw.get("professor_name") or "").strip()
            review_text = (raw.get("review_text") or raw.get("review_snippet") or "").strip()
            if not name or not review_text:
                continue
            rows.append({"professor_name": name, "review_text": review_text})
    return rows


def build_seed_indexes(
    rows: list[dict[str, object]],
) -> tuple[dict[str, dict[str, object]], dict[str, list[dict[str, object]]], dict[str, list[dict[str, object]]]]:
    by_full: dict[str, dict[str, object]] = {}
    by_last_initial: dict[str, list[dict[str, object]]] = {}
    by_last_name: dict[str, list[dict[str, object]]] = {}

    for row in rows:
        name = row.get("professor_name")
        full_key = normalize_name(str(name))
        if full_key and full_key not in by_full:
            by_full[full_key] = row

        last_initial = last_name_first_initial_key(str(name))
        if last_initial:
            by_last_initial.setdefault(last_initial, []).append(row)

        last_key = last_name_key(str(name))
        if last_key:
            by_last_name.setdefault(last_key, []).append(row)

    return by_full, by_last_initial, by_last_name


def build_review_indexes(
    rows: list[dict[str, str]],
) -> tuple[dict[str, list[str]], dict[str, list[str]], dict[str, list[str]]]:
    by_full: dict[str, list[str]] = {}
    by_last_initial: dict[str, list[str]] = {}
    by_last_name: dict[str, list[str]] = {}

    for row in rows:
        name = row.get("professor_name")
        review_text = row.get("review_text")
        if not name or not review_text:
            continue

        full_key = normalize_name(name)
        if full_key:
            by_full.setdefault(full_key, []).append(review_text)

        last_initial = last_name_first_initial_key(name)
        if last_initial:
            by_last_initial.setdefault(last_initial, []).append(review_text)

        last_key = last_name_key(name)
        if last_key:
            by_last_name.setdefault(last_key, []).append(review_text)

    return by_full, by_last_initial, by_last_name


def resolve_seed_row(
    professor_name: str,
    by_full: dict[str, dict[str, object]],
    by_last_initial: dict[str, list[dict[str, object]]],
    by_last_name: dict[str, list[dict[str, object]]],
) -> tuple[dict[str, object] | None, str]:
    full_key = normalize_name(professor_name)
    if full_key and full_key in by_full:
        return by_full[full_key], "full_name"

    last_initial = last_name_first_initial_key(professor_name)
    if last_initial:
        matches = by_last_initial.get(last_initial, [])
        if len(matches) == 1:
            return matches[0], "last_name_first_initial"

    last_key = last_name_key(professor_name)
    if last_key:
        matches = by_last_name.get(last_key, [])
        if len(matches) == 1:
            return matches[0], "last_name_unique"

    return None, ""


def resolve_review_texts(
    professor_name: str,
    by_full: dict[str, list[str]],
    by_last_initial: dict[str, list[str]],
    by_last_name: dict[str, list[str]],
) -> tuple[list[str], str]:
    full_key = normalize_name(professor_name)
    if full_key and full_key in by_full:
        return by_full[full_key], "full_name"

    last_initial = last_name_first_initial_key(professor_name)
    if last_initial:
        matches = by_last_initial.get(last_initial, [])
        if matches:
            return matches, "last_name_first_initial"

    last_key = last_name_key(professor_name)
    if last_key:
        matches = by_last_name.get(last_key, [])
        if matches:
            return matches, "last_name_unique"

    return [], ""


def build_db_row(
    *,
    professor_name: str,
    imported_at: str,
    prior_weight: int,
    prior_rating_mean: float,
    rating_payload: dict[str, object] | None,
    llm_payload: dict[str, object] | None,
    llm_weight: float,
    source: str | None,
) -> tuple[dict[str, object], str]:
    llm_sentiment_score: float | None = None
    llm_sentiment_label: str | None = None
    llm_sentiment_summary: str | None = None
    llm_sentiment_pros_json: str | None = None
    llm_sentiment_cons_json: str | None = None

    if llm_payload:
        try:
            llm_sentiment_score = float(llm_payload.get("sentiment_score"))
        except (TypeError, ValueError):
            llm_sentiment_score = None
        if llm_sentiment_score is not None:
            llm_sentiment_score = clamp(llm_sentiment_score, 0.0, 1.0)
            llm_sentiment_label = str(llm_payload.get("sentiment_label") or "").strip() or None
            llm_sentiment_summary = str(llm_payload.get("summary") or "").strip() or None
            llm_sentiment_pros_json = json.dumps(llm_payload.get("pros") or [])
            llm_sentiment_cons_json = json.dumps(llm_payload.get("cons") or [])

    if rating_payload:
        rating = rating_payload.get("rating")
        review_count = rating_payload.get("num_ratings")
        if rating is not None and review_count is not None:
            difficulty = rating_payload.get("difficulty")
            would_take_again_pct = rating_payload.get("would_take_again_pct")
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
            base_sentiment_score = features["confidence_adjusted_sentiment_score"]
            final_sentiment_score = base_sentiment_score
            if llm_sentiment_score is not None:
                final_sentiment_score = (
                    (1.0 - llm_weight) * base_sentiment_score + llm_weight * llm_sentiment_score
                )
            row = {
                "professor_name": professor_name,
                "source": source or "ratemyprofessors",
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
                "confidence_adjusted_sentiment_score": base_sentiment_score,
                "llm_sentiment_score": llm_sentiment_score,
                "llm_sentiment_label": llm_sentiment_label,
                "llm_sentiment_summary": llm_sentiment_summary,
                "llm_sentiment_pros_json": llm_sentiment_pros_json,
                "llm_sentiment_cons_json": llm_sentiment_cons_json,
                "final_sentiment_score": final_sentiment_score,
                "rmp_url": rating_payload.get("rmp_url"),
                "imported_at": imported_at,
            }
            return row, "matched"

    fallback_features = calculate_sentiment_features(
        rating=prior_rating_mean,
        difficulty=None,
        would_take_again_pct=None,
        num_ratings=0,
        prior_weight=prior_weight,
        prior_rating_mean=prior_rating_mean,
    )
    base_sentiment_score = fallback_features["confidence_adjusted_sentiment_score"]
    final_sentiment_score = base_sentiment_score
    if llm_sentiment_score is not None:
        final_sentiment_score = (
            (1.0 - llm_weight) * base_sentiment_score + llm_weight * llm_sentiment_score
        )

    row = {
        "professor_name": professor_name,
        "source": "llm_review_only" if llm_sentiment_score is not None else "prior_only",
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
        "confidence_adjusted_sentiment_score": base_sentiment_score,
        "llm_sentiment_score": llm_sentiment_score,
        "llm_sentiment_label": llm_sentiment_label,
        "llm_sentiment_summary": llm_sentiment_summary,
        "llm_sentiment_pros_json": llm_sentiment_pros_json,
        "llm_sentiment_cons_json": llm_sentiment_cons_json,
        "final_sentiment_score": final_sentiment_score,
        "rmp_url": None,
        "imported_at": imported_at,
    }
    return row, "fallback_llm_review_only" if llm_sentiment_score is not None else "fallback_prior_only"


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
        "llm_sentiment_score",
        "llm_sentiment_label",
        "llm_sentiment_summary",
        "llm_sentiment_pros_json",
        "llm_sentiment_cons_json",
        "final_sentiment_score",
        "rmp_url",
        "imported_at",
    ]

    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_diagnostics_csv(output_path: Path, rows: list[dict[str, object]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "professor_name",
        "attempted_queries",
        "matched_query",
        "match_key",
        "review_match_key",
        "llm_status",
        "result",
        "source",
        "rating",
        "review_count",
        "rmp_url",
    ]

    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    default_db = get_database_path()
    default_csv = PROJECT_ROOT / "data" / "processed" / "professor_sentiment_features.csv"
    default_seed_csv = PROJECT_ROOT / "data" / "seed" / "professor_sentiment_seed.csv"
    default_review_csv = PROJECT_ROOT / "data" / "seed" / "professor_review_snippets.csv"
    default_diagnostics_csv = (
        PROJECT_ROOT / "data" / "processed" / "professor_sentiment_diagnostics.csv"
    )

    parser = argparse.ArgumentParser(
        description="Build professor sentiment features and store them in SQLite + optional CSV."
    )
    parser.add_argument("--db-path", type=Path, default=default_db)
    parser.add_argument("--export-csv", type=Path, default=default_csv)
    parser.add_argument("--seed-csv", type=Path, default=default_seed_csv)
    parser.add_argument("--review-text-csv", type=Path, default=default_review_csv)
    parser.add_argument("--diagnostics-csv", type=Path, default=default_diagnostics_csv)
    parser.add_argument("--prior-weight", type=int, default=10)
    parser.add_argument("--prior-rating-mean", type=float, default=3.8)
    parser.add_argument(
        "--sentiment-llm-endpoint",
        type=str,
        default="http://localhost:11434/v1/chat/completions",
        help="Local Ollama or compatible HTTP endpoint for optional Llama sentiment analysis",
    )
    parser.add_argument(
        "--sentiment-llm-model",
        type=str,
        default="llama3.1",
        help="Model name to send to the sentiment LLM runtime",
    )
    parser.add_argument(
        "--sentiment-llm-api-key",
        type=str,
        default=None,
        help="Optional bearer token for the sentiment LLM endpoint if it needs one",
    )
    parser.add_argument(
        "--sentiment-llm-timeout",
        type=int,
        default=30,
        help="Timeout in seconds for the Llama request",
    )
    parser.add_argument(
        "--sentiment-llm-max-snippets",
        type=int,
        default=8,
        help="Maximum review snippets to send to Llama per professor",
    )
    parser.add_argument(
        "--sentiment-llm-weight",
        type=float,
        default=0.35,
        help="Blend weight for the Llama sentiment score when available",
    )
    args = parser.parse_args()

    imported_at = datetime.now(timezone.utc).isoformat()
    seed_rows = load_seed_rows(args.seed_csv)
    seed_by_full, seed_by_last_initial, seed_by_last_name = build_seed_indexes(seed_rows)
    review_rows = load_review_rows(args.review_text_csv)
    review_by_full, review_by_last_initial, review_by_last_name = build_review_indexes(review_rows)

    sentiment_llm_endpoint = args.sentiment_llm_endpoint or None

    with sqlite3.connect(args.db_path) as conn:
        init_schema(conn)
        professor_names = fetch_professor_names(conn)

        inserted_rows: list[dict[str, object]] = []
        diagnostics_rows: list[dict[str, object]] = []
        matched = 0
        matched_live = 0
        matched_seed = 0
        fallback = 0
        llm_enriched = 0

        for professor_name in professor_names:
            matched_query = ""
            match_key = ""
            review_match_key = ""
            llm_status = "disabled"
            rating_payload: dict[str, object] | None = None
            source = None
            queries = candidate_queries(professor_name)

            review_texts, review_match_key = resolve_review_texts(
                professor_name,
                review_by_full,
                review_by_last_initial,
                review_by_last_name,
            )

            for query in queries:
                candidate_rmp = fetch_professor_rating(query)
                if candidate_rmp:
                    rating_payload = candidate_rmp
                    source = "ratemyprofessors_live"
                    matched_query = query
                    match_key = "query"
                    break

            if rating_payload is None and seed_rows:
                seed_row, seed_key = resolve_seed_row(
                    professor_name,
                    seed_by_full,
                    seed_by_last_initial,
                    seed_by_last_name,
                )
                if seed_row:
                    rating_payload = seed_row
                    source = "seed_dataset"
                    match_key = seed_key

            llm_payload: dict[str, object] | None = None
            if review_texts and sentiment_llm_endpoint:
                snippet_count = max(1, min(len(review_texts), args.sentiment_llm_max_snippets))
                llm_payload = analyze_review_texts(
                    review_texts[:snippet_count],
                    endpoint=sentiment_llm_endpoint,
                    model=args.sentiment_llm_model,
                    api_key=args.sentiment_llm_api_key,
                    timeout=args.sentiment_llm_timeout,
                )
                if llm_payload:
                    llm_status = "used"
                    llm_enriched += 1
                else:
                    llm_status = "failed"
            elif review_texts:
                llm_status = "available_but_disabled"

            db_row, result = build_db_row(
                professor_name=professor_name,
                imported_at=imported_at,
                prior_weight=args.prior_weight,
                prior_rating_mean=args.prior_rating_mean,
                rating_payload=rating_payload,
                llm_payload=llm_payload,
                llm_weight=args.sentiment_llm_weight,
                source=source,
            )

            if db_row["source"] not in {"prior_only", "llm_review_only"}:
                matched += 1
                if db_row["source"] == "ratemyprofessors_live":
                    matched_live += 1
                elif db_row["source"] == "seed_dataset":
                    matched_seed += 1
            else:
                fallback += 1

            diagnostics_rows.append(
                {
                    "professor_name": professor_name,
                    "attempted_queries": " | ".join(queries),
                    "matched_query": matched_query,
                    "match_key": match_key,
                    "review_match_key": review_match_key,
                    "llm_status": llm_status,
                    "result": result,
                    "source": db_row["source"],
                    "rating": db_row["rating"],
                    "review_count": db_row["review_count"],
                    "rmp_url": db_row["rmp_url"],
                }
            )

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

    if args.export_csv:
        write_csv(args.export_csv, inserted_rows)
    if args.diagnostics_csv:
        write_diagnostics_csv(args.diagnostics_csv, diagnostics_rows)

    print(
        "Built professor_sentiment_features: "
        f"candidates={len(professor_names)}, inserted={len(inserted_rows)}, "
        f"matched={matched}, matched_live={matched_live}, matched_seed={matched_seed}, "
        f"fallback={fallback}, llm_enriched={llm_enriched}, "
        f"db={args.db_path}"
    )
    if args.export_csv:
        print(f"CSV export: {args.export_csv}")
    if args.diagnostics_csv:
        print(f"Diagnostics export: {args.diagnostics_csv}")


if __name__ == "__main__":
    main()