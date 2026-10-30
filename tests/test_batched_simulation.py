import pytest

from dispatchsim.policies.hungarian import hungarian_batch_policy
from dispatchsim.simulator.batched_simulation import BatchedSimulation
from dispatchsim.simulator.location import Location
from dispatchsim.simulator.models import Courier, Order, OrderStatus

RESTAURANT = Location(51.0480, -114.0700)
OTHER_RESTAURANT = Location(51.0480, -114.0600)
CUSTOMER = Location(51.0380, -114.0800)
COURIER_START = Location(51.0447, -114.0631)


def make_order(order_id, created_at, restaurant=RESTAURANT):
    return Order(order_id, restaurant, CUSTOMER, created_at, created_at)


def test_order_waits_for_the_next_batch():
    sim = BatchedSimulation([Courier("c1", COURIER_START)], hungarian_batch_policy, 30)
    order = make_order("o1", created_at=100)
    sim.add_order(order)

    sim.run_until(129)
    assert order.status == OrderStatus.WAITING_FOR_COURIER

    sim.run_until(10_000)
    assert order.assigned_at == pytest.approx(130)
    assert order.status == OrderStatus.DELIVERED


def test_orders_in_the_same_window_are_matched_together():
    couriers = [Courier("c1", COURIER_START), Courier("c2", COURIER_START)]
    sim = BatchedSimulation(couriers, hungarian_batch_policy, 30)
    first = make_order("first", created_at=0)
    second = make_order("second", created_at=20, restaurant=OTHER_RESTAURANT)
    sim.add_order(first)
    sim.add_order(second)
    sim.run_until(10_000)

    # Both go out on the same tick (30 s after the first order arrived).
    assert first.assigned_at == pytest.approx(30)
    assert second.assigned_at == pytest.approx(30)
    assert first.courier_id != second.courier_id
    assert len(sim.delivered_orders()) == 2
    # 2 order_created + ONE dispatch_tick + 3 trip events per order. The second order
    # must not book its own extra tick when one is already coming.
    assert sim.engine.events_processed == 2 + 1 + 2 * 3


def test_leftover_orders_go_out_once_a_courier_frees_up():
    sim = BatchedSimulation([Courier("c1", COURIER_START)], hungarian_batch_policy, 30)
    orders = [make_order(f"o{i}", created_at=i) for i in range(3)]
    for order in orders:
        sim.add_order(order)
    sim.run_until(50_000)

    assert all(o.status == OrderStatus.DELIVERED for o in orders)
    # One courier, so they're served oldest first.
    assigned_order = sorted(orders, key=lambda o: o.assigned_at)
    assert [o.order_id for o in assigned_order] == ["o0", "o1", "o2"]


def test_order_the_policy_skips_is_retried_on_the_next_tick():
    # A policy may pass on an order even with a courier free. No other event is
    # coming to wake dispatch up, so the tick itself has to come back.
    calls = []

    def skip_first_batch(orders, couriers):
        calls.append(len(orders))
        if len(calls) == 1:
            return []
        return hungarian_batch_policy(orders, couriers)

    sim = BatchedSimulation([Courier("c1", COURIER_START)], skip_first_batch, 30)
    order = make_order("o1", created_at=0)
    sim.add_order(order)
    sim.run_until(10_000)

    assert order.assigned_at == pytest.approx(60)
    assert order.status == OrderStatus.DELIVERED


def test_no_tick_is_left_running_once_everything_is_dispatched():
    sim = BatchedSimulation([Courier("c1", COURIER_START)], hungarian_batch_policy, 30)
    sim.add_order(make_order("o1", created_at=0))
    sim.run_until(10_000)
    events_so_far = sim.engine.events_processed

    # If ticks kept rescheduling themselves forever this number would keep climbing.
    sim.run_until(100_000)
    assert sim.engine.events_processed == events_so_far


def test_bad_policy_matching_one_courier_twice_is_caught():
    def double_booking(orders, couriers):
        return [(order, couriers[0]) for order in orders]

    couriers = [Courier("c1", COURIER_START), Courier("c2", COURIER_START)]
    sim = BatchedSimulation(couriers, double_booking, 30)
    sim.add_order(make_order("o1", created_at=0))
    sim.add_order(make_order("o2", created_at=0))
    with pytest.raises(ValueError):
        sim.run_until(1_000)


def test_interval_must_be_positive():
    with pytest.raises(ValueError):
        BatchedSimulation([Courier("c1", COURIER_START)], hungarian_batch_policy, 0)


def test_bad_policy_using_a_courier_not_in_the_simulation_is_caught():
    stranger = Courier("stranger", COURIER_START)

    def hire_a_stranger(orders, couriers):
        return [(orders[0], stranger)]

    sim = BatchedSimulation([Courier("c1", COURIER_START)], hire_a_stranger, 30)
    sim.add_order(make_order("o1", created_at=0))
    with pytest.raises(ValueError):
        sim.run_until(1_000)
