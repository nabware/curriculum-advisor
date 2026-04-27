#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.core.database import get_database_path
from app.models.schemas import AdvisorRequest
import app.services.advisor_service as advisor_service_module
from app.services.advisor_service import AdvisorService


def parse_completed_courses(value: str) -> list[str]:
    if not value.strip():
        return []
    seen: set[str] = set()
    out: list[str] = []
    for token in value.replace("|", ",").replace(";", ",").split(","):
        course = token.strip().upper()
        if not course or course in seen:
            continue
        seen.add(course)
        out.append(course)
    return out


def parse_bool(value: str, default: bool = False) -> bool:
    cleaned = (value or "").strip().lower()
    if cleaned in {"1", "true", "t", "yes", "y"}:
        return True
    if cleaned in {"0", "false", "f", "no", "n"}:
        return False
    return default


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


def resolve_numeric_name_match(
    instructor_name: str | None,
    by_full_name: dict[str, float],
    by_last_initial: dict[str, list[float]],
    by_last_name: dict[str, list[float]],
) -> float | None:
    full_key = normalize_name(instructor_name)
    if full_key and full_key in by_full_name:
        return by_full_name[full_key]

    last_initial = last_name_first_initial_key(instructor_name)
    if last_initial:
        matches = by_last_initial.get(last_initial, [])
        if len(matches) == 1:
            return matches[0]

    last_key = last_name_key(instructor_name)
    if last_key:
        matches = by_last_name.get(last_key, [])
        if len(matches) == 1:
            return matches[0]

    return None


def load_sentiment_by_professor(
    db_path: Path,
) -> tuple[dict[str, float], dict[str, list[float]], dict[str, list[float]]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT professor_name, confidence_adjusted_sentiment_score
            FROM professor_sentiment_features
            WHERE confidence_adjusted_sentiment_score IS NOT NULL
            """
        ).fetchall()

    by_full: dict[str, float] = {}
    by_last_initial: dict[str, list[float]] = {}
    by_last_name: dict[str, list[float]] = {}

    for row in rows:
        name = (row["professor_name"] or "").strip()
        if not name:
            continue
        score = float(row["confidence_adjusted_sentiment_score"])
        by_full[normalize_name(name)] = score

        key_li = last_name_first_initial_key(name)
        if key_li:
            by_last_initial.setdefault(key_li, []).append(score)

        key_ln = last_name_key(name)
        if key_ln:
            by_last_name.setdefault(key_ln, []).append(score)

    return by_full, by_last_initial, by_last_name


def average_recommendation_sentiment(
    courses: list,
    by_full_name: dict[str, float],
    by_last_initial: dict[str, list[float]],
    by_last_name: dict[str, list[float]],
) -> float | None:
    scores: list[float] = []
    for course in courses:
        score = resolve_numeric_name_match(
            course.professor_name or course.instructor,
            by_full_name,
            by_last_initial,
            by_last_name,
        )
        if score is not None:
            scores.append(score)

    if not scores:
        return None
    return sum(scores) / len(scores)


def read_scenarios(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [row for row in csv.DictReader(handle)]


def evaluate_weight_set(
    scenarios: list[dict[str, str]],
    progress_weight: float,
    workload_weight: float,
    sentiment_weight: float,
    by_full_name: dict[str, float],
    by_last_initial: dict[str, list[float]],
    by_last_name: dict[str, list[float]],
) -> dict[str, float]:
    overlap_values: list[float] = []
    sentiment_lifts: list[float] = []

    for scenario in scenarios:
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
            objective_progress_weight=progress_weight,
            objective_workload_weight=workload_weight,
            objective_sentiment_weight=sentiment_weight,
            max_units_per_semester=max_units,
            term=term,
        )
        sent_payload = base_payload.model_copy(update={"prefer_high_rated_professors": True})

        baseline = AdvisorService.recommend(base_payload)
        sentiment = AdvisorService.recommend(sent_payload)

        baseline_codes = [course.course_code for course in baseline.recommendations]
        sentiment_codes = [course.course_code for course in sentiment.recommendations]
        k = min(5, max(len(baseline_codes), len(sentiment_codes)))
        if k > 0:
            overlap = len(set(baseline_codes[:k]) & set(sentiment_codes[:k])) / float(k)
        else:
            overlap = 0.0
        overlap_values.append(overlap)

        baseline_avg = average_recommendation_sentiment(
            baseline.recommendations,
            by_full_name,
            by_last_initial,
            by_last_name,
        )
        sentiment_avg = average_recommendation_sentiment(
            sentiment.recommendations,
            by_full_name,
            by_last_initial,
            by_last_name,
        )
        if baseline_avg is not None and sentiment_avg is not None:
            sentiment_lifts.append(sentiment_avg - baseline_avg)

    mean_overlap = sum(overlap_values) / len(overlap_values) if overlap_values else 0.0
    mean_sentiment_lift = (
        sum(sentiment_lifts) / len(sentiment_lifts) if sentiment_lifts else 0.0
    )

    return {
        "mean_overlap_at_5": mean_overlap,
        "mean_sentiment_lift": mean_sentiment_lift,
        "objective_score": mean_sentiment_lift + 0.05 * (1.0 - abs(0.7 - mean_overlap)),
    }


def write_results(path: Path, rows: list[dict[str, float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "progress_weight",
        "workload_weight",
        "sentiment_weight",
        "mean_overlap_at_5",
        "mean_sentiment_lift",
        "objective_score",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Grid-search objective weights for sentiment-aware ranking."
    )
    parser.add_argument(
        "--scenarios-csv",
        type=Path,
        default=PROJECT_ROOT / "data" / "seed" / "evaluation_scenarios.csv",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=PROJECT_ROOT / "data" / "processed" / "objective_weight_tuning.csv",
    )
    parser.add_argument("--progress-grid", type=str, default="0.45,0.55,0.65")
    parser.add_argument("--workload-grid", type=str, default="0.10,0.20,0.30")
    parser.add_argument("--sentiment-grid", type=str, default="0.20,0.35,0.50")
    parser.add_argument("--db-path", type=Path, default=get_database_path())
    parser.add_argument("--enable-live-rmp", action="store_true", default=False)
    args = parser.parse_args()

    scenarios = read_scenarios(args.scenarios_csv)
    if not scenarios:
        raise SystemExit(f"No scenarios found in {args.scenarios_csv}")

    progress_values = [float(value) for value in args.progress_grid.split(",") if value.strip()]
    workload_values = [float(value) for value in args.workload_grid.split(",") if value.strip()]
    sentiment_values = [float(value) for value in args.sentiment_grid.split(",") if value.strip()]

    # Force DB path validity early.
    with sqlite3.connect(args.db_path):
        pass

    by_full_name, by_last_initial, by_last_name = load_sentiment_by_professor(args.db_path)

    if not args.enable_live_rmp:
        advisor_service_module.fetch_professor_rating = lambda _name: None

    rows: list[dict[str, float]] = []
    best_row: dict[str, float] | None = None

    for pw in progress_values:
        for ww in workload_values:
            for sw in sentiment_values:
                metrics = evaluate_weight_set(
                    scenarios,
                    pw,
                    ww,
                    sw,
                    by_full_name,
                    by_last_initial,
                    by_last_name,
                )
                row = {
                    "progress_weight": pw,
                    "workload_weight": ww,
                    "sentiment_weight": sw,
                    **metrics,
                }
                rows.append(row)
                if best_row is None or row["objective_score"] > best_row["objective_score"]:
                    best_row = row

    write_results(args.output_csv, rows)

    if best_row is None:
        raise SystemExit("No weight combinations evaluated")

    print(f"Evaluated combinations: {len(rows)}")
    print(
        "Best weights: "
        f"progress={best_row['progress_weight']:.3f}, "
        f"workload={best_row['workload_weight']:.3f}, "
        f"sentiment={best_row['sentiment_weight']:.3f}"
    )
    print(
        "Best metrics: "
        f"mean_overlap@5={best_row['mean_overlap_at_5']:.4f}, "
        f"mean_sentiment_lift={best_row['mean_sentiment_lift']:.6f}, "
        f"objective_score={best_row['objective_score']:.6f}"
    )
    print(f"Tuning report: {args.output_csv}")


if __name__ == "__main__":
    main()
