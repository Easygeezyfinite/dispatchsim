"""Compare dispatch strategies on the same seeded order streams.

Example:
    python experiments/compare_strategies.py --seeds 1 2 3 4 5
    python experiments/compare_strategies.py --orders-per-hour 75 --csv data/results.csv

Same arguments give the same numbers every time (no wall-clock or global randomness
goes into the results).
"""

import argparse
import csv
import statistics
import time

from dispatchsim.evaluation.experiment import (
    BASELINE,
    STRATEGIES,
    improvement_per_seed,
    run_comparison,
)
from dispatchsim.evaluation.scenario import ScenarioConfig


def parse_args():
    defaults = ScenarioConfig()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    parser.add_argument("--orders", type=int, default=defaults.order_count)
    parser.add_argument("--couriers", type=int, default=defaults.courier_count)
    parser.add_argument("--orders-per-hour", type=float, default=defaults.orders_per_hour)
    parser.add_argument("--batch-interval", type=float, default=30.0)
    parser.add_argument("--csv", help="also write one row per (strategy, seed) here")
    return parser.parse_args()


def minutes(seconds):
    return f"{seconds / 60:.2f}"


def main():
    args = parse_args()
    config = ScenarioConfig(
        order_count=args.orders,
        courier_count=args.couriers,
        orders_per_hour=args.orders_per_hour,
    )
    print(
        f"{args.orders} orders, {args.couriers} couriers, {args.orders_per_hour:g} orders/hour, "
        f"batch interval {args.batch_interval:g} s, seeds {args.seeds}"
    )

    started = time.perf_counter()
    results = run_comparison(config, args.seeds, batch_interval_seconds=args.batch_interval)
    elapsed = time.perf_counter() - started

    print(f"\n{'strategy':<16} {'seed':>4} {'delivered':>10} {'mean min':>9} "
          f"{'p90 min':>8} {'wait min':>9}")
    for r in results:
        m = r.metrics
        print(
            f"{r.strategy:<16} {r.seed:>4} {m.delivered_orders:>5}/{m.total_orders:<4} "
            f"{minutes(m.mean_delivery_seconds):>9} {minutes(m.p90_delivery_seconds):>8} "
            f"{minutes(m.mean_wait_for_courier_seconds):>9}"
        )

    for strategy in STRATEGIES:
        if strategy == BASELINE:
            continue
        per_seed = improvement_per_seed(results, strategy)
        values = list(per_seed.values())
        spread = f", stdev {statistics.stdev(values):.2f}" if len(values) > 1 else ""
        print(f"\n{strategy} vs {BASELINE}, mean delivery time (positive = faster):")
        for seed, percent in per_seed.items():
            print(f"  seed {seed}: {percent:+.2f}%")
        print(f"  average {statistics.mean(values):+.2f}%{spread}, "
              f"better on {sum(v > 0 for v in values)}/{len(values)} seeds")

    total_orders = sum(r.metrics.total_orders for r in results)
    print(f"\nSimulated {total_orders} orders in {elapsed:.1f} s")

    if args.csv:
        with open(args.csv, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["strategy", "seed", "total_orders", "delivered_orders",
                             "mean_delivery_seconds", "p90_delivery_seconds",
                             "mean_wait_for_courier_seconds"])
            for r in results:
                m = r.metrics
                writer.writerow([r.strategy, r.seed, m.total_orders, m.delivered_orders,
                                 m.mean_delivery_seconds, m.p90_delivery_seconds,
                                 m.mean_wait_for_courier_seconds])
        print(f"Wrote {args.csv}")


if __name__ == "__main__":
    main()
