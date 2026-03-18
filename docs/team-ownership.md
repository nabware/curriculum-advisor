# Team Ownership (Conflict-Minimized)

Use this split to reduce merge conflicts and keep ownership clear.

## Person A: Backend + Data Contracts
- Main area: backend/app/api, backend/app/models
- Owns endpoint design and request/response schemas.
- Creates deterministic prerequisite validation service.

## Person B: Frontend + AJAX UX
- Main area: frontend/
- Owns UI forms, rendering, and API integration via fetch/AJAX.
- Keeps API calls isolated in frontend/js/api.js.

## Person C: Ranking + Sentiment + Data Pipeline
- Main area: backend/app/services, data/
- Owns sentiment extraction, ranking logic, and feature engineering.
- Owns data ingestion scripts and scoring experiments.

## Shared Rules
- Avoid editing files owned by another person unless coordinated.
- Keep interfaces stable: update backend/app/models/schemas.py first, then consumers.
- Open small PRs per feature branch.
- Prefer one concern per PR: UI, API, or ranking/data.
