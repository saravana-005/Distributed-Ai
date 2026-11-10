# LocalMind Phase 0 — ML Benchmark

## Objective

Determine whether a realistic ML experiment is large enough to benefit from distributed execution.

## Dataset

- Rows: 20000
- Features: 20
- Classes: 2
- Random seed: 42

## Model

RandomForestClassifier

Configuration:

- n_estimators: 100
- random_state: 42
- n_jobs: -1

## Cross Validation

- Method: StratifiedKFold
- Number of folds: 5
- shuffle: True
- random_state: 42

## Result

- Mean accuracy: 0.9508
- Execution time: 17.374 seconds
- CPU: 2 logical cores, x86_64
- RAM: 7.76 GB total; 5.33 GB available
- Python version: 3.12.3

## Decision

PASS — task is large enough for initial distribution.

## Important Observation

The benchmark is only a feasibility spike. It is not the final LocalMind benchmark.
