import itertools
import random

import pytest

from dispatchsim.policies.hungarian import hungarian_batch_policy, min_cost_assignment
from dispatchsim.policies.nearest_courier import nearest_idle_courier
from dispatchsim.simulator.location import Location, travel_time_seconds
from dispatchsim.simulator.models import Courier, Order


def total_cost(cost, pairs):
    return sum(cost[r][c] for r, c in pairs)


def brute_force_best_cost(cost):
    # Try every way to give each row a different column (fine for tiny matrices).
    rows, columns = len(cost), len(cost[0])
    if rows <= columns:
        return min(
            sum(cost[r][c] for r, c in enumerate(choice))
            for choice in itertools.permutations(range(columns), rows)
        )
    return min(
        sum(cost[r][c] for c, r in enumerate(choice))
        for choice in itertools.permutations(range(rows), columns)
    )


def test_small_square_example():
    cost = [
        [4, 1, 3],
        [2, 0, 5],
        [3, 2, 2],
    ]
    pairs = min_cost_assignment(cost)
    # Best is row0->col1 (1), row1->col0 (2), row2->col2 (2) = 5.
    assert pairs == [(0, 1), (1, 0), (2, 2)]
    assert total_cost(cost, pairs) == 5


def test_greedy_row_by_row_would_be_worse():
    # Row 0 alone would take column 0 (cost 1), forcing row 1 into column 1 (cost 100).
    cost = [
        [1, 2],
        [1, 100],
    ]
    pairs = min_cost_assignment(cost)
    assert pairs == [(0, 1), (1, 0)]
    assert total_cost(cost, pairs) == 3


def test_more_columns_than_rows():
    cost = [[9, 1, 8, 7]]
    assert min_cost_assignment(cost) == [(0, 1)]


def test_more_rows_than_columns():
    cost = [[5], [2], [7]]
    assert min_cost_assignment(cost) == [(1, 0)]


def test_empty_matrix():
    assert min_cost_assignment([]) == []
    assert min_cost_assignment([[]]) == []


def test_ragged_matrix_is_rejected():
    with pytest.raises(ValueError):
        min_cost_assignment([[1, 2], [3]])


def test_matches_brute_force_on_random_matrices():
    rng = random.Random(42)  # fixed seed so a failure is reproducible
    for _ in range(300):
        rows, columns = rng.randint(1, 6), rng.randint(1, 6)
        cost = [[rng.uniform(0, 100) for _ in range(columns)] for _ in range(rows)]
        pairs = min_cost_assignment(cost)

        assert len(pairs) == min(rows, columns)
        assert len({r for r, _ in pairs}) == len(pairs)  # no row used twice
        assert len({c for _, c in pairs}) == len(pairs)  # no column used twice
        assert total_cost(cost, pairs) == pytest.approx(brute_force_best_cost(cost))


# Two restaurants on a line, two couriers. Courier A is a bit closer to R1 than B is,
# but A is also the only courier anywhere near R2.
R1 = Location(51.0500, -114.0700)
R2 = Location(51.0500, -114.0600)
COURIER_A_SPOT = Location(51.0500, -114.0640)
COURIER_B_SPOT = Location(51.0500, -114.0790)
CUSTOMER = Location(51.0400, -114.0700)


def two_orders_two_couriers():
    first = Order("first", R1, CUSTOMER, 0, 0)
    second = Order("second", R2, CUSTOMER, 1, 1)
    courier_a = Courier("A", COURIER_A_SPOT)
    courier_b = Courier("B", COURIER_B_SPOT)
    return [first, second], [courier_a, courier_b]


def trip(courier, order):
    return travel_time_seconds(courier.location, order.restaurant, courier.speed_kmh)


def test_batch_beats_one_at_a_time_nearest_courier():
    orders, couriers = two_orders_two_couriers()
    first, second = orders
    courier_a, courier_b = couriers

    # One at a time: "first" grabs A, so "second" gets B from far away.
    greedy_a = nearest_idle_courier(first, couriers)
    assert greedy_a is courier_a
    greedy_total = trip(courier_a, first) + trip(courier_b, second)

    pairs = hungarian_batch_policy(orders, couriers)
    assignment = {order.order_id: courier.courier_id for order, courier in pairs}
    assert assignment == {"first": "B", "second": "A"}
    batch_total = sum(trip(courier, order) for order, courier in pairs)
    assert batch_total < greedy_total


def test_only_the_oldest_orders_are_matched_when_couriers_are_short():
    # Three orders, one courier. The courier is right next to the newest order's
    # restaurant, but the oldest order still goes first so it can't be starved.
    oldest = Order("oldest", R1, CUSTOMER, 0, 0)
    middle = Order("middle", R1, CUSTOMER, 1, 1)
    newest = Order("newest", R2, CUSTOMER, 2, 2)
    courier = Courier("A", R2)

    pairs = hungarian_batch_policy([oldest, middle, newest], [courier])
    assert [(o.order_id, c.courier_id) for o, c in pairs] == [("oldest", "A")]


def test_nothing_to_match():
    orders, couriers = two_orders_two_couriers()
    assert hungarian_batch_policy([], couriers) == []
    assert hungarian_batch_policy(orders, []) == []
