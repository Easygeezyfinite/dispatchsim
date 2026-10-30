"""Measure requests/sec and latency of the dispatch API under concurrent clients.

Start the server in one terminal (no --reload, it slows things down):
    uvicorn dispatchsim.dispatch_service.app:app

Then in another:
    python experiments/load_benchmark.py --url http://127.0.0.1:8000
    python experiments/load_benchmark.py --url http://127.0.0.1:8000 --concurrency 16 --orders 5000
    python experiments/load_benchmark.py --url http://127.0.0.1:8000 --min-rps 300 --max-p95-ms 60

Without --url it calls DispatchService directly in this process (no HTTP), which
shows the cost of the dispatching logic alone.

Exits with status 1 if any request failed or a --min-rps / --max-p95-ms target is missed.
"""

import argparse
import statistics
import sys

from dispatchsim.dispatch_service.service import DispatchService
from dispatchsim.evaluation.load_test import (
    REQUESTS_PER_ORDER,
    HttpClient,
    InProcessClient,
    check_thresholds,
    run_load_test,
)
from dispatchsim.evaluation.metrics import percentile


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", help="base URL of a running server; leave out for in-process")
    parser.add_argument("--orders", type=int, default=2000, help="timed orders (4 requests each)")
    parser.add_argument("--concurrency", type=int, default=8, help="number of client threads")
    parser.add_argument("--couriers", type=int, default=50)
    parser.add_argument("--warmup", type=int, default=5, help="untimed orders per client first")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--min-rps", type=float, help="fail if throughput is lower than this")
    parser.add_argument("--max-p95-ms", type=float, help="fail if overall p95 is higher than this")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.url:
        mode = f"HTTP against {args.url}"

        def make_client():
            return HttpClient(args.url)
    else:
        mode = "in-process (no HTTP, service layer only)"
        service = DispatchService()

        def make_client():
            return InProcessClient(service)

    print(f"{mode}: {args.orders} orders x {REQUESTS_PER_ORDER} requests, "
          f"{args.concurrency} clients, {args.couriers} couriers")
    result = run_load_test(
        make_client,
        total_orders=args.orders,
        concurrency=args.concurrency,
        courier_count=args.couriers,
        seed=args.seed,
        warmup_orders=args.warmup,
    )

    print(f"\n{result.requests_sent} requests in {result.elapsed_seconds:.2f} s "
          f"= {result.requests_per_second:.0f} req/s, {result.errors} errors, "
          f"{result.orders_completed} orders delivered")
    print(f"\n{'endpoint':<14} {'count':>6} {'mean ms':>8} {'p50 ms':>7} {'p95 ms':>7} "
          f"{'p99 ms':>7} {'max ms':>7}")
    rows = list(result.latencies_ms.items()) + [("all", result.all_latencies())]
    for name, values in rows:
        if not values:
            print(f"{name:<14} {0:>6}")
            continue
        print(f"{name:<14} {len(values):>6} {statistics.mean(values):>8.2f} "
              f"{percentile(values, 50):>7.2f} {percentile(values, 95):>7.2f} "
              f"{percentile(values, 99):>7.2f} {max(values):>7.2f}")

    failures = check_thresholds(result, args.min_rps, args.max_p95_ms)
    if failures:
        print("\nFAILED:")
        for failure in failures:
            print(f"  - {failure}")
        sys.exit(1)
    if args.min_rps is not None or args.max_p95_ms is not None:
        print("\nAll targets met.")


if __name__ == "__main__":
    main()
