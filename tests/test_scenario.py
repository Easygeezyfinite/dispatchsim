import random

import pytest

from dispatchsim.evaluation.scenario import (
    CITY_CENTER,
    ScenarioConfig,
    generate_scenario,
)
from dispatchsim.simulator.location import distance_km

SMALL = ScenarioConfig(order_count=200, courier_count=10, restaurant_count=8)


def snapshot(orders, couriers):
    # Plain tuples so two scenarios can be compared with ==.
    return (
        [(o.order_id, o.restaurant, o.customer, o.created_at, o.food_ready_at) for o in orders],
        [(c.courier_id, c.location, c.speed_kmh) for c in couriers],
    )


def test_same_seed_gives_the_same_scenario():
    assert snapshot(*generate_scenario(SMALL, seed=7)) == snapshot(*generate_scenario(SMALL, 7))


def test_different_seeds_give_different_scenarios():
    assert snapshot(*generate_scenario(SMALL, seed=7)) != snapshot(*generate_scenario(SMALL, 8))


def test_global_random_state_does_not_leak_in():
    random.seed(1)
    first = snapshot(*generate_scenario(SMALL, seed=7))
    random.seed(999)
    random.random()
    second = snapshot(*generate_scenario(SMALL, seed=7))
    assert first == second


def test_each_call_returns_fresh_objects():
    # The simulator mutates orders and couriers, so sharing them between two
    # strategy runs would let the first run change the second one's input.
    orders_a, couriers_a = generate_scenario(SMALL, seed=7)
    orders_b, couriers_b = generate_scenario(SMALL, seed=7)
    assert all(a is not b for a, b in zip(orders_a, orders_b))
    assert all(a is not b for a, b in zip(couriers_a, couriers_b))


def test_orders_look_sensible():
    orders, couriers = generate_scenario(SMALL, seed=3)
    assert len(orders) == 200 and len(couriers) == 10
    assert len({o.order_id for o in orders}) == 200
    assert len({o.restaurant for o in orders}) <= SMALL.restaurant_count

    created_times = [o.created_at for o in orders]
    assert created_times == sorted(created_times)
    for order in orders:
        prep_minutes = (order.food_ready_at - order.created_at) / 60
        assert SMALL.min_prep_minutes <= prep_minutes <= SMALL.max_prep_minutes
        # Small slack: the km-to-degree conversion is an approximation.
        assert distance_km(CITY_CENTER, order.customer) <= SMALL.city_radius_km * 1.01
        assert distance_km(CITY_CENTER, order.restaurant) <= SMALL.city_radius_km * 1.01


def test_arrival_rate_roughly_matches_the_config():
    config = ScenarioConfig(order_count=3000, orders_per_hour=60)
    orders, _ = generate_scenario(config, seed=11)
    hours = orders[-1].created_at / 3600
    # 3000 orders at 60/hour should take about 50 hours; a Poisson process with this
    # many arrivals lands well within 10% of that.
    assert 45 <= hours <= 55


def test_points_are_spread_over_the_whole_area_not_bunched_in_the_middle():
    config = ScenarioConfig(order_count=4000)
    orders, _ = generate_scenario(config, seed=5)
    inner_half_radius = sum(
        distance_km(CITY_CENTER, o.customer) <= config.city_radius_km / 2 for o in orders
    )
    # The inner circle with half the radius has a quarter of the area, so it should
    # get about a quarter of the customers (not half, which is what you'd get
    # without the square root).
    assert 0.20 <= inner_half_radius / len(orders) <= 0.30


def test_bad_config_is_rejected():
    with pytest.raises(ValueError):
        ScenarioConfig(courier_count=0)
    with pytest.raises(ValueError):
        ScenarioConfig(orders_per_hour=0)
    with pytest.raises(ValueError):
        ScenarioConfig(min_prep_minutes=20, max_prep_minutes=10)
