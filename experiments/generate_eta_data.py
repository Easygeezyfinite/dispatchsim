"""Generate observed ETA labels without exposing future state as model features."""

import argparse
from pathlib import Path

from dispatchsim.eta_model.data import generate_examples, write_dataset
from dispatchsim.evaluation.experiment import STRATEGIES
from dispatchsim.evaluation.scenario import ScenarioConfig


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, nargs="+", default=list(range(1, 11)))
    parser.add_argument("--orders", type=int, default=2000)
    parser.add_argument("--orders-per-hour", type=float, default=60)
    parser.add_argument("--batch-interval", type=float, default=30)
    parser.add_argument("--strategies", nargs="+", choices=STRATEGIES, default=list(STRATEGIES))
    parser.add_argument("--output", type=Path, default=Path("data/eta.csv"))
    args = parser.parse_args()
    config = ScenarioConfig(order_count=args.orders, orders_per_hour=args.orders_per_hour)
    strategies = tuple(args.strategies)
    examples = generate_examples(config, args.seeds, strategies, args.batch_interval)
    write_dataset(args.output, examples, config, args.seeds, strategies, args.batch_interval)
    print(f"Wrote {len(examples)} examples to {args.output}")


if __name__ == "__main__":
    main()
