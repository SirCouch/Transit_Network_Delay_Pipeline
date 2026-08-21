# Segment-Risk Model Evaluation

This report records the current evaluation of the LightGBM segment-risk classifier. The
model estimates whether an MBTA route segment will exceed 180 seconds of delay in a future
update window. It uses current and recent delay behavior, downstream congestion, stop
position, route and direction, and calendar features.

## Executive summary

The model is useful as a ranking model, but the evidence is not yet strong enough for
unmonitored production promotion.

- On the large held-out time split, the model improved ROC-AUC from 0.8828 to 0.9269 and
  PR-AUC from 0.2544 to 0.3436 versus the current-delay persistence baseline.
- Ranking quality also improved: precision among the 50 highest-risk rows was 62% versus
  42% for persistence, and precision among the top 100 was 55% versus 42%.
- At the default 0.50 probability threshold, precision improved to 59.7%, but recall fell
  to 23.2%. The persistence baseline had 45.2% precision and 40.0% recall.
- In purged rolling-origin evaluation, mean PR-AUC was 0.5569 versus 0.4313 for persistence
  across all nine daily folds. On the six folds containing positive examples, mean PR-AUC
  was 0.8353 versus 0.6469.
- Positive events are extremely rare. Three of nine rolling-origin test folds contained no
  positive examples, and the metric variance is high. More collection days and threshold
  tuning are required before treating these estimates as stable.

## Model and target

| Item | Value |
| --- | --- |
| Estimator | LightGBM binary classifier |
| Target | Future segment delay greater than 180 seconds |
| Persistence baseline | Current segment delay, scaled by the 180-second threshold |
| Numeric features | Current, previous, delta, and rolling delays; downstream delay and affected stops; stop position; hour/day and peak/weekend flags |
| Categorical features | Route ID and direction ID |

## Held-out time-split evaluation

This evaluation used 1,659,778 examples. Training covered 2026-05-18 00:22 UTC through
2026-05-21 05:07 UTC. The embargoed test period covered 2026-05-21 05:40 UTC through
2026-05-22 20:36 UTC and contained 546,733 rows. The test positive rate was 0.5235%, so
PR-AUC and top-K precision are more informative than accuracy.

### Discrimination and default threshold

| Metric | Model | Persistence | Difference |
| --- | ---: | ---: | ---: |
| ROC-AUC | 0.9269 | 0.8828 | +0.0441 |
| PR-AUC | 0.3436 | 0.2544 | +0.0891 |
| Precision at threshold | 0.5969 | 0.4518 | +0.1451 |
| Recall at threshold | 0.2324 | 0.3997 | -0.1674 |
| F1 at threshold | 0.3345 | 0.4242 | -0.0897 |

The model separates risky segments better overall, but 0.50 is too conservative if recall
is the operational priority. A threshold sweep found the model's best tested F1 at 0.10:
precision 0.3519, recall 0.5080, and F1 0.4158 while flagging 0.756% of rows. This remains
slightly below the persistence baseline's 0.4242 F1, so deployment should choose a threshold
from an explicit precision/recall or alert-budget requirement rather than F1 alone.

### Ranking and calibration

| Metric | Model | Persistence |
| --- | ---: | ---: |
| Precision@25 | 0.64 | Not recorded |
| Precision@50 | 0.62 | 0.42 |
| Precision@100 | 0.55 | 0.42 |
| Recall@100 | 0.0192 | Not recorded |

Calibration was measured with Brier score, where lower is better:

| Scoring approach | Brier score |
| --- | ---: |
| Existing raw model | 0.004594 |
| Retrained raw model | 0.004590 |
| Platt calibration | 0.004913 |
| Isotonic calibration | 0.004352 |
| Persistence | 0.026372 |

Isotonic calibration performed best on this split. It should still be validated on a later,
untouched time window before being incorporated into the served artifact.

## Purged rolling-origin evaluation

The rolling evaluation used 4,211 GTFS-RT snapshots from 2026-07-02 through 2026-07-16.
Each test date used the preceding five days for training, a 120-minute embargo, a 10-minute
prediction horizon, 180-minute sampling, and the same 180-second delay target. All nine
eligible daily folds ran successfully; six contained at least one positive test example.

| Aggregate metric | Model mean (SD) | Persistence mean (SD) |
| --- | ---: | ---: |
| PR-AUC, all 9 folds | 0.5569 (0.4366) | 0.4313 (0.3543) |
| PR-AUC, 6 positive folds | 0.8353 (0.1609) | 0.6469 (0.1830) |
| Precision@50, positive folds | 0.0867 (0.0450) | 0.0867 (0.0450) |
| Precision@100, positive folds | 0.0433 (0.0225) | 0.0433 (0.0225) |
| Recall@100, positive folds | 0.9815 (0.0454) | Not recorded |

### Daily PR-AUC

| Test date | Positive rate | Model | Persistence |
| --- | ---: | ---: | ---: |
| 2026-07-08 | 0.568% | 0.9762 | 0.6000 |
| 2026-07-09 | 0.000% | N/A | N/A |
| 2026-07-10 | 0.750% | 0.7136 | 0.5934 |
| 2026-07-11 | 0.857% | 0.8167 | 1.0000 |
| 2026-07-12 | 0.000% | N/A | N/A |
| 2026-07-13 | 0.707% | 1.0000 | 0.6667 |
| 2026-07-14 | 0.656% | 0.5889 | 0.5214 |
| 2026-07-15 | 0.458% | 0.9167 | 0.5000 |
| 2026-07-16 | 0.000% | N/A | N/A |

The model beat persistence on PR-AUC in five of the six positive folds. However, only two to
nine positives appeared in each positive daily fold, making a single correctly ranked event
materially change the score. The identical top-K precision values also show that the current
evaluation does not establish a top-K advantage across days.

## Decision and next evals

The current artifact passes the MVP ranking criterion on the large held-out split and shows
the same PR-AUC direction in most positive rolling folds. It should be treated as a candidate,
not an automatically promoted production model.

Before promotion:

1. Collect a longer period spanning more routes, weekdays, weekends, and service disruptions.
2. Repeat rolling-origin evaluation with enough positives per fold to narrow uncertainty.
3. Select the serving threshold from an explicit alert budget or minimum recall requirement.
4. Validate isotonic calibration on a completely later time window.
5. Report route-level slices and monitor drift in positive rate, PR-AUC, and calibration.

## Reproducing the evaluations

The aggregate results above were transcribed from ignored local artifacts under `data/ml/`;
raw GTFS snapshots and trained artifacts are intentionally not committed. With the required
local data and GCP access, run:

```powershell
make evaluate-segment-risk

python -m pipeline.rolling_origin_eval `
  --bucket transit-network-delay-pipeline-gtfs-raw `
  --static-zip data/raw/mbta_static/MBTA_GTFS.zip `
  --test-days 10 `
  --train-days 5 `
  --sample-every-minutes 180 `
  --horizon-minutes 10 `
  --threshold-seconds 180 `
  --embargo-minutes 120
```

The first command writes threshold, top-K, and calibration outputs beneath
`data/ml/generalization/evaluation/`. The rolling-origin command writes `summary.json` and
`fold_metrics.csv` beneath `data/ml/rolling_origin/` by default.
