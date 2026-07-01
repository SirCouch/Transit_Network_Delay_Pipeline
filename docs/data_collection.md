# MBTA Backfill Collection

The segment-risk model needs snapshots across weekdays, weekends, and multiple service periods. A short one-hour sample proves the pipeline, but it cannot support credible claims about Monday morning versus Saturday morning risk exposure.

## Recommended Backfill

Use 5-minute TripUpdates snapshots. Collect at least one full week before trusting directionally useful metrics, and 2-4 weeks before using the model in the public demo.

```powershell
make collect-mbta-week
```

For portfolio-grade evaluation:

```powershell
make collect-mbta-two-weeks
```

These commands write ignored local files under `data/raw/mbta_rt/`.

## Rebuild After Collection

After snapshots are collected, rebuild the ML inputs and serving files:

```powershell
make decode-mbta
make build-training-data
make train-segment-risk
make real-serving
make coverage-report
```

The model uses MBTA local time (`America/New_York`) for `hour_of_day` and `day_of_week`, so route exposure is learned in the same time context that riders experience.

## Coverage Targets

Before treating metrics as reliable, check `data/ml/coverage_report.json` and verify:

- at least one weekday and one weekend day
- morning peak, midday, evening peak, night, and overnight coverage
- enough positive and negative delay-threshold examples
- route and segment counts that match the dashboard scope

If the report recommends more data, keep collecting before comparing model metrics to the baseline.
