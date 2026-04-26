#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.core.database import get_database_path
from app.models.schemas import AdvisorRequest, RecommendedCourse
from app.services.advisor_service import AdvisorService


def parse_completed_courses(value: str) -> list[str]:
    if not value.strip():
        return []
    courses = [item.strip().upper() for item in re.split(r"[;|,]+", value) if item.strip()]
    deduped: list[str] = []
    seen: set[str] = set()
    for course in courses:
        if course in seen:
            continue
        seen.add(course)
        deduped.append(course)
    return deduped


def parse_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    cleaned = value.strip().lower()
    if cleaned in {"1", "true", "t", "yes", "y"}:
        return True
    if cleaned in {"0", "false", "f", "no", "n"}:
        return False
    return default


def normalize_name(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip().lower()


def load_sentiment_by_professor(conn: sqlite3.Connection) -> dict[str, float]:
    try:
        rows = conn.execute(
            """
            SELECT professor_name, confidence_adjusted_sentiment_score
            FROM professor_sentiment_features
            WHERE confidence_adjusted_sentiment_score IS NOT NULL
            """
        ).fetchall()
    except sqlite3.OperationalError:
        return {}

    sentiment: dict[str, float] = {}
    for row in rows:
        key = normalize_name(row[0])
        if not key:
            continue
        sentiment[key] = float(row[1])
    return sentiment


def average_sentiment_score(
    courses: list[RecommendedCourse], sentiment_by_professor: dict[str, float]
) -> float | None:
    scores: list[float] = []
    for course in courses:
        key = normalize_name(course.professor_name or course.instructor)
        if not key:
            continue
        score = sentiment_by_professor.get(key)
        if score is None:
            continue
        scores.append(score)

    if not scores:
        return None
    return sum(scores) / len(scores)


def overlap_at_k(codes_a: list[str], codes_b: list[str], k: int) -> float:
    if k <= 0:
        return 0.0
    top_a = set(codes_a[:k])
    top_b = set(codes_b[:k])
    return len(top_a & top_b) / float(k)


def timed_recommend(payload: AdvisorRequest) -> tuple[float, object]:
    started = time.perf_counter()
    result = AdvisorService.recommend(payload)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return elapsed_ms, result


def read_scenarios(scenarios_csv: Path) -> list[dict[str, str]]:
    with scenarios_csv.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [row for row in reader]


def write_report(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return

    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate baseline vs sentiment-aware recommendations across fixed scenarios "
            "and write a CSV report."
        )
    )
    parser.add_argument(
        "--scenarios-csv",
        type=Path,
        default=PROJECT_ROOT / "data" / "seed" / "evaluation_scenarios.csv",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=PROJECT_ROOT / "data" / "processed" / "evaluation_sentiment_impact.csv",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--db-path", type=Path, default=get_database_path())
    args = parser.parse_args()

    scenarios = read_scenarios(args.scenarios_csv)
    if not scenarios:
        raise SystemExit(f"No scenarios found in {args.scenarios_csv}")

    with sqlite3.connect(args.db_path) as conn:
        sentiment_by_professor = load_sentiment_by_professor(conn)

    report_rows: list[dict[str, object]] = []
    for scenario in scenarios:
        scenario_id = (scenario.get("scenario_id") or "").strip() or "scenario"
        major = (scenario.get("major") or "").strip()
        term = (scenario.get("term") or "").strip() or None
        max_units = int((scenario.get("max_units_per_semester") or "12").strip())
        completed_courses = parse_completed_courses(scenario.get("completed_courses") or "")
        transcript_text = (scenario.get("transcript_text") or "").strip() or None
        prefer_light = parse_bool(scenario.get("prefer_light_workload") or "false")

        base_payload = AdvisorRequest(
            major=major,
            completed_courses=completed_courses,
            transcript_text=transcript_text,
            blocked_time_windows=[],
            interests=[],
            career_goals=[],
            prefer_light_workload=prefer_light,
            prefer_high_rated_professors=False,
            max_units_per_semester=max_units,
            term=term,
        )
        sent_payload = base_payload.model_copy(update={"prefer_high_rated_professors": True})

        baseline_ms, baseline = timed_recommend(base_payload)
        sentiment_ms, sentiment = timed_recommend(sent_payload)

        baseline_codes = [course.course_code for course in baseline.recommendations]
        sentiment_codes = [course.course_code for course in sentiment.recommendations]
        k = min(args.top_k, max(len(baseline_codes), len(sentiment_codes)))
        overlap = overlap_at_k(baseline_codes, sentiment_codes, k) if k > 0 else 0.0

        baseline_avg_sentiment = average_sentiment_score(
            baseline.recommendations, sentiment_by_professor
        )
        sentiment_avg_sentiment = average_sentiment_score(
            sentiment.recommendations, sentiment_by_professor
        )

        sentiment_lift = None
        if baseline_avg_sentiment is not None and sentiment_avg_sentiment is not None:
            sentiment_lift = sentiment_avg_sentiment - baseline_avg_sentiment

        report_rows.append(
            {
                "scenario_id": scenario_id,
                "major": major,
                "term": term or "",
                "baseline_course_count": len(baseline.recommendations),
                "sentiment_course_count": len(sentiment.recommendations),
                "baseline_units_selected": baseline.total_units_selected,
                "sentiment_units_selected": sentiment.total_units_selected,
                "baseline_latency_ms": round(baseline_ms, 2),
                "sentiment_latency_ms": round(sentiment_ms, 2),
                "latency_delta_ms": round(sentiment_ms - baseline_ms, 2),
                "top_k": k,
                "overlap_at_k": round(overlap, 4),
                "baseline_avg_sentiment": None
                if baseline_avg_sentiment is None
                else round(baseline_avg_sentiment, 6),
                "sentiment_avg_sentiment": None
                if sentiment_avg_sentiment is None
                else round(sentiment_avg_sentiment, 6),
                "sentiment_lift": None if sentiment_lift is None else round(sentiment_lift, 6),
                "baseline_top_codes": "|".join(baseline_codes[: args.top_k]),
                "sentiment_top_codes": "|".join(sentiment_codes[: args.top_k]),
            }
        )

    write_report(args.output_csv, report_rows)

    total = len(report_rows)
    mean_overlap = sum(float(row["overlap_at_k"]) for row in report_rows) / total
    measured_lifts = [
        float(row["sentiment_lift"])
        for row in report_rows
        if row["sentiment_lift"] is not None and row["sentiment_lift"] != ""
    ]
    mean_lift = (sum(measured_lifts) / len(measured_lifts)) if measured_lifts else 0.0
    mean_latency_delta = sum(float(row["latency_delta_ms"]) for row in report_rows) / total

    print(f"Evaluated scenarios: {total}")
    print(f"Mean overlap@k: {mean_overlap:.4f}")
    print(f"Mean sentiment lift: {mean_lift:.6f}")
    print(f"Mean latency delta (ms): {mean_latency_delta:.2f}")
    print(f"Report written to: {args.output_csv}")


if __name__ == "__main__":
    main()