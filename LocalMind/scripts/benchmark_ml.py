from pathlib import Path
from time import perf_counter

import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import StratifiedKFold, cross_val_score


def main() -> None:
    dataset = Path("data/demo_20k.csv")

    if not dataset.exists():
        raise FileNotFoundError(
            "Dataset not found. Run: python scripts/make_demo_data.py"
        )

    df = pd.read_csv(dataset)

    X = df.drop(columns=["target"])
    y = df["target"]

    model = RandomForestClassifier(
        n_estimators=100,
        random_state=42,
        n_jobs=-1,
    )

    cv = StratifiedKFold(
        n_splits=5,
        shuffle=True,
        random_state=42,
    )

    start = perf_counter()

    scores = cross_val_score(
        model,
        X,
        y,
        cv=cv,
        scoring="accuracy",
        n_jobs=1,
    )

    elapsed = perf_counter() - start

    print("=" * 60)
    print("LocalMind ML Benchmark")
    print("=" * 60)
    print(f"Dataset rows : {len(df)}")
    print(f"Features     : {X.shape[1]}")
    print(f"CV folds     : {cv.n_splits}")
    print(f"Mean accuracy: {scores.mean():.4f}")
    print(f"Time         : {elapsed:.3f} seconds")

    if elapsed >= 2:
        print("Task duration target: PASS")
    else:
        print("Task duration target: TOO FAST")
        print("Consider batching multiple configurations per task.")


if __name__ == "__main__":
    main()
