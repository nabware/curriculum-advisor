from __future__ import annotations

import json
import re
import urllib.request
from functools import lru_cache

SCHOOL_ID = "U2FuIEZyYW5jaXNjbyBTdGF0ZSBVbml2ZXJzaXR5"  

_GQL_URL = "https://www.ratemyprofessors.com/graphql"

_SCHOOL_QUERY = """
query SchoolSearchQuery($query: SchoolSearchQuery!) {
  newSearch {
    schools(query: $query) {
      edges {
        node {
          id
          name
          city
          state
        }
      }
    }
  }
}
"""

_PROFESSOR_QUERY = """
query TeacherSearchQuery($text: String!, $schoolID: ID) {
  newSearch {
    teachers(query: { text: $text, schoolID: $schoolID }, first: 5) {
      edges {
        node {
          id
          firstName
          lastName
          department
          avgRating
          avgDifficulty
          numRatings
          wouldTakeAgainPercent
          school {
            id
            name
          }
        }
      }
    }
  }
}
"""


def _graphql(query: str, variables: dict) -> dict:
    payload = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        _GQL_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Basic dGVzdDp0ZXN0",  # RMP public token
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.ratemyprofessors.com/",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode())


@lru_cache(maxsize=1)
def get_school_id(school_name: str) -> str | None:
    """Look up the base64 school ID by name. Cached after first call."""
    try:
        data = _graphql(_SCHOOL_QUERY, {"query": {"text": school_name}})
        edges = data["data"]["newSearch"]["schools"]["edges"]
        if not edges:
            return None
        return edges[0]["node"]["id"]
    except Exception:
        return None


def _name_similarity(a: str, b: str) -> float:
    """Simple token overlap ratio."""
    tokens_a = set(re.sub(r"[^a-z ]", "", a.lower()).split())
    tokens_b = set(re.sub(r"[^a-z ]", "", b.lower()).split())
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / max(len(tokens_a), len(tokens_b))


def fetch_professor_rating(
    professor_name: str,
    school_id: str = SCHOOL_ID,
) -> dict | None:
    """
    Returns a dict with RMP data for the best-matching professor, or None.

    Keys: rating, difficulty, num_ratings, would_take_again_pct, rmp_url
    """
    if not professor_name or not professor_name.strip():
        return None

    last_name = professor_name.strip().split()[-1]

    try:
        data = _graphql(
            _PROFESSOR_QUERY,
            {"text": last_name, "schoolID": school_id},
        )
        edges = data["data"]["newSearch"]["teachers"]["edges"]
    except Exception:
        return None

    if not edges:
        return None

    best_node = None
    best_score = 0.0
    for edge in edges:
        node = edge["node"]
        full = f"{node['firstName']} {node['lastName']}"
        score = _name_similarity(professor_name, full)
        if score > best_score:
            best_score = score
            best_node = node

    if best_node is None or best_score < 0.4:
        return None

    try:
        import base64
        numeric_id = base64.b64decode(best_node["id"]).decode().split("-")[-1]
        rmp_url = f"https://www.ratemyprofessors.com/professor/{numeric_id}"
    except Exception:
        rmp_url = "https://www.ratemyprofessors.com"

    avg_rating = best_node.get("avgRating")
    avg_difficulty = best_node.get("avgDifficulty")
    num_ratings = best_node.get("numRatings", 0)
    would_take_again = best_node.get("wouldTakeAgainPercent")

    if num_ratings == 0:
        return None

    return {
        "rating": round(float(avg_rating), 1) if avg_rating is not None else None,
        "difficulty": round(float(avg_difficulty), 1) if avg_difficulty is not None else None,
        "num_ratings": num_ratings,
        "would_take_again_pct": round(float(would_take_again), 1) if would_take_again is not None and would_take_again >= 0 else None,
        "rmp_url": rmp_url,
    }