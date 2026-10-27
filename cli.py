"""Run North16 from a source checkout: python cli.py --help."""
from pathlib import Path
import sys


def main(argv=None):
    source = Path(__file__).resolve().parent / "src"
    if source.is_dir():
        sys.path.insert(0, str(source))
    from north16.cli import main as package_main
    return package_main(argv)


if __name__ == "__main__":
    result = main()
    if isinstance(result, int):
        raise SystemExit(result)
