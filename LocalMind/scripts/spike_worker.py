import platform
import sys
from multiprocessing import freeze_support

import pandas as pd
import psutil
import sklearn


def main() -> None:
    print("=" * 60)
    print("LocalMind Worker Packaging Spike")
    print("=" * 60)

    print(f"Python       : {sys.version}")
    print(f"Platform     : {platform.platform()}")
    print(f"Machine      : {platform.machine()}")
    print(f"Processor    : {platform.processor()}")

    print()
    print("Package versions:")
    print(f"pandas       : {pd.__version__}")
    print(f"scikit-learn : {sklearn.__version__}")
    print(f"psutil       : {psutil.__version__}")

    print()
    print("System resources:")
    print(f"CPU cores    : {psutil.cpu_count(logical=True)}")
    print(f"RAM          : {psutil.virtual_memory().total / (1024 ** 3):.2f} GB")
    print(f"RAM available: {psutil.virtual_memory().available / (1024 ** 3):.2f} GB")

    print()
    print("Worker packaging spike: PASS")


if __name__ == "__main__":
    freeze_support()
    main()
