from __future__ import annotations

import json
import math
import re
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Any

from app.core.database import get_database_path
from app.services.llama_sentiment_service import (
    _call_json_llm,
    _trim_text,
    _normalize_sentiment_text,
)


def compute_sentiment_trend(
    professor_name: str,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """
    Bucket reviews into three time windows and return a trend dict.

    Returns:
        {
          "recent_avg":   float | None,   # last 6 months
          "mid_avg":      float | None,   # 6–24 months ago
          "older_avg":    float | None,   # > 24 months ago
          "trend":        "improving" | "declining" | "stable" | "insufficient_data",
          "bucket_counts": {"recent": int, "mid": int, "older": int},
        }
    """
    now = datetime.now(timezone.utc)
    cutoff_recent = (now - timedelta(days=180)).date().isoformat()
    cutoff_mid    = (now - timedelta(days=730)).date().isoformat()

    rows = conn.execute(
        """
        SELECT review_date, quality
        FROM professor_rmp_reviews
        WHERE professor_name = ?
          AND review_date IS NOT NULL
          AND quality IS NOT NULL
        ORDER BY review_date
        """,
        (professor_name,),
    ).fetchall()

    buckets: dict[str, list[float]] = {"recent": [], "mid": [], "older": []}
    for row in rows:
        date_str = str(row[0] if not hasattr(row, "keys") else row["review_date"])
        quality  = float(row[1] if not hasattr(row, "keys") else row["quality"])
        if date_str >= cutoff_recent:
            buckets["recent"].append(quality)
        elif date_str >= cutoff_mid:
            buckets["mid"].append(quality)
        else:
            buckets["older"].append(quality)

    def _avg(lst: list[float]) -> float | None:
        return sum(lst) / len(lst) if lst else None

    recent_avg = _avg(buckets["recent"])
    mid_avg    = _avg(buckets["mid"])
    older_avg  = _avg(buckets["older"])
    trend = "insufficient_data"
    comparisons: list[tuple[float | None, float | None]] = [
        (recent_avg, mid_avg),
        (recent_avg, older_avg),
    ]
    deltas: list[float] = []
    for newer, older in comparisons:
        if newer is not None and older is not None:
            deltas.append(newer - older)

    if deltas:
        avg_delta = sum(deltas) / len(deltas)
        if avg_delta > 0.3:
            trend = "improving"
        elif avg_delta < -0.3:
            trend = "declining"
        else:
            trend = "stable"

    return {
        "recent_avg": recent_avg,
        "mid_avg":    mid_avg,
        "older_avg":  older_avg,
        "trend":      trend,
        "bucket_counts": {k: len(v) for k, v in buckets.items()},
    }

def compute_tag_sentiment_breakdown(
    professor_name: str,
    conn: sqlite3.Connection,
    *,
    endpoint: str | None = None,
    model: str = "llama3.1",
    api_key: str | None = None,
    timeout: int = 30,
) -> dict[str, dict[str, Any]]:
    """
    For each distinct RMP tag, compute a sentiment score from the subset of
    reviews that mention (or have) that tag.

    Returns:
        {
          "Tough Grader": {
              "count": 4,
              "avg_quality": 3.1,
              "tone": "negative" | "positive" | "neutral",
              "llm_summary": str | None,
          },
          ...
        }
    """
    rows = conn.execute(
        """
        SELECT review_text, quality, tags_json
        FROM professor_rmp_reviews
        WHERE professor_name = ?
          AND tags_json IS NOT NULL
          AND tags_json != '[]'
        """,
        (professor_name,),
    ).fetchall()

    tag_buckets: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        try:
            tags = json.loads(row[2] if not hasattr(row, "keys") else row["tags_json"])
        except (json.JSONDecodeError, TypeError):
            tags = []
        quality  = float(row[1] if not hasattr(row, "keys") else row["quality"] or 3.0)
        text     = str(row[0] if not hasattr(row, "keys") else row["review_text"] or "")
        for tag in tags:
            tag_norm = str(tag).strip()
            if tag_norm:
                tag_buckets.setdefault(tag_norm, []).append({"quality": quality, "text": text})

    result: dict[str, dict[str, Any]] = {}
    for tag, entries in tag_buckets.items():
        qualities = [e["quality"] for e in entries]
        avg_quality = sum(qualities) / len(qualities)
        if avg_quality >= 3.8:
            tone = "positive"
        elif avg_quality <= 2.5:
            tone = "negative"
        else:
            tone = "neutral"

        llm_summary: str | None = None
        if endpoint and len(entries) >= 2:
            texts = [e["text"] for e in entries if e["text"].strip()][:5]
            if texts:
                prompt = (
                    f"These reviews all mention the tag '{tag}' for a professor. "
                    "Summarize in one sentence what students say about this aspect of the professor. "
                    "Return JSON only: {\"summary\": \"...\", \"tone\": \"positive|neutral|negative\"}"
                    f"\n\nReviews:\n" + "\n".join(f"- {_trim_text(t, 300)}" for t in texts)
                )
                parsed = _call_json_llm(
                    prompt,
                    endpoint=endpoint,
                    model=model,
                    api_key=api_key,
                    timeout=timeout,
                )
                if parsed:
                    llm_summary = _normalize_sentiment_text(str(parsed.get("summary") or ""))
                    llm_tone = str(parsed.get("tone") or "").lower()
                    if llm_tone in {"positive", "neutral", "negative"}:
                        tone = llm_tone

        result[tag] = {
            "count":       len(entries),
            "avg_quality": round(avg_quality, 2),
            "tone":        tone,
            "llm_summary": llm_summary,
        }

    return result

def compute_course_specific_sentiment(
    professor_name: str,
    conn: sqlite3.Connection,
) -> dict[str, dict[str, Any]]:
    """
    Parse course_raw from reviews to build per-course sentiment at
    (professor, course_code) granularity.

    Returns:
        {
          "CSC 256": {"avg_quality": 3.4, "review_count": 5, "base_sentiment": 0.68},
          ...
        }
    """
    rows = conn.execute(
        """
        SELECT quality, difficulty, course_raw
        FROM professor_rmp_reviews
        WHERE professor_name = ?
          AND quality IS NOT NULL
        """,
        (professor_name,),
    ).fetchall()

    course_buckets: dict[str, list[dict[str, Any]]] = {}
    course_code_pattern = re.compile(r"([A-Z]{2,6})\s*(\d{3,4})", re.IGNORECASE)

    for row in rows:
        quality    = float(row[0] if not hasattr(row, "keys") else row["quality"])
        difficulty = row[2] if not hasattr(row, "keys") else row["difficulty"]
        course_raw = str(row[2] if not hasattr(row, "keys") else row["course_raw"] or "").strip()
        match = course_code_pattern.search(course_raw)
        if match:
            course_key = f"{match.group(1).upper()} {match.group(2)}"
        elif course_raw.isdigit():
            course_key = course_raw 
        else:
            continue

        course_buckets.setdefault(course_key, []).append(
            {"quality": quality, "difficulty": difficulty}
        )

    result: dict[str, dict[str, Any]] = {}
    for course_key, entries in course_buckets.items():
        qualities   = [e["quality"] for e in entries]
        avg_quality = sum(qualities) / len(qualities)
        base_sentiment = avg_quality / 5.0
        result[course_key] = {
            "avg_quality":    round(avg_quality, 3),
            "review_count":   len(entries),
            "base_sentiment": round(base_sentiment, 3),
        }
    return result


def compute_confidence_interval(
    rating: float,
    num_ratings: int,
    *,
    z: float = 1.96,      # 95 % CI
    max_rating: float = 5.0,
) -> dict[str, float]:
    """
    Return a Wilson-score-inspired confidence interval for the sentiment score.

    Because RMP ratings are 1–5 (not binary), we treat the proportion as
    p = rating / max_rating and apply the standard Wilson interval.

    Returns:
        {"score": float, "low": float, "high": float, "margin": float}
    """
    if num_ratings <= 0:
        return {"score": 0.5, "low": 0.0, "high": 1.0, "margin": 0.5}

    p = max(0.0, min(1.0, rating / max_rating))
    n = num_ratings
    z2 = z * z

    centre = (p + z2 / (2 * n)) / (1 + z2 / n)
    half_width = (z / (1 + z2 / n)) * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))

    low  = max(0.0, centre - half_width)
    high = min(1.0, centre + half_width)
    return {
        "score":  round(p, 4),
        "low":    round(low, 4),
        "high":   round(high, 4),
        "margin": round(high - low, 4),
    }

def extract_structured_sentiment(
    review_texts: list[str],
    *,
    rating: float,
    difficulty: float | None,
    would_take_again_pct: float | None,
    review_count: int,
    endpoint: str | None,
    model: str = "llama3.1",
    api_key: str | None = None,
    timeout: int = 30,
) -> dict[str, Any] | None:
    """
    Call the LLM with a prompt requesting a multi-dimension sentiment JSON.

    Returns:
        {
          "overall_sentiment":   float,   # 0–1
          "teaching_clarity":    float,   # 0–1
          "grading_fairness":    float,   # 0–1
          "accessibility":       float,   # 0–1
          "course_difficulty":   float,   # 0–1  (higher = harder)
          "sentiment_label":     str,
          "summary":             str,
        }
    """
    if not endpoint or not review_texts:
        return None

    cleaned = [re.sub(r"\s+", " ", r).strip() for r in review_texts if r.strip()][:10]
    joined  = "\n\n".join(
        f"Review {i + 1}: {_trim_text(r, 500)}" for i, r in enumerate(cleaned)
    )
    stats = (
        f"Overall rating: {rating:.1f}/5. "
        f"Difficulty: {difficulty:.1f}/5. " if difficulty else ""
        f"Would take again: {would_take_again_pct:.0f}%. " if would_take_again_pct else ""
        f"Review count: {review_count}."
    )
    prompt = (
        "Analyze these professor reviews. Score ONLY what the reviews say "
        "(0.0 = very bad, 1.0 = very good). Return strict JSON only:\n"
        '{"overall_sentiment":0.0,"teaching_clarity":0.0,"grading_fairness":0.0,'
        '"accessibility":0.0,"course_difficulty":0.0,'
        '"sentiment_label":"positive|neutral|negative","summary":"..."}\n\n'
        f"Stats: {stats}\n\nReviews:\n{joined}"
    )

    parsed = _call_json_llm(
        prompt,
        endpoint=endpoint,
        model=model,
        api_key=api_key,
        timeout=timeout,
        max_tokens=300,
    )
    if not parsed:
        return None

    def _clamp(val: Any, default: float = 0.5) -> float:
        try:
            return max(0.0, min(1.0, float(val)))
        except (TypeError, ValueError):
            return default

    label = str(parsed.get("sentiment_label") or "neutral").strip().lower()
    if label not in {"positive", "neutral", "negative"}:
        label = "neutral"

    return {
        "overall_sentiment":  _clamp(parsed.get("overall_sentiment")),
        "teaching_clarity":   _clamp(parsed.get("teaching_clarity")),
        "grading_fairness":   _clamp(parsed.get("grading_fairness")),
        "accessibility":      _clamp(parsed.get("accessibility")),
        "course_difficulty":  _clamp(parsed.get("course_difficulty")),
        "sentiment_label":    label,
        "summary":            _normalize_sentiment_text(str(parsed.get("summary") or "")),
    }

def build_preference_weight_vector(
    preferences_text: str | None,
    *,
    endpoint: str | None = None,
    model: str = "llama3.2:3b",
    api_key: str | None = None,
    timeout: int = 10,
) -> dict[str, float]:
    """
    Parse free-form student preferences into dimension weights for ranking.

    Default weights (sum to 1.0):
        teaching_clarity  0.35
        grading_fairness  0.25
        accessibility     0.20
        overall_sentiment 0.20

    Student can shift these via text like "I really need clear explanations"
    (raises teaching_clarity weight) or "I hate tough graders" (raises
    grading_fairness weight).

    Falls back to keyword rules if Ollama is unavailable.
    """
    defaults: dict[str, float] = {
        "teaching_clarity":  0.35,
        "grading_fairness":  0.25,
        "accessibility":     0.20,
        "overall_sentiment": 0.20,
    }

    if not preferences_text or not preferences_text.strip():
        return defaults

    lower = preferences_text.strip().lower()

    weights = dict(defaults)
    if re.search(r"\b(clear|explain|understand|clarity|confusing)\b", lower):
        weights["teaching_clarity"] += 0.15
    if re.search(r"\b(fair|grade|grader|tough grader|strict)\b", lower):
        weights["grading_fairness"] += 0.15
    if re.search(r"\b(access|help|office.?hour|respond|available)\b", lower):
        weights["accessibility"] += 0.10
    if re.search(r"\b(highly.?rated|best professor|top professor)\b", lower):
        weights["overall_sentiment"] += 0.15

    total = sum(weights.values())
    return {k: round(v / total, 4) for k, v in weights.items()}


def score_professor_with_weights(
    structured_sentiment: dict[str, Any],
    weight_vector: dict[str, float],
) -> float:
    """
    Compute a weighted composite sentiment score from structured dimensions.
    """
    dims = ["teaching_clarity", "grading_fairness", "accessibility", "overall_sentiment"]
    total_w = sum(weight_vector.get(d, 0.0) for d in dims)
    if total_w <= 0:
        return structured_sentiment.get("overall_sentiment", 0.5)

    score = sum(
        weight_vector.get(d, 0.0) * structured_sentiment.get(d, 0.5)
        for d in dims
    )
    return round(score / total_w, 4)

def verify_sentiment_claims(
    summary: str,
    source_reviews: list[str],
    *,
    min_support_ratio: float = 0.15,
) -> dict[str, Any]:
    """
    Extract factual claims from the LLM summary and verify each one is
    grounded in at least one source review via keyword overlap.

    Returns:
        {
          "verified":   bool,              # True if all claims are grounded
          "claims":     list[str],         # extracted claim phrases
          "supported":  list[str],         # claims with evidence
          "unsupported": list[str],        # claims with no evidence
          "clean_summary": str,            # summary with unsupported claims removed
        }
    """
    if not summary or not source_reviews:
        return {
            "verified":      True,
            "claims":        [],
            "supported":     [],
            "unsupported":   [],
            "clean_summary": summary,
        }

    claim_sentences = [s.strip() for s in re.split(r"[.!?]+", summary) if s.strip()]

    corpus = " ".join(source_reviews).lower()
    corpus_tokens = set(re.findall(r"\b[a-z]{3,}\b", corpus))

    supported:   list[str] = []
    unsupported: list[str] = []

    stopwords = {
        "the", "and", "for", "that", "this", "with", "are", "has", "was",
        "have", "from", "they", "not", "but", "its", "who", "can", "his",
        "her", "their", "very", "also", "often", "sometimes", "professor",
        "students", "course", "class",
    }

    for claim in claim_sentences:
        claim_tokens = {
            t for t in re.findall(r"\b[a-z]{3,}\b", claim.lower())
            if t not in stopwords
        }
        if not claim_tokens:
            supported.append(claim)
            continue
        overlap = claim_tokens & corpus_tokens
        ratio   = len(overlap) / len(claim_tokens)
        if ratio >= min_support_ratio:
            supported.append(claim)
        else:
            unsupported.append(claim)

    clean_summary = ". ".join(supported).strip()
    if clean_summary and not clean_summary.endswith("."):
        clean_summary += "."

    return {
        "verified":      len(unsupported) == 0,
        "claims":        claim_sentences,
        "supported":     supported,
        "unsupported":   unsupported,
        "clean_summary": clean_summary or summary,
    }

def get_last_built_watermark(
    professor_name: str,
    conn: sqlite3.Connection,
) -> str | None:
    """Return the imported_at timestamp of the last sentiment build for this professor."""
    row = conn.execute(
        """
        SELECT imported_at
        FROM professor_sentiment_features
        WHERE professor_name = ?
        """,
        (professor_name,),
    ).fetchone()
    if row is None:
        return None
    val = row[0] if not hasattr(row, "keys") else row["imported_at"]
    return str(val).strip() if val else None


def fetch_new_reviews_since(
    professor_name: str,
    since_iso: str | None,
    conn: sqlite3.Connection,
) -> list[str]:
    """
    Return review texts newer than `since_iso` (ISO-8601 string).
    If since_iso is None, returns all reviews.
    """
    if since_iso:
        rows = conn.execute(
            """
            SELECT review_text
            FROM professor_rmp_reviews
            WHERE professor_name = ?
              AND fetched_at > ?
              AND review_text IS NOT NULL
              AND TRIM(review_text) != ''
            ORDER BY fetched_at DESC
            """,
            (professor_name, since_iso),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT review_text
            FROM professor_rmp_reviews
            WHERE professor_name = ?
              AND review_text IS NOT NULL
              AND TRIM(review_text) != ''
            ORDER BY fetched_at DESC
            """,
            (professor_name,),
        ).fetchall()
    return [str(r[0] if not hasattr(r, "keys") else r["review_text"]).strip() for r in rows]


def needs_rebuild(professor_name: str, conn: sqlite3.Connection) -> bool:
    """
    Return True if any review was fetched after the last sentiment build,
    or if the professor has no sentiment row at all.
    """
    watermark = get_last_built_watermark(professor_name, conn)
    if watermark is None:
        return True
    row = conn.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM professor_rmp_reviews
        WHERE professor_name = ?
          AND fetched_at > ?
        """,
        (professor_name, watermark),
    ).fetchone()
    cnt = row[0] if not hasattr(row, "keys") else row["cnt"]
    return int(cnt or 0) > 0


def detect_sentiment_anomaly(
    professor_name: str,
    new_score: float,
    conn: sqlite3.Connection,
    *,
    threshold: float = 0.20,
) -> dict[str, Any]:
    """
    Compare `new_score` to the stored final_sentiment_score.
    Flag as anomaly if |delta| >= threshold.

    Returns:
        {
          "is_anomaly":   bool,
          "delta":        float | None,
          "old_score":    float | None,
          "new_score":    float,
          "direction":    "improved" | "declined" | "unchanged" | "no_history",
          "message":      str,
        }
    """
    row = conn.execute(
        """
        SELECT final_sentiment_score, imported_at
        FROM professor_sentiment_features
        WHERE professor_name = ?
        """,
        (professor_name,),
    ).fetchone()

    if row is None:
        return {
            "is_anomaly": False,
            "delta":      None,
            "old_score":  None,
            "new_score":  new_score,
            "direction":  "no_history",
            "message":    f"No prior sentiment score for {professor_name}.",
        }

    old_score = float(row[0] if not hasattr(row, "keys") else row["final_sentiment_score"] or 0.0)
    delta     = new_score - old_score
    is_anomaly = abs(delta) >= threshold

    if delta > 0.05:
        direction = "improved"
    elif delta < -0.05:
        direction = "declined"
    else:
        direction = "unchanged"

    message = (
        f"ANOMALY: {professor_name} sentiment changed by {delta:+.3f} "
        f"({old_score:.3f} → {new_score:.3f}). Manual review recommended."
        if is_anomaly
        else f"{professor_name}: sentiment change {delta:+.3f} within normal range."
    )

    return {
        "is_anomaly": is_anomaly,
        "delta":      round(delta, 4),
        "old_score":  round(old_score, 4),
        "new_score":  round(new_score, 4),
        "direction":  direction,
        "message":    message,
    }

def build_professor_sentiment_explanation(
    professor_name: str,
    conn: sqlite3.Connection,
    *,
    endpoint: str | None = None,
    model: str = "llama3.1",
    api_key: str | None = None,
    timeout: int = 30,
    max_excerpts: int = 3,
) -> dict[str, Any]:
    """
    Build a rich sentiment explanation for a single professor. Suitable for
    GET /advisor/professor/{name}/sentiment.

    Returns:
        {
          "professor_name":       str,
          "overall_score":        float | None,
          "confidence_interval":  {"score", "low", "high", "margin"},
          "sentiment_label":      str | None,
          "summary":              str | None,
          "pros":                 list[str],
          "cons":                 list[str],
          "trend":                dict,           # from compute_sentiment_trend
          "tag_breakdown":        dict,           # from compute_tag_sentiment_breakdown
          "supporting_excerpts":  list[str],      # paraphrased-safe short snippets
          "structured":           dict | None,    # multi-dimension scores
        }
    """
    feat_row = conn.execute(
        """
        SELECT rating, difficulty, would_take_again_pct, review_count,
               final_sentiment_score, llm_sentiment_label,
               llm_sentiment_summary, llm_sentiment_pros_json,
               llm_sentiment_cons_json
        FROM professor_sentiment_features
        WHERE professor_name = ?
        """,
        (professor_name,),
    ).fetchone()

    if feat_row is None:
        return {
            "professor_name":      professor_name,
            "overall_score":       None,
            "confidence_interval": compute_confidence_interval(0.0, 0),
            "sentiment_label":     None,
            "summary":             None,
            "pros":                [],
            "cons":                [],
            "trend":               {"trend": "insufficient_data", "bucket_counts": {}},
            "tag_breakdown":       {},
            "supporting_excerpts": [],
            "structured":          None,
        }

    def _col(row: Any, key: str, idx: int) -> Any:
        return row[key] if hasattr(row, "keys") else row[idx]

    rating     = float(_col(feat_row, "rating", 0) or 0.0)
    difficulty = _col(feat_row, "difficulty", 1)
    wta        = _col(feat_row, "would_take_again_pct", 2)
    rev_count  = int(_col(feat_row, "review_count", 3) or 0)
    score      = float(_col(feat_row, "final_sentiment_score", 4) or 0.0)
    label      = str(_col(feat_row, "llm_sentiment_label", 5) or "")
    summary    = str(_col(feat_row, "llm_sentiment_summary", 6) or "")

    try:
        pros = json.loads(_col(feat_row, "llm_sentiment_pros_json", 7) or "[]")
    except (json.JSONDecodeError, TypeError):
        pros = []
    try:
        cons = json.loads(_col(feat_row, "llm_sentiment_cons_json", 8) or "[]")
    except (json.JSONDecodeError, TypeError):
        cons = []

    ci    = compute_confidence_interval(rating, rev_count)
    trend = compute_sentiment_trend(professor_name, conn)
    tags  = compute_tag_sentiment_breakdown(
        professor_name, conn,
        endpoint=endpoint, model=model, api_key=api_key, timeout=timeout,
    )

    review_rows = conn.execute(
        """
        SELECT review_text
        FROM professor_rmp_reviews
        WHERE professor_name = ?
          AND review_text IS NOT NULL
          AND LENGTH(TRIM(review_text)) > 20
        ORDER BY quality DESC
        LIMIT ?
        """,
        (professor_name, max_excerpts * 3),
    ).fetchall()

    excerpts: list[str] = []
    for rrow in review_rows:
        text = str(rrow[0] if not hasattr(rrow, "keys") else rrow["review_text"]).strip()
        first_sentence = re.split(r"[.!?]", text)[0].strip()
        snippet = first_sentence[:120].strip()
        if len(snippet) >= 20 and snippet not in excerpts:
            excerpts.append(snippet)
        if len(excerpts) >= max_excerpts:
            break
            
    structured: dict[str, Any] | None = None
    if endpoint:
        all_texts = fetch_new_reviews_since(professor_name, None, conn)[:8]
        if all_texts:
            structured = extract_structured_sentiment(
                all_texts,
                rating=rating,
                difficulty=float(difficulty) if difficulty else None,
                would_take_again_pct=float(wta) if wta else None,
                review_count=rev_count,
                endpoint=endpoint,
                model=model,
                api_key=api_key,
                timeout=timeout,
            )

    return {
        "professor_name":      professor_name,
        "overall_score":       round(score, 4),
        "confidence_interval": ci,
        "sentiment_label":     label or None,
        "summary":             summary or None,
        "pros":                [str(p) for p in pros if p],
        "cons":                [str(c) for c in cons if c],
        "trend":               trend,
        "tag_breakdown":       tags,
        "supporting_excerpts": excerpts,
        "structured":          structured,
    }

def rank_sections_for_course(
    course_code: str,
    sections: list[dict[str, Any]],
    *,
    sentiment_by_professor: dict[str, float],
    structured_by_professor: dict[str, dict[str, Any]] | None = None,
    weight_vector: dict[str, float] | None = None,
    time_preference_scores: dict[str, float] | None = None,
    unit_value: float = 0.5,
    prereq_unlock_value: float = 0.3,
) -> list[dict[str, Any]]:
    """
    Rank all sections of `course_code` using a multi-signal score:

        score = w_sentiment * sentiment_score
              + w_time      * time_pref_score
              + w_unit      * unit_value        (same for all sections)
              + w_prereq    * prereq_unlock      (same for all sections)

    Each section dict should have keys: instructor, days_times, [units].
    Returns sections sorted best-first with a `section_score` field added.

    Args:
        sections:               list of section metadata dicts
        sentiment_by_professor: pre-loaded {norm_name: score} mapping
        structured_by_professor: optional {norm_name: structured_dims} mapping
        weight_vector:          from build_preference_weight_vector()
        time_preference_scores: {days_times: 0–1 score} for student time prefs
        unit_value:             normalized unit contribution (same for all)
        prereq_unlock_value:    how much this course unlocks prereqs (same for all)
    """
    if not sections:
        return []

    wv = weight_vector or {
        "teaching_clarity":  0.35,
        "grading_fairness":  0.25,
        "accessibility":     0.20,
        "overall_sentiment": 0.20,
    }

    # Weights for the four ranking signals
    w_sentiment = 0.40
    w_time      = 0.30
    w_unit      = 0.15
    w_prereq    = 0.15

    def _norm_name(name: str | None) -> str:
        return re.sub(r"\s+", " ", (name or "")).strip().lower()

    scored: list[dict[str, Any]] = []
    for section in sections:
        instructor = str(section.get("instructor") or "").strip()
        days_times = str(section.get("days_times") or "").strip()
        norm_instr = _norm_name(instructor)

        raw_sentiment = sentiment_by_professor.get(norm_instr, 0.5)
        if structured_by_professor and norm_instr in structured_by_professor:
            struct = structured_by_professor[norm_instr]
            raw_sentiment = score_professor_with_weights(struct, wv)

        time_score = (time_preference_scores or {}).get(days_times, 0.5)

        composite = (
            w_sentiment * raw_sentiment
            + w_time    * time_score
            + w_unit    * unit_value
            + w_prereq  * prereq_unlock_value
        )

        scored.append({**section, "section_score": round(composite, 4)})

    scored.sort(key=lambda s: s["section_score"], reverse=True)
    return scored


def ensure_extended_schema(conn: sqlite3.Connection) -> None:
    """
    Idempotently add new columns to professor_sentiment_features for the
    extended pipeline features. Safe to run multiple times.
    """
    existing = {
        row[1]
        for row in conn.execute("PRAGMA table_info(professor_sentiment_features)").fetchall()
    }

    new_columns = [
        ("sentiment_trend",            "TEXT"),      # JSON: trend dict
        ("tag_sentiment_json",         "TEXT"),      # JSON: per-tag breakdown
        ("course_sentiment_json",      "TEXT"),      # JSON: per-course sentiment
        ("score_low",                  "REAL"),      # Wilson CI lower bound
        ("score_high",                 "REAL"),      # Wilson CI upper bound
        ("score_margin",               "REAL"),      # CI margin
        ("structured_sentiment_json",  "TEXT"),      # JSON: multi-dimension scores
        ("hallucination_check_json",   "TEXT"),      # JSON: claim verification
        ("anomaly_json",               "TEXT"),      # JSON: anomaly detection result
        ("last_incremental_built_at",  "TEXT"),      # watermark for incremental refresh
    ]

    for col_name, col_type in new_columns:
        if col_name not in existing:
            conn.execute(
                f"ALTER TABLE professor_sentiment_features ADD COLUMN {col_name} {col_type}"
            )
    conn.commit()