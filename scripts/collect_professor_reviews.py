#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.core.database import get_database_path
from rmp_client import RMPClient


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_iso8601(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        key = item.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(key)
    return result


def fetch_professor_names(db_path: Path) -> list[str]:
    with sqlite3.connect(db_path) as conn:
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


def init_cache_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
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
            source_url TEXT,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (professor_name, review_hash)
        );
        """
    )


def load_cached_reviews(
    conn: sqlite3.Connection,
    professor_name: str,
    stale_hours: int,
) -> tuple[list[str], str | None, bool]:
    state_row = conn.execute(
        """
        SELECT source_url, status, fetched_at
        FROM crawl_state
        WHERE professor_name = ?
        """,
        (professor_name,),
    ).fetchone()

    if not state_row:
        return [], None, False

    source_url = str(state_row[0]) if state_row[0] else None
    status = str(state_row[1])
    fetched_at = parse_iso8601(str(state_row[2]))
    if not fetched_at:
        return [], source_url, False

    cutoff = datetime.now(timezone.utc).timestamp() - (stale_hours * 3600)
    if fetched_at.timestamp() < cutoff:
        return [], source_url, False

    if status != "ok":
        return [], source_url, True

    review_rows = conn.execute(
        """
        SELECT review_text
        FROM review_cache
        WHERE professor_name = ?
        ORDER BY fetched_at DESC
        """,
        (professor_name,),
    ).fetchall()

    reviews = [str(row[0]).strip() for row in review_rows if row[0]]
    return dedupe_preserve_order(reviews), source_url, True


def write_cache_result(
    conn: sqlite3.Connection,
    professor_name: str,
    source_url: str | None,
    status: str,
    error_message: str | None,
    review_texts: list[str],
) -> None:
    fetched_at = utc_now_iso()
    conn.execute(
        """
        INSERT INTO crawl_state (professor_name, source_url, status, error_message, fetched_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(professor_name)
        DO UPDATE SET
            source_url = excluded.source_url,
            status = excluded.status,
            error_message = excluded.error_message,
            fetched_at = excluded.fetched_at
        """,
        (professor_name, source_url, status, error_message, fetched_at),
    )

    conn.execute(
        "DELETE FROM review_cache WHERE professor_name = ?",
        (professor_name,),
    )

    for review_text in dedupe_preserve_order(review_texts):
        review_hash = hashlib.sha256(review_text.encode("utf-8")).hexdigest()
        conn.execute(
            """
            INSERT OR REPLACE INTO review_cache (
                professor_name,
                review_hash,
                review_text,
                source_url,
                fetched_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (professor_name, review_hash, review_text, source_url, fetched_at),
        )


def resolve_professor_match(
    client: RMPClient,
    professor_name: str,
    school_id: str,
) -> object | None:
    search_result = client.search_professors(
        professor_name,
        school_id=school_id,
        page_size=10,
    )
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

    return professors[0]


def fetch_reviews_for_professor(
    client: RMPClient,
    professor_name: str,
    school_id: str,
    max_reviews_per_professor: int,
    max_retries: int,
) -> tuple[str | None, list[str]]:
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            professor = resolve_professor_match(client, professor_name, school_id)
            if professor is None:
                return None, []

            source_url = f"https://www.ratemyprofessors.com/professor/{professor.id}"
            ratings = list(client.iter_professor_ratings(professor.id, page_size=100))
            review_texts = [
                normalize_space(str(rating.comment))
                for rating in ratings
                if getattr(rating, "comment", None)
                and normalize_space(str(rating.comment))
            ]

            if max_reviews_per_professor > 0:
                review_texts = review_texts[:max_reviews_per_professor]

            return source_url, dedupe_preserve_order(review_texts)
        except Exception as exc:
            last_error = exc
            backoff_seconds = min(8.0, 1.5 * (2 ** (attempt - 1)))
            time.sleep(backoff_seconds)

    if last_error:
        raise last_error
    return None, []


def write_output_csv(output_path: Path, rows: list[dict[str, str]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["professor_name", "review_text"])
        writer.writeheader()
        writer.writerows(rows)


def write_report_csv(output_path: Path, rows: list[dict[str, str]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "professor_name",
        "status",
        "review_count",
        "source_url",
        "from_cache",
        "error_message",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def collect_reviews(args: argparse.Namespace) -> None:
    professor_names = fetch_professor_names(args.db_path)
    if not professor_names:
        print("No professors found in professor_profiles.")
        return

    args.cache_db.parent.mkdir(parents=True, exist_ok=True)

    output_rows: list[dict[str, str]] = []
    report_rows: list[dict[str, str]] = []
    cache_hits = 0
    fetched = 0

    with sqlite3.connect(args.cache_db) as cache_conn:
        init_cache_schema(cache_conn)
        client = RMPClient()

        try:
            for idx, professor_name in enumerate(professor_names, start=1):
                cached_reviews, cached_url, cache_fresh = load_cached_reviews(
                    cache_conn,
                    professor_name,
                    args.stale_hours,
                )

                if cache_fresh and cached_reviews:
                    cache_hits += 1
                    selected_reviews = (
                        cached_reviews[: args.max_reviews_per_professor]
                        if args.max_reviews_per_professor > 0
                        else cached_reviews
                    )
                    for review_text in selected_reviews:
                        output_rows.append(
                            {
                                "professor_name": professor_name,
                                "review_text": review_text,
                            }
                        )
                    report_rows.append(
                        {
                            "professor_name": professor_name,
                            "status": "ok",
                            "review_count": str(len(cached_reviews)),
                            "source_url": cached_url or "",
                            "from_cache": "yes",
                            "error_message": "",
                        }
                    )
                    print(
                        f"[{idx}/{len(professor_names)}] {professor_name}: cache hit ({len(cached_reviews)} reviews)"
                    )
                    continue

                source_url, review_texts = fetch_reviews_for_professor(
                    client=client,
                    professor_name=professor_name,
                    school_id=args.school_id,
                    max_reviews_per_professor=args.max_reviews_per_professor,
                    max_retries=args.max_retries,
                )

                if not source_url:
                    write_cache_result(
                        cache_conn,
                        professor_name=professor_name,
                        source_url=None,
                        status="no_match",
                        error_message="No matching RMP profile found",
                        review_texts=[],
                    )
                    cache_conn.commit()
                    report_rows.append(
                        {
                            "professor_name": professor_name,
                            "status": "no_match",
                            "review_count": "0",
                            "source_url": "",
                            "from_cache": "no",
                            "error_message": "No matching RMP profile found",
                        }
                    )
                    print(f"[{idx}/{len(professor_names)}] {professor_name}: no profile match")
                    continue

                try:
                    fetched += 1
                    status = "ok" if review_texts else "ok_empty"
                    write_cache_result(
                        cache_conn,
                        professor_name=professor_name,
                        source_url=source_url,
                        status=status,
                        error_message=None,
                        review_texts=review_texts,
                    )
                    cache_conn.commit()

                    for review_text in review_texts:
                        output_rows.append(
                            {
                                "professor_name": professor_name,
                                "review_text": review_text,
                            }
                        )

                    report_rows.append(
                        {
                            "professor_name": professor_name,
                            "status": status,
                            "review_count": str(len(review_texts)),
                            "source_url": source_url,
                            "from_cache": "no",
                            "error_message": "",
                        }
                    )
                    print(
                        f"[{idx}/{len(professor_names)}] {professor_name}: fetched {len(review_texts)} reviews"
                    )
                except Exception as exc:
                    error_message = normalize_space(str(exc))
                    write_cache_result(
                        cache_conn,
                        professor_name=professor_name,
                        source_url=source_url,
                        status="error",
                        error_message=error_message,
                        review_texts=[],
                    )
                    cache_conn.commit()

                    report_rows.append(
                        {
                            "professor_name": professor_name,
                            "status": "error",
                            "review_count": "0",
                            "source_url": source_url,
                            "from_cache": "no",
                            "error_message": error_message,
                        }
                    )
                    print(
                        f"[{idx}/{len(professor_names)}] {professor_name}: error ({error_message})"
                    )
        finally:
            client.close()

    write_output_csv(args.output_csv, output_rows)
    write_report_csv(args.report_csv, report_rows)

    print(
        "Completed review collection: "
        f"professors={len(professor_names)}, "
        f"rows_written={len(output_rows)}, "
        f"cache_hits={cache_hits}, fetched_live={fetched}, "
        f"output={args.output_csv}, report={args.report_csv}, cache={args.cache_db}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Collect professor review snippets for all professors in professor_profiles "
            "using the RateMyProfessors GraphQL client with retry and cache."
        )
    )
    parser.add_argument("--db-path", type=Path, default=get_database_path())
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=PROJECT_ROOT / "data" / "seed" / "professor_review_snippets.csv",
    )
    parser.add_argument(
        "--report-csv",
        type=Path,
        default=PROJECT_ROOT / "data" / "processed" / "professor_review_collection_report.csv",
    )
    parser.add_argument(
        "--cache-db",
        type=Path,
        default=PROJECT_ROOT / "data" / "seed" / "professor_review_cache.db",
    )
    parser.add_argument(
        "--school-id",
        type=str,
        default="880",
        help="RateMyProfessors school id to scope professor searches (default: 880)",
    )
    parser.add_argument(
        "--max-reviews-per-professor",
        type=int,
        default=0,
        help="Maximum reviews to keep per professor; 0 means keep all reviews",
    )
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--stale-hours", type=int, default=24 * 7)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    collect_reviews(args)


if __name__ == "__main__":
    main()
