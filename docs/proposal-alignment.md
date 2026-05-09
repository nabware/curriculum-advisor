# Capstone Proposal Alignment

This document maps every objective and deliverable in
`course_files_export_text/Capstone Project Proposal.txt` to concrete artifacts
in this repository. It supersedes earlier partial-coverage notes once the
conversational interface and prerequisite DAG were added.

## Objective-by-Objective Coverage

### 1. Web-based **conversational** AI system that generates semester course recommendations
**Status: Implemented.**

- Frontend: chat UI in `frontend/index.html` and `frontend/js/app.js` —
  message bubbles, single text input, rolling conversation state, follow-up
  message support.
- Backend: `POST /advisor/chat` (`backend/app/api/routes/advisor.py`).
- Orchestration: `backend/app/services/chat_service.py`.
- LLM: Llama 3.2 3B via Ollama for runtime intent extraction and per-course
  rationale generation; regex + template fallback when Ollama is unavailable.
- "Each course is suggested with a natural-language explanation" satisfied via
  `RecommendedCourse.rationale` filled by `_attach_rationales(...)`.

### 2. **Deterministic prerequisite validation** mechanism using a structured **course dependency graph** to ensure **zero prerequisite violations**
**Status: Implemented.**

- DAG storage:
  - `course_prerequisites` (DNF: AND across `clause_index`, OR within a
    clause; supports `concurrent_allowed` and `recommended_only` flags).
  - `course_prerequisite_notes` for non-course free-form prereqs
    ("upper-division standing", "permission of instructor"). These are
    informational and never block.
- Parser: `scripts/import_course_prerequisites.py` (handles `or`/`and`/`,`/`;`
  conventions, `(may be taken concurrently)`, `is recommended`, dedup).
- Validator: `backend/app/services/prerequisite_service.py`
  (`PrerequisiteService.validate / filter_takeable / build_prerequisite_graph`).
- Wired into `AdvisorService.recommend`; blocked candidates returned in
  `AdvisorResponse.prerequisite_blocked_courses` for UI transparency.
- Evaluation: `scripts/evaluate_sentiment_impact.py` now reports
  `prerequisite_violation_rate` per scenario and aggregate. Current numbers
  on the included scenario packs:
  - `evaluation_scenarios.csv`: 0.0000 (8 scenarios)
  - `evaluation_scenarios_dsai_edge.csv`: 0.0000 (16 scenarios)

### 3. Sentiment extraction pipeline (unstructured → structured features)
**Status: Already implemented prior to this revision; unchanged.**

- `scripts/refresh_professor_rmp_data.py` pulls reviews into SQLite.
- `scripts/build_professor_sentiment_features.py` calls Llama 3.1 8B for
  review summarization and writes confidence-shrunk per-professor sentiment
  features to `professor_sentiment_features`.

### 4. Multi-objective ranking that integrates academic relevance, degree progress, and instructor sentiment
**Status: Already implemented; unchanged.**

- `AdvisorService._resolve_course_objective` weights progress / workload /
  sentiment / difficulty with per-request override support.
- Ranked selection inside `_select_group_courses` enumerates feasible
  combinations and chooses the highest-objective subset.

### 5. Compare baseline vs sentiment-aware recommendations
**Status: Already implemented; unchanged.**

- `scripts/evaluate_sentiment_impact.py` runs both modes per scenario and
  reports overlap@k, sentiment lift, and latency delta.
- Result tables in `data/processed/` and `docs/final-evaluation-comparison.md`.

## Project Description Coverage

| Proposal claim | Implementation |
|---|---|
| "Conversational interface" | `POST /advisor/chat` + chat UI |
| "Recommended schedule that satisfies prerequisite constraints" | `PrerequisiteService` filter inside `AdvisorService.recommend` |
| "Explaining, in natural language, why each course is suggested" | `generate_course_rationales` + template fallback |
| "Structured course database, prereq engine modeled as a directed graph" | `course_prerequisites` + `PrerequisiteService.build_prerequisite_graph()` |
| "Sentiment-processing component" | `build_professor_sentiment_features.py` + `llama_sentiment_service.py` |
| "Multi-objective scoring function" | `AdvisorService._resolve_course_objective` |

## Technical Approach Coverage

| Proposal claim | Implementation |
|---|---|
| "Pre-trained LLM accessed through an API to power conversational interface" | Llama 3.2 3B via Ollama at `http://localhost:11434/v1/chat/completions` |
| "LLM will interpret user inputs" | `extract_chat_intent` |
| "LLM will generate natural language explanations for recommendations" | `generate_course_rationales` |
| "Assist in extracting structured sentiment indicators from professor review text" | `summarize_review_texts` (Llama 3.1 8B at build time) |
| "HTML, CSS, JavaScript" | `frontend/` |
| "Asynchronous API calls" | `frontend/js/api.js` (`fetch`) |
| "Backend handles database queries, prerequisite validation, sentiment processing, LLM API" | All of the above |
| "Course and prerequisite data from official catalogs in a relational database" | `data/raw/class_descriptions/` parsed by `import_course_prerequisites.py` into SQLite |
| "Professor reviews from publicly available datasets or simulated" | `refresh_professor_rmp_data.py` (live) + `generate_synthetic_reviews.py` (simulated fallback) |

## Expected-Outcomes Coverage

| Proposal expectation | Status |
|---|---|
| Functional web-based curriculum advisor | Yes |
| Sentiment-aware course recommendations | Yes |
| Working prototype | Yes |
| Source code repository | This repo |
| Final report and presentation | Out of scope for code; doc artifacts under `docs/` |
| **Prerequisite violation rate** | `0.0000` on packaged scenario sets |
| Ranking consistency (overlap@k) | Reported per scenario |
| Response latency | Reported per scenario; runtime chat path measured separately (~5–10 s warm with Llama 3.2 3B on CPU) |
| Baseline vs sentiment-aware comparison | `evaluate_sentiment_impact.py` |

## CPU-laptop Demo Plan

The runtime chat is intentionally architected to stay responsive on CPU-only
laptops:

- **Llama 3.2 3B (Q4_K_M, ~2 GB)** is the default chat model. On a typical
  laptop with 16 GB RAM, the warm intent-extraction call returns in roughly
  2–4 s; the per-course rationale call adds another 3–5 s, so a full
  recommendation turn is usually under 10 s.
- The model is **warmed at backend startup** by a daemon thread so the first
  user message does not pay the model-load cost.
- Determinism: both LLM calls use `temperature=0`. The plan generation itself
  remains entirely deterministic regardless of LLM output.
- **No-GPU fallback path** kicks in transparently:
  - intent extraction → regex + degree-name matching
  - per-course rationales → templates pre-built by
    `scripts/prebuild_demo_rationales.py` and stored in
    `course_descriptions.recommendation_rationale_template`.
- The deterministic prerequisite validator runs in single-digit milliseconds
  on the in-memory clause map.

For demo day:

1. `ollama pull llama3.2:3b` on each laptop (one-time, ~2 GB).
2. `bash scripts/run_backend.sh` (auto-starts Ollama, fires warm-up).
3. `bash scripts/run_frontend.sh` (serves on port 5500).
4. Optionally pre-run the eval script with `--scenarios-csv` for a known
   scenario to confirm `prerequisite_violation_rate=0.0000` before the demo.
