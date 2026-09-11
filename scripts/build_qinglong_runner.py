import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tg_ifttt.cli.qinglong import build_runner


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the standalone Qinglong runner")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = build_runner(args.output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
