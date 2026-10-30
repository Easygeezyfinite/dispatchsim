"""Runs dispatch strategies on identical order streams and compares them.

For each seed we build the scenario once per strategy (fresh objects, same numbers),
run it until every order is delivered, and summarize. Comparing strategies on the
same seed is a paired comparison: both see exactly the same orders, so the
difference comes from the strategy, not from one run getting an easier day.
"""

from dataclasses import dataclass

from dispatchsim.evaluation.metrics import DeliveryMetrics, summarize_orders
from dispatchsim.evaluation.scenario import ScenarioConfig, generate_scenario
from dispatchsim.policies.hungarian import hungarian_batch_policy
from dispatchsim.policies.nearest_courier import nearest_idle_courier
from dispatchsim.simulator.batched_simulation import BatchedSimulation
from dispatchsim.simulator.simulation import Simulation

BASELINE = "nearest"
STRATEGIES = (BASELINE, "hungarian_batch")

# After the last order arrives, keep simulating this long so the backlog can clear.
# If orders are still undelivered after that, the result says so instead of hiding it.
DRAIN_SECONDS = 24 * 3600


@dataclass
class RunResult:
    strategy: str
    seed: int
    metrics: DeliveryMetrics
    events_processed: int


def build_simulation(strategy: str, couriers, batch_interval_seconds: float):
    if strategy == "nearest":
        return Simulation(couriers, nearest_idle_courier)
    if strategy == "hungarian_batch":
        return BatchedSimulation(couriers, hungarian_batch_policy, batch_interval_seconds)
    raise ValueError(f"unknown strategy {strategy!r}, expected one of {STRATEGIES}")


def run_strategy(
    strategy: str, config: ScenarioConfig, seed: int, batch_interval_seconds: float = 30.0
) -> RunResult:
    orders, couriers = generate_scenario(config, seed)
    sim = build_simulation(strategy, couriers, batch_interval_seconds)
    for order in orders:
        sim.add_order(order)
    last_order_time = max(order.created_at for order in orders)
    sim.run_until(last_order_time + DRAIN_SECONDS)
    return RunResult(strategy, seed, summarize_orders(orders), sim.engine.events_processed)


def run_comparison(
    config: ScenarioConfig,
    seeds: list[int],
    strategies=STRATEGIES,
    batch_interval_seconds: float = 30.0,
) -> list[RunResult]:
    if not seeds:
        raise ValueError("need at least one seed")
    return [
        run_strategy(strategy, config, seed, batch_interval_seconds)
        for seed in seeds
        for strategy in strategies
    ]


def percent_lower(baseline_value: float, other_value: float) -> float:
    """How much lower other_value is than the baseline, in percent (negative = worse)."""
    if baseline_value <= 0:
        raise ValueError("baseline must be positive to compare against it")
    return (baseline_value - other_value) / baseline_value * 100


def improvement_per_seed(results: list[RunResult], strategy: str) -> dict[int, float]:
    """Percent lower mean delivery time than the baseline, for each seed.

    Refuses to compare a seed where either run left orders undelivered, because the
    averages only cover delivered orders and would make the backlogged run look better.
    """
    by_key = {(r.strategy, r.seed): r for r in results}
    improvements = {}
    for (name, seed), result in by_key.items():
        if name != strategy:
            continue
        baseline = by_key.get((BASELINE, seed))
        if baseline is None:
            raise ValueError(f"no baseline run for seed {seed}")
        for run in (baseline, result):
            if run.metrics.undelivered_orders:
                raise ValueError(
                    f"{run.strategy} seed {seed} left {run.metrics.undelivered_orders} "
                    "orders undelivered, so its averages aren't comparable"
                )
        improvements[seed] = percent_lower(
            baseline.metrics.mean_delivery_seconds, result.metrics.mean_delivery_seconds
        )
    return dict(sorted(improvements.items()))
