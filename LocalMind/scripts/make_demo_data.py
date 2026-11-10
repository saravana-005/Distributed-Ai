from pathlib import Path

import pandas as pd
from sklearn.datasets import make_classification


def main() -> None:
    output_dir = Path("data")
    output_dir.mkdir(exist_ok=True)

    output_file = output_dir / "demo_20k.csv"

    X, y = make_classification(
        n_samples=20_000,
        n_features=20,
        n_informative=12,
        n_redundant=4,
        n_classes=2,
        random_state=42,
    )

    columns = [f"feature_{i}" for i in range(X.shape[1])]

    df = pd.DataFrame(X, columns=columns)
    df["target"] = y

    df.to_csv(output_file, index=False)

    print(f"Created: {output_file}")
    print(f"Rows   : {len(df)}")
    print(f"Columns: {len(df.columns)}")


if __name__ == "__main__":
    main()
