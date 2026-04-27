# Curriculum Advisor

Web app for degree-aware starter semester planning.

Current stack:
- Frontend: HTML, CSS, JavaScript (AJAX via fetch)
- Backend: FastAPI
- Database: SQLite (default for development)

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
python scripts/build_professor_sentiment_features.py
```

Expected SQLite file:
- `data/seed/curriculum_advisor.db`

Expected core tables:
- `degree_requirements`
- `degree_programs`
- `requirement_groups`
- `requirement_group_courses`
- `class_schedules`
- `course_descriptions`
- `professor_profiles`
- `professor_sentiment_features`

## Where To Look

- Project architecture: [docs/architecture.md](docs/architecture.md)
- Team ownership split: [docs/team-ownership.md](docs/team-ownership.md)
- Detailed startup and API test commands: [docs/quickstart.md](docs/quickstart.md)
- Proposal alignment for data pipeline scope: [docs/proposal-data-pipeline-alignment.md](docs/proposal-data-pipeline-alignment.md)

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
- POST `/advisor/recommend`

## Current Recommendation Behavior

- Degree-first onboarding from `GET /advisor/degrees`.
- Requirement-group-aware recommendations.
- Term-filtered availability via class schedules.
- Greedy schedule conflict removal.
- Semester cap support via `max_units_per_semester`.
- Progress output using `total_units_selected` and `total_units_required`.
- Course enrichment from metadata imports (course descriptions, professor names, and professor images).
