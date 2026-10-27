"""Run this source checkout without changing the global Python environment."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from north16.pipeline.build import main

if __name__ == "__main__":
    main()
