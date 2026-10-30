"""Fails CI when a code change makes dispatching worse.

The simulator is deterministic: same seeds and config give the same numbers. So we
run a fixed scenario, compare its metrics to a baseline file committed in the repo,
and fail if any metric got worse by more than a small tolerance. The tolerance only
has to absorb floating-point differences between machines and Python versions, not
random noise, so it can be tight.

If a change makes things better, the gate passes and suggests updating the baseline,
so the next regression is measured from the new, better numbers.

Timing (requests/sec, latency) is deliberately NOT gated here: shared CI machines
vary too much from run to run. That's what experiments/load_benchmark.py is for.
"""

import json
import statistics
from dataclasses import asdict, dataclass

from dispatchsim.evaluation.experiment import (
    BASELINE,
    STRATEGIES,
    improvement_per_seed,
    run_comparison,
)
from dispatchsim.evaluation.scenario import ScenarioConfig

# Busy-but-stable load from the README results (60 orders/hour, 40 couriers),
# 10,000 orders per strategy. Takes about a second, so it can run on every push.
DEFAULT_SEEDS = [1, 2, 3, 4, 5]
DEFAULT_CONFIG = ScenarioConfig(order_count=2000, courier_count=40, orders_per_hour=60.0)
DEFAULT_BATCH_INTERVAL = 30.0
DEFAULT_TOLERANCE_PERCENT = 1.0

# Which direction is "better" for each metric we track.
LOWER_IS_BETTER = "lower"
HIGHER_IS_BETTER = "higher"


@dataclass
class GateResult:
    passed: bool
    failures: list[str]
    improvements: list[str]


def collect_gate_metrics(
    config: ScenarioConfig = DEFAULT_CONFIG,
    seeds: list[int] = DEFAULT_SEEDS,
    batch_interval_seconds: float = DEFAULT_BATCH_INTERVAL,
) -> dict:
    """Run every strategy on the gate scenario and boil it down to a few numbers."""
    results = run_comparison(config, seeds, batch_interval_seconds=batch_interval_seconds)
    metrics = {}
    for strategy in STRATEGIES:
        runs = [r for r in results if r.strategy == strategy]
        metrics[f"{strategy}.mean_delivery_seconds"] = statistics.mean(
            r.metrics.mean_delivery_seconds for r in runs
        )
        metrics[f"{strategy}.p90_delivery_seconds"] = statistics.mean(
            r.metrics.p90_delivery_seconds for r in runs
        )
        metrics[f"{strategy}.undelivered_orders"] = sum(
            r.metrics.undelivered_orders for r in runs
        )
    for strategy in STRATEGIES:
        if strategy != BASELINE:
            # Raises if any run left orders undelivered, which is itself a regression.
            per_seed = improvement_per_seed(results, strategy)
            metrics[f"{strategy}.percent_faster_than_{BASELINE}"] = statistics.mean(
                per_seed.values()
            )
    return {
        "scenario": {
            **asdict(config),
            "seeds": list(seeds),
            "batch_interval_seconds": batch_interval_seconds,
        },
        "metrics": metrics,
    }


def metric_direction(name: str) -> str:
    return HIGHER_IS_BETTER if "percent_faster" in name else LOWER_IS_BETTER


def compare_to_baseline(
    current: dict, baseline: dict, tolerance_percent: float = DEFAULT_TOLERANCE_PERCENT
) -> GateResult:
    """Check every baseline metric against the current run.

    Times are compared relatively (more than tolerance_percent slower fails).
    The percent-faster metric is already a percentage, so it's compared in
    percentage points. Undelivered orders must stay at zero.
    """
    failures = []
    improvements = []
    if current.get("scenario") != baseline.get("scenario"):
        # Comparing numbers from different scenarios would be meaningless.
        failures.append(
            "scenario changed since the baseline was recorded; "
            "re-record it with --write-baseline if that was intended"
        )
        return GateResult(False, failures, improvements)

    current_metrics = current["metrics"]
    for name, expected in baseline["metrics"].items():
        if name not in current_metrics:
            failures.append(f"{name}: missing from this run")
            continue
        actual = current_metrics[name]
        if name.endswith("undelivered_orders"):
            if actual > expected:
                failures.append(f"{name}: {actual} (baseline {expected})")
            continue
        if metric_direction(name) == HIGHER_IS_BETTER:
            worse_by = expected - actual
            description = f"{actual:+.2f} points (baseline {expected:+.2f})"
        else:
            worse_by = (actual - expected) / expected * 100
            description = f"{actual:.1f} s, {worse_by:+.2f}% vs baseline {expected:.1f} s"
        if worse_by > tolerance_percent:
            failures.append(f"{name}: {description}")
        elif worse_by < -tolerance_percent:
            improvements.append(f"{name}: {description}")
    return GateResult(not failures, failures, improvements)


def load_baseline(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def write_baseline(path: str, gate_metrics: dict) -> None:
    with open(path, "w") as f:
        json.dump(gate_metrics, f, indent=2, sort_keys=True)
        f.write("\n")
