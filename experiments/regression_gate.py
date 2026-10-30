"""CI quality gate: rerun the fixed dispatch scenario and compare it to the baseline.

    python experiments/regression_gate.py
    python experiments/regression_gate.py --write-baseline

The first form exits with status 1 if mean or p90 delivery time got more than 1%
worse for any strategy, if batching lost more than 1 point of its advantage, or if
any order was left undelivered. Use --write-baseline after an intended change (and
commit the updated JSON so reviewers can see the numbers move).
"""

import argparse
import os
import sys
import time

from dispatchsim.evaluation.regression_gate import (
    DEFAULT_TOLERANCE_PERCENT,
    collect_gate_metrics,
    compare_to_baseline,
    load_baseline,
    write_baseline,
)

DEFAULT_BASELINE_PATH = os.path.join(os.path.dirname(__file__), "baseline_metrics.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline", default=DEFAULT_BASELINE_PATH)
    parser.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE_PERCENT,
                        help="allowed worsening in percent (default 1)")
    parser.add_argument("--write-baseline", action="store_true",
                        help="record this run as the new baseline instead of checking")
    args = parser.parse_args()

    started = time.perf_counter()
    current = collect_gate_metrics()
    elapsed = time.perf_counter() - started
    print(f"Ran gate scenario in {elapsed:.1f} s")
    for name, value in current["metrics"].items():
        print(f"  {name:<45} {value:,.2f}")

    if args.write_baseline:
        write_baseline(args.baseline, current)
        print(f"\nWrote {args.baseline}")
        return

    if not os.path.exists(args.baseline):
        print(f"\nNo baseline at {args.baseline}. Run with --write-baseline first.")
        sys.exit(1)

    result = compare_to_baseline(current, load_baseline(args.baseline), args.tolerance)
    for line in result.improvements:
        print(f"\nBetter than baseline: {line}")
    if result.improvements:
        print("Consider re-recording with --write-baseline so the gate keeps the gain.")
    if not result.passed:
        print("\nREGRESSION GATE FAILED:")
        for line in result.failures:
            print(f"  - {line}")
        sys.exit(1)
    print("\nRegression gate passed.")


if __name__ == "__main__":
    main()
