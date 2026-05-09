# Architecture

## Frontend
- Stack: static HTML, CSS, and vanilla JavaScript.
- Conversational entry point in `frontend/index.html` and `frontend/js/app.js`:
  - Chat thread with user/assistant message bubbles.
  - Single text input that POSTs to `/advisor/chat` with rolling
    `state` and `history` (last 8 turns).
  - Side controls retained for blocked time windows and a per-message
    `Max units` override.
- Recommendation panel re-renders on every chat turn that produces a plan:
  - Course cards with rationale (italic block), prereq line, schedule, and
    professor card (image, sentiment pill, RMP ratings).
  - "Excluded by Prerequisite Validation" section listing courses removed by
    the deterministic prereq filter, with the unmet-clause summary.
  - Degree progress (`total_units_selected` / `total_units_required`).
  - Day/time schedule overview.

## Backend
- Stack: FastAPI + Pydantic + SQLite.
- Route layer: `backend/app/api/routes`.
  - `GET /health`
  - `GET /advisor/degrees`
  - `POST /advisor/recommend` — structured request used by eval scripts.
  - `POST /advisor/chat` — conversational orchestrator.
- Service layer:
  - `backend/app/services/chat_service.py` (`ChatService`):
    - Calls `extract_chat_intent` (Llama 3.2 3B) to turn free-form text into
      structured intent JSON; falls back to regex-based intent extraction if
      Ollama is unreachable or the response can't be parsed.
    - Merges intent into rolling `ChatState`.
    - Delegates plan generation to `AdvisorService.recommend`.
    - Calls `generate_course_rationales` (Llama 3.2 3B) for per-course
      one-sentence reasons; uses pre-built templates from
      `recommendation_rationale_template` as fallback.
    - Composes a natural-language assistant reply.
    - Warm-up: a daemon thread on FastAPI startup fires one intent call so the
      runtime model is in memory before the first user request.
  - `backend/app/services/prerequisite_service.py` (`PrerequisiteService`):
    - Loads `course_prerequisites` into an in-memory DNF map (clauses are
      AND'd; options within a clause are OR'd).
    - `validate(course_code, completed, currently_enrolled)` returns a
      `PrerequisiteValidationResult` with unmet clauses + satisfying courses.
    - `filter_takeable(...)` returns `(takeable_codes, blocked_results)`.
    - Cycle-safe: validation only inspects direct prereqs.
  - `backend/app/services/advisor_service.py` (`AdvisorService`):
    - Resolves selected degree.
    - Builds requirement-group-aware candidate sets.
    - **Drops candidates that fail `PrerequisiteService.validate`** (collects
      them into `prerequisite_blocked_courses` for transparency).
    - Selects a concise set of courses per requirement group via knapsack-style
      enumeration with multi-objective tie-breaking (progress / workload /
      sentiment / difficulty).
    - Applies term filtering, schedule conflict removal, blocked-window
      filtering, and the semester unit cap.
    - Enriches with descriptions, professor metadata, RMP, and sentiment.
- Static assets:
  - Professor images served from `data/raw/professor_images` and mounted at
    `/assets/professor-images/*`.

## Data Layer
- SQLite file: `data/seed/curriculum_advisor.db`
- Core serving tables:
  - `degree_programs`
  - `requirement_groups`
  - `requirement_group_courses`
  - `class_schedules`
  - `course_descriptions` (extra column: `recommendation_rationale_template`)
  - `course_prerequisites` (DNF: `(course_code, clause_index, prereq_course_code, concurrent_allowed, recommended_only, raw_text)`)
  - `course_prerequisite_notes` (free-form non-course prereqs, informational)
  - `professor_profiles`
  - `professor_sentiment_features`

## Data Pipeline Scripts
- `scripts/import_degree_requirements.py` — degree requirement pages and totals.
- `scripts/build_degree_requirement_model.py` — normalized serving tables.
- `scripts/import_class_schedules.py` — schedule/term/section data.
- `scripts/import_course_metadata.py` — course descriptions and professor profiles.
- `scripts/import_course_prerequisites.py` — parses prereq sentences from the
  catalog HTML into the DNF prereq table and an informational notes table.
- `scripts/build_professor_sentiment_features.py` — confidence-aware sentiment
  features written to `professor_sentiment_features` and a CSV export.
- `scripts/prebuild_demo_rationales.py` — caches per-course rationale templates
  in `course_descriptions.recommendation_rationale_template` so the chat UI
  has a graceful fallback when the runtime LLM is unavailable.

## Evaluation
- `scripts/evaluate_sentiment_impact.py` reports per-scenario:
  - overlap@k between baseline and sentiment-aware recommendations,
  - mean sentiment lift,
  - latency delta,
  - **prerequisite violation rate** (validated against the prereq DAG, with
    transcript-text expansion mirrored from `AdvisorService.recommend`).
- Aggregate prereq violation rate is `0.0000` across the included scenario
  packs, demonstrating the proposal's "zero prerequisite violations" target.

## Runtime LLM Path (CPU-friendly)
- Default chat model: `llama3.2:3b` via Ollama at
  `http://localhost:11434/v1/chat/completions` (Q4 quantization, ~2 GB on disk).
- Two narrow LLM jobs per turn: (1) intent extraction, (2) per-course
  rationale generation. Both use temperature 0 for repeatability.
- Warmed at backend startup so first user message isn't a cold-start hit.
- Fallback path requires no GPU and no network: regex intent + cached
  rationale templates.
