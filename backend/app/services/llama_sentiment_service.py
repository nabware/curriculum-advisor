from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any


def _build_json_schema_prompt(review_texts: list[str]) -> str:
    joined_reviews = "\n\n".join(
        f"Review {index + 1}: {_trim_text(review, 500)}"
        for index, review in enumerate(review_texts)
    )
    return (
        "Analyze the following professor reviews and return strict JSON only. "
        "Use the reviews, not any outside knowledge. "
        "Return this schema exactly: "
        '{"sentiment_label":"positive|neutral|negative","sentiment_score":0.0,"summary":"...",'
        '"pros":["..."],"cons":["..."]}. '
        "sentiment_score must be a number from 0.0 to 1.0 where 1.0 means very positive. "
        "Keep summary to one or two sentences. "
        "If the reviews are mixed, label them neutral and keep the score near 0.5.\n\n"
        f"Reviews:\n{joined_reviews}"
    )


def _build_ollama_prompt(review_texts: list[str]) -> str:
    return _build_json_schema_prompt(review_texts)


def _build_chat_prompt(review_texts: list[str]) -> str:
    return _build_json_schema_prompt(review_texts)


def _trim_text(value: str, limit: int) -> str:
    cleaned = re.sub(r"\s+", " ", value).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _extract_json_object(text: str) -> dict[str, Any] | None:
    candidate = text.strip()
    if not candidate:
        return None

    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\s*```$", "", candidate)
        candidate = candidate.strip()

    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    start = candidate.find("{")
    end = candidate.rfind("}")
    if start < 0 or end <= start:
        return None

    try:
        parsed = json.loads(candidate[start : end + 1])
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _build_prompt(review_texts: list[str]) -> str:
    joined_reviews = "\n\n".join(
        f"Review {index + 1}: {_trim_text(review, 500)}"
        for index, review in enumerate(review_texts)
    )
    return (
        "Analyze the following professor reviews and return strict JSON only. "
        "Use the reviews, not any outside knowledge. "
        "Return this schema exactly: "
        '{"sentiment_label":"positive|neutral|negative","sentiment_score":0.0,"summary":"...",'
        '"pros":["..."],"cons":["..."]}. '
        "sentiment_score must be a number from 0.0 to 1.0 where 1.0 means very positive. "
        "Keep summary to one or two sentences. "
        "If the reviews are mixed, label them neutral and keep the score near 0.5.\n\n"
        f"Reviews:\n{joined_reviews}"
    )


def analyze_review_texts(
    review_texts: list[str],
    *,
    endpoint: str | None,
    model: str,
    api_key: str | None = None,
    timeout: int = 30,
) -> dict[str, Any] | None:
    cleaned_reviews = [re.sub(r"\s+", " ", review).strip() for review in review_texts if review and review.strip()]
    if not cleaned_reviews or not endpoint:
        return None

    prompt = _build_prompt(cleaned_reviews)
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a precise sentiment analysis engine. "
                    "Respond with valid JSON only and no markdown."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
    }

    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return None

    content = ""
    if isinstance(response_payload, dict):
        choices = response_payload.get("choices")
        if isinstance(choices, list) and choices:
            first_choice = choices[0]
            if isinstance(first_choice, dict):
                message = first_choice.get("message")
                if isinstance(message, dict):
                    content = str(message.get("content") or "")
                else:
                    content = str(first_choice.get("text") or "")
        if not content and isinstance(response_payload.get("response"), str):
            content = str(response_payload["response"])

    parsed = _extract_json_object(content)
    if not parsed:
        return None

    label = str(parsed.get("sentiment_label") or "neutral").strip().lower()
    if label not in {"positive", "neutral", "negative"}:
        label = "neutral"

    try:
        score = float(parsed.get("sentiment_score", 0.5))
    except (TypeError, ValueError):
        score = 0.5
    score = max(0.0, min(1.0, score))

    summary = str(parsed.get("summary") or "").strip()
    pros = parsed.get("pros") if isinstance(parsed.get("pros"), list) else []
    cons = parsed.get("cons") if isinstance(parsed.get("cons"), list) else []

    return {
        "sentiment_label": label,
        "sentiment_score": score,
        "summary": summary,
        "pros": [str(item).strip() for item in pros if str(item).strip()],
        "cons": [str(item).strip() for item in cons if str(item).strip()],
    }