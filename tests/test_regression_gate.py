import copy
import json
import os
import tempfile

import pytest

from dispatchsim.evaluation.regression_gate import (
    DEFAULT_BATCH_INTERVAL,
    DEFAULT_CONFIG,
    DEFAULT_SEEDS,
    collect_gate_metrics,
    compare_to_baseline,
    load_baseline,
    write_baseline,
)
from dispatchsim.evaluation.scenario import ScenarioConfig

BASELINE_FILE = os.path.join(
    os.path.dirname(__file__), "..", "experiments", "baseline_metrics.json"
)

SMALL_CONFIG = ScenarioConfig(order_count=150, courier_count=10, orders_per_hour=15.0)


def sample_gate_metrics():
    return {
        "scenario": {"order_count": 100, "seeds": [1, 2]},
        "metrics": {
            "nearest.mean_delivery_seconds": 2000.0,
            "nearest.p90_delivery_seconds": 3000.0,
            "nearest.undelivered_orders": 0,
            "hungarian_batch.mean_delivery_seconds": 1950.0,
            "hungarian_batch.percent_faster_than_nearest": 2.5,
            "hungarian_batch.undelivered_orders": 0,
        },
    }


def with_metric(name, value):
    current = sample_gate_metrics()
    current["metrics"][name] = value
    return current


def test_identical_run_passes():
    result = compare_to_baseline(sample_gate_metrics(), sample_gate_metrics())
    assert result.passed
    assert result.failures == [] and result.improvements == []


def test_slower_delivery_beyond_tolerance_fails():
    current = with_metric("nearest.mean_delivery_seconds", 2030.0)  # 1.5% slower
    result = compare_to_baseline(current, sample_gate_metrics(), tolerance_percent=1.0)
    assert not result.passed
    assert len(result.failures) == 1
    assert "nearest.mean_delivery_seconds" in result.failures[0]


def test_small_change_within_tolerance_passes():
    current = with_metric("nearest.p90_delivery_seconds", 3020.0)  # 0.67% slower
    assert compare_to_baseline(current, sample_gate_metrics(), tolerance_percent=1.0).passed


def test_faster_delivery_passes_and_is_reported():
    current = with_metric("hungarian_batch.mean_delivery_seconds", 1800.0)
    result = compare_to_baseline(current, sample_gate_metrics())
    assert result.passed
    assert len(result.improvements) == 1


def test_losing_batching_advantage_fails_in_points():
    # 2.5% -> 1.2% faster is 1.3 points worse, more than the 1 point allowed.
    current = with_metric("hungarian_batch.percent_faster_than_nearest", 1.2)
    result = compare_to_baseline(current, sample_gate_metrics(), tolerance_percent=1.0)
    assert not result.passed
    assert "percent_faster" in result.failures[0]
    # 2.5% -> 1.8% is within one point.
    current = with_metric("hungarian_batch.percent_faster_than_nearest", 1.8)
    assert compare_to_baseline(current, sample_gate_metrics(), tolerance_percent=1.0).passed


def test_any_new_undelivered_order_fails():
    current = with_metric("nearest.undelivered_orders", 1)
    assert not compare_to_baseline(current, sample_gate_metrics()).passed


def test_missing_metric_fails():
    current = sample_gate_metrics()
    del current["metrics"]["nearest.p90_delivery_seconds"]
    result = compare_to_baseline(current, sample_gate_metrics())
    assert not result.passed
    assert "missing" in result.failures[0]


def test_different_scenario_is_not_compared():
    current = copy.deepcopy(sample_gate_metrics())
    current["scenario"]["order_count"] = 200
    result = compare_to_baseline(current, sample_gate_metrics())
    assert not result.passed
    assert "scenario changed" in result.failures[0]


def test_collect_is_deterministic():
    first = collect_gate_metrics(SMALL_CONFIG, [1, 2])
    second = collect_gate_metrics(SMALL_CONFIG, [1, 2])
    assert first == second
    assert first["metrics"]["nearest.undelivered_orders"] == 0
    assert first["scenario"]["seeds"] == [1, 2]
    assert "hungarian_batch.percent_faster_than_nearest" in first["metrics"]


def test_baseline_round_trips_through_json():
    gate_metrics = collect_gate_metrics(SMALL_CONFIG, [3])
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "baseline.json")
        write_baseline(path, gate_metrics)
        loaded = load_baseline(path)
    assert compare_to_baseline(gate_metrics, loaded).passed


def test_committed_baseline_matches_gate_scenario():
    # If someone changes the gate scenario, the baseline file must be re-recorded too,
    # otherwise CI would fail with "scenario changed" on every push.
    with open(BASELINE_FILE) as f:
        baseline = json.load(f)
    assert baseline["scenario"]["seeds"] == DEFAULT_SEEDS
    assert baseline["scenario"]["order_count"] == DEFAULT_CONFIG.order_count
    assert baseline["scenario"]["batch_interval_seconds"] == DEFAULT_BATCH_INTERVAL
    assert baseline["metrics"]["nearest.undelivered_orders"] == 0


def test_empty_seed_list_is_rejected():
    with pytest.raises(ValueError):
        collect_gate_metrics(SMALL_CONFIG, [])
