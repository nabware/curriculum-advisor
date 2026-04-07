# Quickstart

## 0) First-Clone Data Setup

Run these once to build the local SQLite data used by the project:

```bash
python scripts/import_degree_requirements.py
python scripts/build_degree_requirement_model.py
python scripts/import_class_schedules.py
python scripts/import_course_metadata.py
```

Expected SQLite file: `data/seed/curriculum_advisor.db`

Expected core tables:
- `degree_requirements`
- `degree_programs`
- `requirement_groups`
- `requirement_group_courses`
- `class_schedules`
- `course_descriptions`
- `professor_profiles`

## 1) Backend
```bash
bash scripts/run_backend.sh
```

`scripts/run_backend.sh` will:
- create `backend/.venv` if missing
- install dependencies from `backend/requirements.txt` when requirements change
- start FastAPI on port `8000`

Backend URL: http://localhost:8000
Health check: http://localhost:8000/health

## 2) Frontend
In a second terminal:
```bash
bash scripts/run_frontend.sh
```

Frontend URL: http://localhost:5500

## 3) Test request (optional)
List available degree programs:
```bash
curl http://localhost:8000/advisor/degrees
```

Starter recommendation request:
```bash
curl -X POST http://localhost:8000/advisor/recommend \
  -H "Content-Type: application/json" \
  -d '{
    "major": "Bachelor of Science in Computer Science",
    "completed_courses": [],
    "interests": [],
    "career_goals": [],
    "prefer_light_workload": false,
    "prefer_high_rated_professors": false,
    "max_units_per_semester": 12,
    "term": "Spring 2026"
  }'
```
