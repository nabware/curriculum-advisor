# Curriculum Advisor

Conversational, sentiment-aware semester planning that respects course
prerequisites deterministically.

Current stack:
- Frontend: HTML, CSS, vanilla JavaScript (chat UI, AJAX via `fetch`)
- Backend: FastAPI + Pydantic
- Database: SQLite (default for development)
- Runtime LLM: Llama 3.2 3B via Ollama (intent extraction + per-course rationales)
- Build-time LLM: Llama 3.1 8B via Ollama (professor sentiment summaries)

## Prerequisites

Before cloning or running the scripts, ensure you have:

1. **Python 3.8+** - Required for backend and data scripts
   - macOS: `brew install python3`
   - Ubuntu/Debian: `sudo apt-get install python3 python3-venv`
   - Windows: [Download from python.org](https://www.python.org)

2. **Ollama** - powers both the runtime chat and the offline sentiment build
   - **macOS/Linux**: `curl -fsSL https://ollama.ai/install.sh | sh`
   - **Windows**: [Download installer](https://ollama.ai/download)
   - After install, pull the two models:
     ```bash
     ollama pull llama3.2:3b   # runtime chat (~2 GB) — used live
     ollama pull llama3.1      # sentiment build (~4.9 GB) — used offline only
     ```
   - Then run `run_backend.sh` — it auto-starts the Ollama service and warms up
     the chat model on backend boot so the first user message isn't a cold start.

If Ollama is not running, the conversational interface falls back gracefully
to keyword intent parsing and template-based course rationales (templates are
built once via `scripts/prebuild_demo_rationales.py`). Sentiment scoring
similarly falls back to ratings-only when the build-time LLM is unavailable.

## Quick Start

1. Start backend:

```bash
bash scripts/run_backend.sh
```

The script auto-creates `backend/.venv`, installs dependencies when needed, and starts the API.

2. Start frontend in a second terminal:

```bash
bash scripts/run_frontend.sh
```

The script serves `frontend/` on port `5500`.

3. Open:
- Frontend: http://localhost:5500
- Backend health: http://localhost:8000/health

## First-Clone Data Setup

After cloning, run these once to build the local SQLite data used by the project:

```bash
python scripts/import_degree_requirements.py
python scripts/build_degree_requirement_model.py
python scripts/import_class_schedules.py
python scripts/import_course_metadata.py
python scripts/import_course_prerequisites.py     # NEW: builds the prereq DAG
python scripts/build_professor_sentiment_features.py
python scripts/prebuild_demo_rationales.py        # NEW: cached chat rationales
```

### Real Reviews from RateMyProfessors

The refresh job pulls review data for all SFSU professors from the `ratemyprofessors-client` GraphQL API, stores the profiles and raw reviews in SQLite, and then rebuilds professor sentiment features from that database data.

Review text still drives the AI summary. RMP review tags are now scored as a separate signal and blended into the final sentiment score, instead of being merged into the text summary.

```bash
pip install ratemyprofessors-client
python scripts/refresh_professor_rmp_data.py
python scripts/build_professor_sentiment_features.py
```

To refresh the local database from live RateMyProfessors data and rebuild the sentiment features in one pass, run this maintenance job:

```bash
python scripts/refresh_professor_rmp_data.py
```

This refreshes `data/seed/curriculum_advisor.db`, the review cache, the professor RMP profile exports, and the sentiment feature rows from live `ratemyprofessors-client` data. The app itself reads only from the local SQLite database.

### Sentiment Pipeline

The sentiment builder now reads from `professor_rmp_reviews` in SQLite, calls Ollama at `http://localhost:11434/v1/chat/completions` for LLM-based sentiment analysis, and stores the resulting summaries and scores in `professor_sentiment_features`.

Expected SQLite file:
- `data/seed/curriculum_advisor.db`

Expected core tables:
- `degree_requirements`
- `degree_programs`
- `requirement_groups`
- `requirement_group_courses`
- `class_schedules`
- `course_descriptions` (with `recommendation_rationale_template` column)
- `course_prerequisites` (DNF: AND across `clause_index`, OR within a clause)
- `course_prerequisite_notes` (free-form non-course prereqs, informational only)
- `professor_profiles`
- `professor_sentiment_features`

## Where To Look

- Project architecture: [docs/architecture.md](docs/architecture.md)
- **Capstone proposal alignment (full)**: [docs/proposal-alignment.md](docs/proposal-alignment.md)
- Team ownership split: [docs/team-ownership.md](docs/team-ownership.md)
- Detailed startup and API test commands: [docs/quickstart.md](docs/quickstart.md)
- Proposal alignment for data pipeline scope: [docs/proposal-data-pipeline-alignment.md](docs/proposal-data-pipeline-alignment.md)
- Final evaluation comparison table: [docs/final-evaluation-comparison.md](docs/final-evaluation-comparison.md)

## Suggested Team Workflow

- Person A: API + schemas in `backend/app/api` and `backend/app/models`
- Person B: frontend in `frontend/`
- Person C: ranking/sentiment/data pipeline in `backend/app/services` and `data/`

Keep PRs small and avoid cross-area edits unless coordinated.

## Database Direction

For a minimal, easy-to-use setup, use SQLite first.

- Why now: zero setup, works well for local development and demos.
- Suggested file location: `data/seed/curriculum_advisor.db` (or `backend/curriculum_advisor.db`).
- Future upgrade path: PostgreSQL when multi-user concurrency and deployment scale up.

### Import Degree Requirements Into SQLite

If you place degree requirement HTML files in `data/raw/degree_requirements`, run:

```bash
python scripts/import_degree_requirements.py
```

This recreates `degree_requirements` in `data/seed/curriculum_advisor.db`.
Current parser behavior is intentionally simple: groups are based on requirement `h3` headings.

### Build Lightweight Requirement Model (Multi-table)

To build the simplified serving model for advisor logic (degrees, requirement groups, and group course options), run:

```bash
python scripts/build_degree_requirement_model.py
```

This creates these tables in `data/seed/curriculum_advisor.db`:
- `degree_programs`
- `requirement_groups`
- `requirement_group_courses`

### Import Class Schedules Into SQLite

If you place class schedule HTML files in `data/raw/class_schedules`, run:

```bash
python scripts/import_class_schedules.py
```

This recreates `class_schedules` in `data/seed/curriculum_advisor.db`.

## Current API Endpoints

- GET `/health`
- GET `/advisor/degrees`
- POST `/advisor/recommend` — structured form-style request (used by eval scripts)
- POST `/advisor/chat` — conversational entry point; orchestrates LLM intent
  extraction, calls `recommend` deterministically, then attaches per-course
  rationales

## Current Recommendation Behavior

- **Conversational entry point**: `POST /advisor/chat` interprets a free-form
  message via Llama 3.2 3B (with a regex fallback), maintains rolling state,
  and delegates the deterministic plan generation to `AdvisorService.recommend`.
- **Deterministic prerequisite validation**: `PrerequisiteService` loads a DNF
  course-dependency graph from `course_prerequisites` and removes any candidate
  whose prereqs are not satisfied by the student's completed coursework.
  Removed courses are returned in `prerequisite_blocked_courses` with
  human-readable unmet-clause summaries.
- Requirement-group-aware recommendations from official catalog data.
- Term-filtered availability via class schedules.
- Greedy schedule conflict removal + blocked time-window filtering.
- Semester cap support via `max_units_per_semester`.
- Progress output using `total_units_selected` / `total_units_required`.
- Course enrichment with descriptions, professor names, professor images, RMP
  ratings/tags, and confidence-weighted sentiment scores.
- Per-course natural-language rationales from Llama 3.2 3B at runtime, with
  pre-built templates as fallback when Ollama is unavailable.

## Configuration

Optional environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `CURRICULUM_ADVISOR_CHAT_ENDPOINT` | `http://localhost:11434/v1/chat/completions` | Override the runtime LLM endpoint |
| `CURRICULUM_ADVISOR_CHAT_MODEL` | `llama3.2:3b` | Override the runtime LLM model name |
| `CURRICULUM_ADVISOR_DISABLE_CHAT_WARMUP` | unset | Skip the startup warm-up call (useful for tests / when Ollama is intentionally down) |
