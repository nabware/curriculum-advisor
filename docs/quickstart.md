# Quickstart

## 0) First-Clone Data Setup

Run these once to build the local SQLite data used by the project:

```bash
python scripts/import_degree_requirements.py
python scripts/build_degree_requirement_model.py
python scripts/import_class_schedules.py
```

Expected SQLite file: `data/seed/curriculum_advisor.db`

Expected core tables:
- `degree_requirements`
- `degree_programs`
- `requirement_groups`
- `requirement_group_courses`
- `class_schedules`

## 1) Backend
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd ..
bash scripts/run_backend.sh
```

Backend URL: http://localhost:8000
Health check: http://localhost:8000/health

## 2) Frontend
In a second terminal:
```bash
bash scripts/run_frontend.sh
```

Frontend URL: http://localhost:5500

## 3) Test request (optional)
```bash
curl -X POST http://localhost:8000/advisor/recommend \
  -H "Content-Type: application/json" \
  -d '{"major":"CS","completed_courses":["CSC 210"],"interests":[],"career_goals":[]}'
```
