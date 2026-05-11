from __future__ import annotations

import json
import os
import sqlite3
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.core.database import get_database_path
from app.models.schemas import (
    ConfidenceInterval,
    ProfessorSentimentExplanation,
    SentimentRankingRequest,
    SentimentTrend,
    StructuredSentiment,
    TagSentimentEntry,
)
from app.services.sentiment_pipeline import (
    build_professor_sentiment_explanation,
    build_preference_weight_vector,
    compute_confidence_interval,
    compute_course_specific_sentiment,
    compute_sentiment_trend,
    compute_tag_sentiment_breakdown,
    score_professor_with_weights,
)

router = APIRouter(prefix="/sentiment", tags=["sentiment"])

OLLAMA_ENDPOINT = os.environ.get(
    "CURRICULUM_ADVISOR_CHAT_ENDPOINT",
    "http://localhost:11434/v1/chat/completions",
)
SENTIMENT_MODEL = os.environ.get("CURRICULUM_ADVISOR_SENTIMENT_MODEL", "llama3.1")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(get_database_path())
    conn.row_factory = sqlite3.Row
    return conn


def _norm(name: str | None) -> str:
    return re.sub(r"\s+", " ", (name or "")).strip().lower()


def _find_professor(name: str, conn: sqlite3.Connection) -> str | None:
    """Fuzzy-find a professor name in professor_sentiment_features."""
    needle = _norm(name)
    rows = conn.execute(
        "SELECT professor_name FROM professor_sentiment_features"
    ).fetchall()
    # Exact normalized match
    for row in rows:
        if _norm(row["professor_name"]) == needle:
            return str(row["professor_name"])
    # Partial match
    for row in rows:
        if needle in _norm(row["professor_name"]) or _norm(row["professor_name"]) in needle:
            return str(row["professor_name"])
    return None


@router.get("/professor/{name}", response_model=ProfessorSentimentExplanation)
def get_professor_sentiment(
    name: str,
    include_llm: bool = Query(
        default=False,
        description="Set true to include LLM-generated structured sentiment (slow on CPU)",
    ),
) -> ProfessorSentimentExplanation:
    """
    Full sentiment explanation for a single professor.

    Returns overall score, confidence interval, trend, per-tag breakdown,
    supporting review excerpts, and (optionally) multi-dimension LLM scores.
    """
    with _connect() as conn:
        professor_name = _find_professor(name, conn)
        if not professor_name:
            raise HTTPException(status_code=404, detail=f"No sentiment data found for '{name}'")

        endpoint = OLLAMA_ENDPOINT if include_llm else None
        data = build_professor_sentiment_explanation(
            professor_name,
            conn,
            endpoint=endpoint,
            model=SENTIMENT_MODEL,
            timeout=30,
        )

    ci_data = data.get("confidence_interval") or {}
    trend_data = data.get("trend") or {}
    tag_data = data.get("tag_breakdown") or {}
    struct_data = data.get("structured")

    return ProfessorSentimentExplanation(
        professor_name=data["professor_name"],
        overall_score=data.get("overall_score"),
        confidence_interval=ConfidenceInterval(**ci_data) if ci_data else None,
        sentiment_label=data.get("sentiment_label"),
        summary=data.get("summary"),
        pros=data.get("pros") or [],
        cons=data.get("cons") or [],
        trend=SentimentTrend(**trend_data) if trend_data else None,
        tag_breakdown={
            tag: TagSentimentEntry(**entry)
            for tag, entry in tag_data.items()
        },
        supporting_excerpts=data.get("supporting_excerpts") or [],
        structured=StructuredSentiment(**struct_data) if struct_data else None,
    )


@router.get("/professor/{name}/trend", response_model=SentimentTrend)
def get_professor_trend(name: str) -> SentimentTrend:
    """Fast endpoint: return only the sentiment trend for a professor."""
    with _connect() as conn:
        professor_name = _find_professor(name, conn)
        if not professor_name:
            raise HTTPException(status_code=404, detail=f"No data found for '{name}'")
        trend = compute_sentiment_trend(professor_name, conn)
    return SentimentTrend(**trend)


@router.get("/professor/{name}/tags")
def get_professor_tag_breakdown(name: str) -> dict[str, Any]:
    """Return per-RMP-tag sentiment breakdown for a professor."""
    with _connect() as conn:
        professor_name = _find_professor(name, conn)
        if not professor_name:
            raise HTTPException(status_code=404, detail=f"No data found for '{name}'")
        tags = compute_tag_sentiment_breakdown(professor_name, conn)
    return {"professor_name": professor_name, "tags": tags}


@router.get("/sentiment/professor/{name}/courses")
def get_professor_course_sentiment(name: str) -> dict[str, Any]:
    """Return per-course sentiment breakdown for a professor."""
    with _connect() as conn:
        professor_name = _find_professor(name, conn)
        if not professor_name:
            raise HTTPException(status_code=404, detail=f"No data found for '{name}'")
        courses = compute_course_specific_sentiment(professor_name, conn)
    return {"professor_name": professor_name, "courses": courses}


@router.post("/rank-professors")
def rank_professors(payload: SentimentRankingRequest) -> dict[str, Any]:
    """
    Rank a list of professors using preference-weighted sentiment scoring.

    Optionally supply course_code to use course-specific sentiment where
    available, and preferences_text to shift dimension weights toward the
    student's stated priorities (e.g. "I need clear explanations").
    """
    weight_vector = build_preference_weight_vector(payload.preferences_text)

    with _connect() as conn:
        ranked: list[dict[str, Any]] = []

        for name in payload.professor_names:
            professor_name = _find_professor(name, conn)
            if not professor_name:
                ranked.append({
                    "requested_name": name,
                    "matched_name":   None,
                    "composite_score": None,
                    "confidence_interval": None,
                    "sentiment_label": None,
                    "trend": None,
                    "note": "Not found in sentiment database",
                })
                continue

            feat_row = conn.execute(
                """
                SELECT final_sentiment_score, llm_sentiment_label,
                       rating, num_ratings,
                       structured_sentiment_json, sentiment_trend,
                       score_low, score_high, score_margin
                FROM professor_sentiment_features
                WHERE professor_name = ?
                """,
                (professor_name,),
            ).fetchone()

            if feat_row is None:
                ranked.append({
                    "requested_name": name,
                    "matched_name":   professor_name,
                    "composite_score": None,
                    "confidence_interval": None,
                    "sentiment_label": None,
                    "trend": None,
                    "note": "Sentiment features not built yet",
                })
                continue

            base_score = float(feat_row["final_sentiment_score"] or 0.0)

            composite_score = base_score
            structured_raw  = feat_row["structured_sentiment_json"]
            if structured_raw:
                try:
                    structured = json.loads(structured_raw)
                    composite_score = score_professor_with_weights(structured, weight_vector)
                except (json.JSONDecodeError, TypeError):
                    pass

            if payload.course_code:
                course_sent = compute_course_specific_sentiment(professor_name, conn)
                course_key  = payload.course_code.strip().upper()
                if course_key in course_sent:
                    course_score    = course_sent[course_key]["base_sentiment"]
                    composite_score = 0.60 * composite_score + 0.40 * course_score

            ci = ConfidenceInterval(
                score=base_score,
                low=float(feat_row["score_low"] or 0.0),
                high=float(feat_row["score_high"] or 1.0),
                margin=float(feat_row["score_margin"] or 1.0),
            )

            trend_raw = feat_row["sentiment_trend"]
            trend_dict: dict | None = None
            if trend_raw:
                try:
                    trend_dict = json.loads(trend_raw)
                except (json.JSONDecodeError, TypeError):
                    pass

            ranked.append({
                "requested_name":    name,
                "matched_name":      professor_name,
                "composite_score":   round(composite_score, 4),
                "base_score":        round(base_score, 4),
                "confidence_interval": ci.model_dump(),
                "sentiment_label":   str(feat_row["llm_sentiment_label"] or ""),
                "trend":             trend_dict,
                "weight_vector_used": weight_vector,
            })

    ranked.sort(key=lambda r: r.get("composite_score") or 0.0, reverse=True)
    return {
        "ranked_professors": ranked,
        "weight_vector":     weight_vector,
        "preferences_text":  payload.preferences_text,
    }