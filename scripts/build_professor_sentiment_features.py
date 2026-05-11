from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR  = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.core.database import get_database_path
from app.services.llama_sentiment_service import summarize_review_texts
from app.services.sentiment_pipeline import (
    compute_sentiment_trend,
    compute_tag_sentiment_breakdown,
    compute_course_specific_sentiment,
    compute_confidence_interval,
    extract_structured_sentiment,
    verify_sentiment_claims,
    detect_sentiment_anomaly,
    needs_rebuild,
    ensure_extended_schema,
    fetch_new_reviews_since,
)

def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def calculate_sentiment_features(
    rating: float,
    difficulty: float | None,
    would_take_again_pct: float | None,
    num_ratings: int,
    *,
    prior_weight: int = 10,
    prior_rating_mean: float = 3.8,
) -> dict:
    review_count      = max(0, int(num_ratings))
    confidence_weight = review_count / (review_count + prior_weight) if review_count > 0 else 0.0

    rating_clamped = clamp(float(rating), 0.0, 5.0)
    rating_shrunk  = (
        (review_count * rating_clamped + prior_weight * prior_rating_mean)
        / (review_count + prior_weight)
        if review_count > 0
        else prior_rating_mean
    )
    rating_score = rating_shrunk / 5.0

    difficulty_score: float | None = None
    if difficulty is not None:
        difficulty_clamped = clamp(float(difficulty), 1.0, 5.0)
        difficulty_score   = 1.0 - ((difficulty_clamped - 1.0) / 4.0)

    would_take_again_score: float | None = None
    if would_take_again_pct is not None:
        wta_clamped          = clamp(float(would_take_again_pct), 0.0, 100.0)
        would_take_again_score = wta_clamped / 100.0

    weighted_sum   = 0.60 * rating_score
    weighted_total = 0.60
    if would_take_again_score is not None:
        weighted_sum   += 0.25 * would_take_again_score
        weighted_total += 0.25
    if difficulty_score is not None:
        weighted_sum   += 0.15 * difficulty_score
        weighted_total += 0.15

    base_sentiment_score                = (weighted_sum / weighted_total) if weighted_total > 0 else 0.0
    confidence_adjusted_sentiment_score = base_sentiment_score * confidence_weight

    return {
        "confidence_weight":                 confidence_weight,
        "rating_shrunk":                     rating_shrunk,
        "rating_score":                      rating_score,
        "difficulty_score":                  difficulty_score if difficulty_score is not None else -1.0,
        "would_take_again_score":            would_take_again_score if would_take_again_score is not None else -1.0,
        "base_sentiment_score":              base_sentiment_score,
        "confidence_adjusted_sentiment_score": confidence_adjusted_sentiment_score,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Extended professor sentiment build.")
    parser.add_argument("--db-path",            type=Path,  default=get_database_path())
    parser.add_argument("--professor-name",     type=str,   default=None)
    parser.add_argument("--limit",              type=int,   default=0)
    parser.add_argument("--force-rebuild",      action="store_true",
                        help="Ignore incremental watermarks; rebuild all professors")
    parser.add_argument("--prior-weight",       type=int,   default=10)
    parser.add_argument("--prior-rating-mean",  type=float, default=3.8)
    parser.add_argument("--sentiment-llm-endpoint", type=str,
                        default="http://localhost:11434/v1/chat/completions")
    parser.add_argument("--sentiment-llm-model",    type=str, default="llama3.1")
    parser.add_argument("--sentiment-llm-api-key",  type=str, default=None)
    parser.add_argument("--sentiment-llm-timeout",  type=int, default=30)
    parser.add_argument("--sentiment-llm-max-snippets", type=int, default=8)
    args = parser.parse_args()

    imported_at        = datetime.now(timezone.utc).isoformat()
    endpoint           = args.sentiment_llm_endpoint or None
    model              = args.sentiment_llm_model
    api_key            = args.sentiment_llm_api_key
    timeout            = args.sentiment_llm_timeout
    max_snippets       = args.sentiment_llm_max_snippets

    anomaly_warnings: list[str] = []

    with sqlite3.connect(args.db_path) as conn:
        conn.row_factory = sqlite3.Row
        ensure_extended_schema(conn)

        professor_rows = conn.execute(
            """
            SELECT p.professor_name, p.overall_rating, p.num_ratings,
                   p.percent_take_again, p.level_of_difficulty, p.source_url
            FROM professor_rmp_profiles p
            ORDER BY p.professor_name
            """
        ).fetchall()

        if args.professor_name:
            needle = args.professor_name.strip().lower()
            professor_rows = [
                r for r in professor_rows
                if needle in str(r["professor_name"] or "").lower()
            ]
        if args.limit > 0:
            professor_rows = professor_rows[: args.limit]

        # Filter to only professors that need rebuilding (incremental mode)
        if not args.force_rebuild:
            professor_rows = [
                r for r in professor_rows
                if needs_rebuild(str(r["professor_name"]), conn)
            ]
            print(f"Incremental mode: {len(professor_rows)} professor(s) need rebuild.")
        else:
            print(f"Force rebuild: processing all {len(professor_rows)} professor(s).")
            # In force mode, wipe old rows so we can re-insert cleanly
            if not args.professor_name:
                conn.execute("DELETE FROM professor_sentiment_features")

        inserted = 0
        llm_summarized = 0
        anomaly_count  = 0

        for row in professor_rows:
            professor_name = str(row["professor_name"] or "").strip()
            if not professor_name:
                continue

            rating     = float(row["overall_rating"] or 0.0)
            num_ratings = int(row["num_ratings"] or 0)
            difficulty = float(row["level_of_difficulty"]) if row["level_of_difficulty"] is not None else None
            wta_pct    = float(row["percent_take_again"]) if row["percent_take_again"] is not None else None
            rmp_url    = row["source_url"]

            # --- Feature calculation (unchanged from original) ---
            features = calculate_sentiment_features(
                rating=rating,
                difficulty=difficulty,
                would_take_again_pct=wta_pct,
                num_ratings=num_ratings,
                prior_weight=args.prior_weight,
                prior_rating_mean=args.prior_rating_mean,
            )

            # --- LLM summary (original path) ---
            review_texts = fetch_new_reviews_since(professor_name, None, conn)
            llm_payload: dict | None = None
            if review_texts and endpoint:
                snippet_count = max(1, min(len(review_texts), max_snippets))
                llm_payload   = summarize_review_texts(
                    review_texts[:snippet_count],
                    endpoint=endpoint, model=model,
                    api_key=api_key, timeout=timeout,
                )
                if llm_payload:
                    llm_summarized += 1

            base_sentiment  = features["confidence_adjusted_sentiment_score"]
            final_score     = base_sentiment
            llm_score       = None
            llm_label       = None
            llm_summary     = None
            llm_pros_json   = None
            llm_cons_json   = None

            if llm_payload:
                llm_summary   = str(llm_payload.get("summary") or "").strip() or None
                llm_pros_json = json.dumps(llm_payload.get("pros") or [])
                llm_cons_json = json.dumps(llm_payload.get("cons") or [])

            anomaly = detect_sentiment_anomaly(professor_name, final_score, conn)
            if anomaly["is_anomaly"]:
                anomaly_count += 1
                anomaly_warnings.append(anomaly["message"])
                print(f"  ⚠  {anomaly['message']}")

            ci = compute_confidence_interval(rating, num_ratings)

            trend = compute_sentiment_trend(professor_name, conn)

            tag_breakdown = compute_tag_sentiment_breakdown(
                professor_name, conn,
                endpoint=endpoint, model=model, api_key=api_key, timeout=timeout,
            )

            course_sentiment = compute_course_specific_sentiment(professor_name, conn)

            structured: dict | None = None
            if endpoint and review_texts:
                structured = extract_structured_sentiment(
                    review_texts[:max_snippets],
                    rating=rating, difficulty=difficulty,
                    would_take_again_pct=wta_pct, review_count=num_ratings,
                    endpoint=endpoint, model=model,
                    api_key=api_key, timeout=timeout,
                )
                if structured and structured.get("overall_sentiment") is not None:
                    # Blend: 65% stats-based, 35% structured LLM
                    final_score = 0.65 * base_sentiment + 0.35 * float(
                        structured["overall_sentiment"]
                    )

            hallucination_result: dict | None = None
            if llm_summary and review_texts:
                hallucination_result = verify_sentiment_claims(llm_summary, review_texts)
                # If summary contains unsupported claims, use the cleaned version
                if hallucination_result and not hallucination_result["verified"]:
                    clean = hallucination_result.get("clean_summary", "")
                    if clean:
                        llm_summary = clean
                        print(
                            f"  ℹ  Hallucination guard cleaned summary for {professor_name}: "
                            f"{len(hallucination_result['unsupported'])} unsupported claim(s) removed."
                        )

            conn.execute(
                """
                INSERT INTO professor_sentiment_features (
                    professor_name, source, rating, difficulty, would_take_again_pct,
                    review_count, confidence_weight, rating_shrunk, rating_score,
                    difficulty_score, would_take_again_score, base_sentiment_score,
                    confidence_adjusted_sentiment_score, llm_sentiment_score,
                    llm_sentiment_label, llm_sentiment_summary, llm_sentiment_pros_json,
                    llm_sentiment_cons_json, final_sentiment_score, rmp_url, imported_at,
                    sentiment_trend, tag_sentiment_json, course_sentiment_json,
                    score_low, score_high, score_margin, structured_sentiment_json,
                    hallucination_check_json, anomaly_json, last_incremental_built_at
                ) VALUES (
                    ?,?,?,?,?, ?,?,?,?,?, ?,?,?,?,?, ?,?,?,?,?,?, ?,?,?,?,?,?,?,?,?,?
                )
                ON CONFLICT(professor_name) DO UPDATE SET
                    source=excluded.source, rating=excluded.rating,
                    difficulty=excluded.difficulty,
                    would_take_again_pct=excluded.would_take_again_pct,
                    review_count=excluded.review_count,
                    confidence_weight=excluded.confidence_weight,
                    rating_shrunk=excluded.rating_shrunk,
                    rating_score=excluded.rating_score,
                    difficulty_score=excluded.difficulty_score,
                    would_take_again_score=excluded.would_take_again_score,
                    base_sentiment_score=excluded.base_sentiment_score,
                    confidence_adjusted_sentiment_score=excluded.confidence_adjusted_sentiment_score,
                    llm_sentiment_score=excluded.llm_sentiment_score,
                    llm_sentiment_label=excluded.llm_sentiment_label,
                    llm_sentiment_summary=excluded.llm_sentiment_summary,
                    llm_sentiment_pros_json=excluded.llm_sentiment_pros_json,
                    llm_sentiment_cons_json=excluded.llm_sentiment_cons_json,
                    final_sentiment_score=excluded.final_sentiment_score,
                    rmp_url=excluded.rmp_url, imported_at=excluded.imported_at,
                    sentiment_trend=excluded.sentiment_trend,
                    tag_sentiment_json=excluded.tag_sentiment_json,
                    course_sentiment_json=excluded.course_sentiment_json,
                    score_low=excluded.score_low, score_high=excluded.score_high,
                    score_margin=excluded.score_margin,
                    structured_sentiment_json=excluded.structured_sentiment_json,
                    hallucination_check_json=excluded.hallucination_check_json,
                    anomaly_json=excluded.anomaly_json,
                    last_incremental_built_at=excluded.last_incremental_built_at
                """,
                (
                    professor_name, "ratemyprofessors_live",
                    row["overall_rating"], row["level_of_difficulty"], row["percent_take_again"],
                    num_ratings, features["confidence_weight"], features["rating_shrunk"],
                    features["rating_score"],
                    None if features["difficulty_score"] < 0 else features["difficulty_score"],
                    None if features["would_take_again_score"] < 0 else features["would_take_again_score"],
                    features["base_sentiment_score"], base_sentiment,
                    llm_score, llm_label, llm_summary, llm_pros_json, llm_cons_json,
                    round(final_score, 6), rmp_url, imported_at,
                    json.dumps(trend),
                    json.dumps(tag_breakdown),
                    json.dumps(course_sentiment),
                    ci["low"], ci["high"], ci["margin"],
                    json.dumps(structured) if structured else None,
                    json.dumps(hallucination_result) if hallucination_result else None,
                    json.dumps(anomaly),
                    imported_at,
                ),
            )
            inserted += 1

        conn.commit()

    print(
        f"\nDone. processed={len(professor_rows)}, upserted={inserted}, "
        f"llm_summarized={llm_summarized}, anomalies={anomaly_count}"
    )
    if anomaly_warnings:
        print("\nAnomaly warnings:")
        for w in anomaly_warnings:
            print(f"  • {w}")


if __name__ == "__main__":
    main()
