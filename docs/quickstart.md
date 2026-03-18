# Quickstart

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
