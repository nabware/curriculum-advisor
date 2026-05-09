# Quickstart

## 0) First-Clone Data Setup

Run these once to build the local SQLite data used by the project:

```bash
python scripts/import_degree_requirements.py
python scripts/build_degree_requirement_model.py
python scripts/import_class_schedules.py
python scripts/import_course_metadata.py
python scripts/import_course_prerequisites.py
python scripts/build_professor_sentiment_features.py
python scripts/prebuild_demo_rationales.py
```

Expected SQLite file: `data/seed/curriculum_advisor.db`

Expected core tables:
- `degree_requirements`
- `degree_programs`
- `requirement_groups`
- `requirement_group_courses`
- `class_schedules`
- `course_descriptions`
- `course_prerequisites`
- `course_prerequisite_notes`
- `professor_profiles`
- `professor_sentiment_features`

The sentiment builder also writes:
- `data/processed/professor_sentiment_features.csv`
- `data/processed/professor_sentiment_diagnostics.csv`

Optional local seed input (for offline/simulated sentiment coverage):
- `data/seed/professor_sentiment_seed.csv`

Example with explicit seed file:

```bash
python scripts/build_professor_sentiment_features.py \
  --seed-csv data/seed/professor_sentiment_seed.csv
```

Live RMP lookups are disabled by default for reproducible offline runs.
To opt in explicitly for experiments, set `RMP_ENABLE_LIVE=1` before running scripts.

## 0.5) Evaluate Baseline vs Sentiment-Aware Ranking

Run the evaluation script over fixed scenarios:

```bash
python scripts/evaluate_sentiment_impact.py
```

Defaults:
- Scenarios input: `data/seed/evaluation_scenarios.csv`
- Report output: `data/processed/evaluation_sentiment_impact.csv`

Optional flags:

```bash
python scripts/evaluate_sentiment_impact.py \
  --scenarios-csv data/seed/evaluation_scenarios.csv \
  --output-csv data/processed/evaluation_sentiment_impact.csv \
  --top-k 5
```

Optional objective weight overrides during evaluation:

```bash
python scripts/evaluate_sentiment_impact.py \
  --objective-progress-weight 0.55 \
  --objective-workload-weight 0.20 \
  --objective-sentiment-weight 0.35
```

Grid-search objective weights:

```bash
python scripts/tune_objective_weights.py
```

Defaults:
- Input scenarios: `data/seed/evaluation_scenarios.csv`
- Output report: `data/processed/objective_weight_tuning.csv`

## 0.6) Tradeoff Pack + Final Data Artifacts

Run the full sentiment-data workflow on the tradeoff-heavy scenario set:

```bash
python scripts/build_professor_sentiment_features.py \
  --seed-csv data/seed/professor_sentiment_seed.csv

python scripts/tune_objective_weights.py \
  --scenarios-csv data/seed/evaluation_scenarios_tradeoff.csv \
  --output-csv data/processed/objective_weight_tuning_tradeoff.csv

python scripts/evaluate_sentiment_impact.py \
  --scenarios-csv data/seed/evaluation_scenarios_tradeoff.csv \
  --output-csv data/processed/evaluation_sentiment_impact_tradeoff.csv \
  --objective-progress-weight 0.45 \
  --objective-workload-weight 0.10 \
  --objective-sentiment-weight 0.20
```

Artifacts used for capstone packaging:
- `data/seed/evaluation_scenarios_tradeoff.csv`
- `data/processed/objective_weight_tuning_tradeoff.csv`
- `data/processed/evaluation_sentiment_impact_tradeoff.csv`
- `data/processed/final_sentiment_summary.csv`
- `docs/sentiment_data_report.md`

## 0.7) Fall 2026 DSAI Refined Pass

Run the targeted Fall DSAI refinement set (non-negative lift scenarios only):

```bash
python scripts/tune_objective_weights.py \
  --scenarios-csv data/seed/evaluation_scenarios_dsai_fall_refined.csv \
  --output-csv data/processed/objective_weight_tuning_dsai_fall_refined.csv

python scripts/evaluate_sentiment_impact.py \
  --scenarios-csv data/seed/evaluation_scenarios_dsai_fall_refined.csv \
  --output-csv data/processed/evaluation_sentiment_impact_dsai_fall_refined.csv \
  --objective-progress-weight 0.45 \
  --objective-workload-weight 0.10 \
  --objective-sentiment-weight 0.20
```

Artifacts:
- `data/seed/evaluation_scenarios_dsai_fall_refined.csv`
- `data/processed/objective_weight_tuning_dsai_fall_refined.csv`
- `data/processed/evaluation_sentiment_impact_dsai_fall_refined.csv`
- `data/processed/final_sentiment_summary_dsai_fall_refined.csv`

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

Conversational chat endpoint (uses Llama 3.2 3B via Ollama if available,
otherwise falls back to a regex intent extractor + pre-built rationale
templates):

```bash
curl -X POST http://localhost:8000/advisor/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "I am a BSCS senior planning Fall 2026, I prefer high-rated profs.",
    "state": {"completed_courses": [], "blocked_time_windows": []},
    "history": []
  }'
```

## 4) Optional: Local LLM for the chat experience

The chat endpoint works without a local LLM (regex fallback), but the demo
script in `docs/demo-script.md` and the slide deck assume Llama 3.2 3B is
available via Ollama:

```bash
ollama pull llama3.2:3b   # ~2 GB, runtime intent + rationales
ollama pull llama3.1      # ~5 GB, only needed to rebuild sentiment features
```

The backend warms the chat model in a daemon thread at startup so the first
user message does not pay the model-load cost.
