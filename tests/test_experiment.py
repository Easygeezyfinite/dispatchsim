import pytest

from dispatchsim.evaluation.experiment import (
    STRATEGIES,
    RunResult,
    improvement_per_seed,
    percent_lower,
    run_comparison,
    run_strategy,
)
from dispatchsim.evaluation.metrics import DeliveryMetrics
from dispatchsim.evaluation.scenario import ScenarioConfig

SMALL = ScenarioConfig(order_count=300, courier_count=15, orders_per_hour=40)


def test_same_seed_gives_identical_results():
    first = run_strategy("hungarian_batch", SMALL, seed=4)
    second = run_strategy("hungarian_batch", SMALL, seed=4)
    assert first.metrics == second.metrics
    assert first.events_processed == second.events_processed


def test_every_order_is_delivered_after_the_drain():
    for strategy in STRATEGIES:
        result = run_strategy(strategy, SMALL, seed=1)
        assert result.metrics.delivered_orders == SMALL.order_count


def test_strategies_do_not_affect_each_other():
    # Running the baseline first must not change what the batched run sees.
    alone = run_strategy("hungarian_batch", SMALL, seed=2)
    together = run_comparison(SMALL, seeds=[2])
    batched_in_comparison = next(r for r in together if r.strategy == "hungarian_batch")
    assert batched_in_comparison.metrics == alone.metrics


def test_comparison_runs_every_strategy_on_every_seed():
    results = run_comparison(SMALL, seeds=[1, 2])
    assert {(r.strategy, r.seed) for r in results} == {
        (strategy, seed) for strategy in STRATEGIES for seed in (1, 2)
    }


def test_unknown_strategy_is_rejected():
    with pytest.raises(ValueError):
        run_strategy("random", SMALL, seed=1)


def test_percent_lower():
    assert percent_lower(100, 88) == pytest.approx(12)
    assert percent_lower(100, 110) == pytest.approx(-10)
    with pytest.raises(ValueError):
        percent_lower(0, 5)


def fake_result(strategy, seed, mean, delivered=10, total=10):
    metrics = DeliveryMetrics(total, delivered, mean, mean, 0.0)
    return RunResult(strategy, seed, metrics, events_processed=0)


def test_improvement_is_computed_per_seed_against_the_same_seed():
    results = [
        fake_result("nearest", 1, 1000),
        fake_result("hungarian_batch", 1, 900),
        fake_result("nearest", 2, 2000),
        fake_result("hungarian_batch", 2, 2100),
    ]
    improvements = improvement_per_seed(results, "hungarian_batch")
    assert improvements == {1: pytest.approx(10), 2: pytest.approx(-5)}


def test_improvement_refuses_runs_with_undelivered_orders():
    # Averages skip undelivered orders, so a backlogged run would look faster than it was.
    results = [
        fake_result("nearest", 1, 1000),
        fake_result("hungarian_batch", 1, 500, delivered=6),
    ]
    with pytest.raises(ValueError):
        improvement_per_seed(results, "hungarian_batch")
