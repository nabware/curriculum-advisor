# Architecture

## Frontend
- Stack: static HTML, CSS, and vanilla JavaScript.
- API integration: `fetch` calls from `frontend/js/api.js` to FastAPI.
- Main flow in `frontend/js/app.js`:
  - Load degrees from `GET /advisor/degrees`.
  - Submit recommendation requests to `POST /advisor/recommend`.
  - Render:
    - Flat course recommendation cards.
    - Degree progress (`total_units_selected` / `total_units_required`).
    - A day/time schedule overview derived from recommended courses.

## Backend
- Stack: FastAPI + Pydantic + SQLite.
- Route layer: `backend/app/api/routes`.
  - `GET /health`
  - `GET /advisor/degrees`
  - `POST /advisor/recommend`
- Service layer: `backend/app/services/advisor_service.py`.
  - Resolves selected degree.
  - Builds requirement-group-aware recommendations.
  - Selects a concise set of courses per requirement group.
  - Applies term filtering using class schedules.
  - Removes overlapping course times (greedy conflict filter).
  - Enforces optional semester unit cap.
  - Enriches courses with descriptions and professor metadata.
  - Computes degree progress totals.
- Static assets:
  - Professor images are served by FastAPI from:
    - `data/raw/professor_images`
  - Mounted path:
    - `/assets/professor-images/*`

## Data Layer
- SQLite file:
  - `data/seed/curriculum_advisor.db`
- Core serving tables:
  - `degree_programs`
  - `requirement_groups`
  - `requirement_group_courses`
  - `class_schedules`
  - `course_descriptions`
  - `professor_profiles`

## Data Pipeline Scripts
- `scripts/import_degree_requirements.py`
  - Imports degree requirement pages and parses degree totals.
- `scripts/build_degree_requirement_model.py`
  - Builds normalized serving tables for recommendation queries.
- `scripts/import_class_schedules.py`
  - Imports schedule/term/section data.
- `scripts/import_course_metadata.py`
  - Imports course descriptions and professor profile metadata.
