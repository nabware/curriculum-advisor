# Minimal Architecture

## Frontend
- Static HTML/CSS/JS.
- AJAX (`fetch`) requests to FastAPI.

## Backend
- FastAPI app with two starter routes:
  - GET /health
  - POST /advisor/recommend
- Service layer in backend/app/services for recommendation logic.
- Pydantic schemas in backend/app/models/schemas.py.

## Data
- data/raw: imported catalogs and review files.
- data/processed: transformed outputs.
- data/seed: tiny local seed files for development.

## Why this stack
- Minimal setup and easy onboarding.
- Clear separation of concerns and ownership.
- Scales later without rewriting core structure.
