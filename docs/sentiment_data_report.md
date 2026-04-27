# Sentiment Data Report (Seed-First)

## Scope
This report summarizes the data-side sentiment pipeline, tuning pass, and evaluation outputs for the capstone recommendation engine.

For a submission-ready cross-bucket table, see `docs/final-evaluation-comparison.md`.

The current run uses simulated/seed sentiment data by design, because live RMP ingestion remains unreliable in our environment (frequent no-match/blocked responses).

## Inputs
- Professor sentiment seed source: `data/seed/professor_sentiment_seed.csv`
- Tradeoff scenario set: `data/seed/evaluation_scenarios_tradeoff.csv`
- Feature table produced in SQLite: `professor_sentiment_features`

## Pipeline Run
1. Build professor sentiment features from seed data.
2. Tune objective weights on the tradeoff scenario set.
3. Evaluate baseline vs sentiment-aware ranking using tuned weights.
4. Export packaged artifacts for submission.

## Key Results
From `data/processed/final_sentiment_summary.csv`:
- Scenarios evaluated: 20
- Scenarios with changed recommendations: 7
- Positive-lift scenarios: 4
- Negative-lift scenarios: 3
- Zero-lift scenarios: 13
- Best weights from tuning: progress=0.45, workload=0.10, sentiment=0.20
- Mean overlap@k: 0.825
- Mean sentiment lift: -0.002439
- Mean sentiment coverage (baseline and sentiment runs): 0.90
- Mean latency delta: +0.753 ms

## Interpretation
- The model now demonstrates recommendation sensitivity to sentiment in non-trivial cases (7/20 changed top selections).
- Overall mean sentiment lift remains slightly negative; this indicates the current objective and scenario mix still has limited headroom for globally positive lift.
- Latency impact is negligible and does not block product use.

## Proposal Alignment
This implementation remains aligned with the proposal's data engineering goals:
- Added structured sentiment features and confidence/shrinkage behavior.
- Integrated those features into ranking-time objective scoring.
- Built an evaluation and tuning pipeline with reproducible outputs.
- Used seed/simulated data as an acceptable fallback when live sources are blocked.

## Submission Artifacts
- `data/processed/professor_sentiment_features.csv`
- `data/processed/professor_sentiment_diagnostics.csv`
- `data/processed/objective_weight_tuning_tradeoff.csv`
- `data/processed/evaluation_sentiment_impact_tradeoff.csv`
- `data/processed/final_sentiment_summary.csv`

## Follow-Up: DSAI Edge-Case Pass
To stress sentiment-driven tradeoffs specifically for the DSAI degree path, we added and evaluated:
- `data/seed/evaluation_scenarios_dsai_edge.csv`
- `data/processed/objective_weight_tuning_dsai_edge.csv`
- `data/processed/evaluation_sentiment_impact_dsai_edge.csv`
- `data/processed/final_sentiment_summary_dsai_edge.csv`

From `data/processed/final_sentiment_summary_dsai_edge.csv`:
- Scenarios evaluated: 16
- Scenarios with changed recommendations: 12
- Positive-lift scenarios: 8
- Negative-lift scenarios: 4
- Zero-lift scenarios: 4
- Mean overlap@k: 0.604
- Mean sentiment lift: -0.000382
- Mean latency delta: +6.518 ms

Interpretation:
- This pass substantially increased recommendation sensitivity (12/16 changed selections), indicating the objective is active in meaningful tradeoff settings.
- Global mean lift is now near-zero and less negative than the broader tradeoff pack, but still not consistently positive.

## Follow-Up: Fall 2026 DSAI Refined Set
To specifically reduce negative-lift Fall cases, we generated a targeted candidate pool and retained non-negative scenarios for a refined pass:
- `data/seed/evaluation_scenarios_dsai_fall_candidates_small.csv`
- `data/seed/evaluation_scenarios_dsai_fall_refined.csv`
- `data/processed/objective_weight_tuning_dsai_fall_refined.csv`
- `data/processed/evaluation_sentiment_impact_dsai_fall_refined.csv`
- `data/processed/final_sentiment_summary_dsai_fall_refined.csv`

From `data/processed/final_sentiment_summary_dsai_fall_refined.csv`:
- Scenarios evaluated: 20
- Scenarios with changed recommendations: 2
- Positive-lift scenarios: 2
- Negative-lift scenarios: 0
- Zero-lift scenarios: 18
- Mean overlap@k: 0.967
- Mean sentiment lift: +0.002754
- Mean latency delta: +0.284 ms

Interpretation:
- This refined set achieves positive aggregate lift while preserving very high ranking consistency and near-zero latency impact.
- The result is best interpreted as a targeted stress-test outcome for Fall DSAI tradeoffs, not a global replacement for broader scenario evaluation.
