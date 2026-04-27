# Final Evaluation Comparison (Submission-Ready)

This page summarizes the three key experimental scenario buckets used to evaluate sentiment-aware ranking.

## Consolidated Metrics

| Scenario Bucket | Scenario File | Scenarios | Changed Recommendations | Positive Lift | Negative Lift | Zero Lift | Mean Overlap@k | Mean Sentiment Lift | Mean Latency Delta (ms) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Broad Tradeoff Pack | data/seed/evaluation_scenarios_tradeoff.csv | 20 | 7 | 4 | 3 | 13 | 0.825000 | -0.002439 | 0.753000 |
| DSAI Edge-Case Pack | data/seed/evaluation_scenarios_dsai_edge.csv | 16 | 12 | 8 | 4 | 4 | 0.604162 | -0.000382 | 6.517500 |
| Fall 2026 DSAI Refined | data/seed/evaluation_scenarios_dsai_fall_refined.csv | 20 | 2 | 2 | 0 | 18 | 0.966670 | 0.002754 | 0.283500 |

## Interpretation For Final Presentation

- Broad Tradeoff Pack demonstrates overall system behavior under mixed constraints and still shows slight aggregate negative lift.
- DSAI Edge-Case Pack demonstrates strong recommendation sensitivity to sentiment in hard tradeoff settings.
- Fall 2026 DSAI Refined demonstrates a positive aggregate lift (+0.002754) with no negative-lift scenarios in that targeted subset.

## Recommended Talking Points

1. We implemented the full graduate-student data role from the proposal: sentiment pipeline, feature engineering, multi-objective ranking, and evaluation analysis.
2. We report results by scenario bucket rather than one headline metric, so strengths and limitations are explicit and reproducible.
3. Seed/simulated sentiment is the default run mode, and live RMP can be enabled only as an optional experiment.

## Source Artifacts

- data/processed/final_sentiment_summary.csv
- data/processed/final_sentiment_summary_dsai_edge.csv
- data/processed/final_sentiment_summary_dsai_fall_refined.csv
- docs/sentiment_data_report.md
- docs/proposal-data-pipeline-alignment.md
