import json
from dataclasses import asdict

import pytest

from dispatchsim.eta_model.data import extract_features, generate_examples, write_dataset
from dispatchsim.evaluation.experiment import run_strategy
from dispatchsim.evaluation.scenario import ScenarioConfig
from dispatchsim.simulator.location import Location, travel_time_seconds
from dispatchsim.simulator.models import Courier, Order


def test_features_ignore_hidden_readiness_and_future_labels():
    order = Order("o", Location(51, -114), Location(51.01, -114), 10, 200)
    courier = Courier("c", order.restaurant)
    kwargs = {"estimated_prep_seconds": 600, "available_couriers": 2, "outstanding_orders": 3}
    before = extract_features(order, courier, 20, **kwargs)
    order.food_ready_at = 900
    order.delivered_at = 2000
    assert extract_features(order, courier, 20, **kwargs) == before
    assert before.order_age_seconds == 10
    assert before.courier_to_restaurant_km == 0
    assert before.restaurant_to_customer_km > 0
    assert set(asdict(before)) == {
        "courier_to_restaurant_km",
        "restaurant_to_customer_km",
        "courier_speed_kmh",
        "estimated_prep_seconds",
        "order_age_seconds",
        "available_couriers",
        "outstanding_orders",
    }
    with pytest.raises(ValueError):
        extract_features(order, courier, 9, **kwargs)


@pytest.mark.parametrize("strategy", ["nearest", "hungarian_batch"])
def test_repeatable_complete_data_preserves_simulation(strategy):
    config = ScenarioConfig(order_count=30, courier_count=3)
    rows = generate_examples(config, [7], (strategy,))
    assert rows == generate_examples(config, [7], (strategy,))
    assert len(rows) == config.order_count
    assert len({row.order_id for row in rows}) == len(rows)
    assert all(row.delivery_seconds >= 0 for row in rows)
    # The observer must not change any event timing or assignments.
    mean_total = sum(r.delivery_seconds + r.features.order_age_seconds for r in rows) / len(rows)
    assert mean_total == pytest.approx(
        run_strategy(strategy, config, 7).metrics.mean_delivery_seconds
    )
    if strategy == "nearest":
        assert rows[0].features.outstanding_orders == 1  # future orders were preloaded
        assert rows[0].features.available_couriers == 3


def test_label_matches_event_physics_with_known_prep():
    config = ScenarioConfig(order_count=1, min_prep_minutes=10, max_prep_minutes=10)
    row = generate_examples(config, [2], ("nearest",))[0]
    from dispatchsim.evaluation.scenario import generate_scenario

    orders, couriers = generate_scenario(config, 2)
    order = orders[0]
    courier = next(c for c in couriers if c.courier_id == row.courier_id)
    expected = max(600, travel_time_seconds(courier.location, order.restaurant, courier.speed_kmh))
    expected += travel_time_seconds(order.restaurant, order.customer, courier.speed_kmh)
    assert row.delivery_seconds == pytest.approx(expected)


def test_seed_groups_and_stable_output(tmp_path):
    config = ScenarioConfig(order_count=5)
    rows = generate_examples(config, [1, 2])
    assert {r.seed for r in rows} == {1, 2}
    assert len(rows) == 20
    path = tmp_path / "eta.csv"
    write_dataset(path, rows, config, [1, 2])
    original = path.read_bytes()
    write_dataset(path, generate_examples(config, [1, 2]), config, [1, 2])
    assert path.read_bytes() == original
    assert json.loads(path.with_suffix(".metadata.json").read_text())["rows"] == 20


def test_incomplete_runs_are_rejected():
    with pytest.raises(ValueError, match="undelivered"):
        generate_examples(ScenarioConfig(order_count=2, courier_speed_kmh=0.001), [1])


@pytest.mark.parametrize("seeds", [[], [1, 1]])
def test_invalid_seed_groups(seeds):
    with pytest.raises(ValueError):
        generate_examples(ScenarioConfig(order_count=1), seeds)
