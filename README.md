# Curriculum Advisor

Minimal starter stack for the capstone project:
- Frontend: HTML, CSS, JavaScript (AJAX via fetch)
- Backend: FastAPI
- Database: SQLite (default for development)

## Quick Start

1. Start backend:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd ..
bash scripts/run_backend.sh
```

2. Start frontend in a second terminal:

```bash
bash scripts/run_frontend.sh
```

3. Open:
- Frontend: http://localhost:5500
- Backend health: http://localhost:8000/health

## Where To Look

- Project architecture: [docs/architecture.md](docs/architecture.md)
- Team ownership split: [docs/team-ownership.md](docs/team-ownership.md)
- Detailed startup and API test commands: [docs/quickstart.md](docs/quickstart.md)

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

## Current API Endpoints

- GET `/health`
- POST `/advisor/recommend`
