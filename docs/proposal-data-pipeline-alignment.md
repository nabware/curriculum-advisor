# Proposal Alignment: Graduate Student Data Pipeline Scope

This document maps the capstone proposal's graduate-student responsibilities to concrete implementation artifacts in this repository.

## Proposal Responsibilities (Graduate Student)
From the proposal, the graduate student leads:
1. Sentiment extraction pipeline design.
2. Feature engineering methodology.
3. Multi-objective ranking function formulation.
4. Evaluation design and experimental analysis.

## Implementation Mapping

### 1) Sentiment Extraction Pipeline
Status: Completed (seed-first with live fallback).

Implemented in:
- `scripts/build_professor_sentiment_features.py`
- `backend/app/services/rmp_service.py`

Outputs:
- SQLite table `professor_sentiment_features`
- `data/processed/professor_sentiment_features.csv`
- `data/processed/professor_sentiment_diagnostics.csv`

Notes:
- The pipeline supports live lookup attempts, but defaults to reliable seed/simulated sentiment when live data is unavailable.
- This matches the proposal risk-mitigation path for legal/ethical and access constraints.

### 2) Feature Engineering Methodology
Status: Completed.

Implemented in:
- `scripts/build_professor_sentiment_features.py`

Feature behavior:
- Converts raw sentiment signals into normalized professor-level features.
- Applies confidence-aware smoothing/shrinkage for low-support observations.
- Persists both features and diagnostics for auditability.

### 3) Multi-Objective Ranking Formulation
Status: Completed.

Implemented in:
- `backend/app/services/advisor_service.py`
- `backend/app/models/schemas.py`

Capabilities:
- Objective weights for progress, workload, and sentiment are configurable.
- Recommendation selection balances prerequisite-safe progress with sentiment/workload objectives.
- Ranking uses deterministic prerequisite validation from requirement model tables.

### 4) Evaluation Design and Experimental Analysis
Status: Completed, with ongoing refinement.

Implemented in:
- `scripts/evaluate_sentiment_impact.py`
- `scripts/tune_objective_weights.py`

Scenario sets:
- `data/seed/evaluation_scenarios.csv`
- `data/seed/evaluation_scenarios_tradeoff.csv`
- `data/seed/evaluation_scenarios_dsai_edge.csv`

Current packaged summaries:
- `data/processed/final_sentiment_summary.csv`
- `data/processed/final_sentiment_summary_dsai_edge.csv`
- `docs/sentiment_data_report.md`

## Proposal Metric Coverage
The proposal specifies system-level and controlled-scenario evaluation. Current coverage:
- Ranking behavior change baseline vs sentiment-aware: covered.
- Sentiment lift and overlap@k: covered.
- Response latency delta: covered.
- Prerequisite violation rate: enforced by deterministic prerequisite filtering in recommendation logic.

## Current Gap and Next Data Step
Gap:
- Mean sentiment lift is near zero/slightly negative in aggregate, despite improved recommendation sensitivity.

Next step (data-side):
- Expand edge scenarios where equally valid Fall 2026 DSAI alternatives differ in sentiment/workload.
- Re-run tuner and evaluator to improve aggregate lift while preserving prerequisite correctness and low latency.

## Repro Commands
```bash
python scripts/build_professor_sentiment_features.py \
  --seed-csv data/seed/professor_sentiment_seed.csv

python scripts/tune_objective_weights.py \
  --scenarios-csv data/seed/evaluation_scenarios_dsai_edge.csv \
  --output-csv data/processed/objective_weight_tuning_dsai_edge.csv

python scripts/evaluate_sentiment_impact.py \
  --scenarios-csv data/seed/evaluation_scenarios_dsai_edge.csv \
  --output-csv data/processed/evaluation_sentiment_impact_dsai_edge.csv \
  --objective-progress-weight 0.45 \
  --objective-workload-weight 0.10 \
  --objective-sentiment-weight 0.20
```
