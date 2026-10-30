import pytest

from dispatchsim.evaluation.metrics import percentile, summarize_orders
from dispatchsim.simulator.location import Location
from dispatchsim.simulator.models import Order

SPOT = Location(51.0447, -114.0631)


def finished_order(order_id, created_at, assigned_at, delivered_at):
    # Walk the order through its real status changes so the numbers come from the model.
    order = Order(order_id, SPOT, SPOT, created_at, created_at)
    order.assign("courier", assigned_at)
    order.pick_up(assigned_at)
    order.deliver(delivered_at)
    return order


def test_means_over_delivered_orders():
    orders = [
        finished_order("a", created_at=0, assigned_at=0, delivered_at=600),
        finished_order("b", created_at=100, assigned_at=160, delivered_at=1300),
    ]
    metrics = summarize_orders(orders)

    assert metrics.total_orders == 2
    assert metrics.delivered_orders == 2
    assert metrics.mean_delivery_seconds == pytest.approx((600 + 1200) / 2)
    assert metrics.mean_wait_for_courier_seconds == pytest.approx((0 + 60) / 2)


def test_undelivered_orders_are_counted_but_not_averaged():
    delivered = finished_order("a", created_at=0, assigned_at=30, delivered_at=900)
    still_on_the_way = Order("b", SPOT, SPOT, 0, 0)
    still_on_the_way.assign("courier", 5000)  # waited a long time, not delivered yet

    metrics = summarize_orders([delivered, still_on_the_way])

    assert metrics.total_orders == 2
    assert metrics.delivered_orders == 1
    assert metrics.undelivered_orders == 1
    assert metrics.mean_delivery_seconds == pytest.approx(900)
    # The undelivered order's 5000 s wait must not leak into the average.
    assert metrics.mean_wait_for_courier_seconds == pytest.approx(30)


def test_no_delivered_orders_gives_none_not_a_crash():
    metrics = summarize_orders([Order("a", SPOT, SPOT, 0, 0)])
    assert metrics.delivered_orders == 0
    assert metrics.mean_delivery_seconds is None
    assert metrics.p90_delivery_seconds is None
    assert metrics.mean_wait_for_courier_seconds is None


def test_empty_list():
    metrics = summarize_orders([])
    assert metrics.total_orders == 0
    assert metrics.mean_delivery_seconds is None


def test_p90_uses_nearest_rank():
    orders = [
        finished_order(str(i), created_at=0, assigned_at=0, delivered_at=seconds)
        for i, seconds in enumerate([100, 200, 300, 400, 500, 600, 700, 800, 900, 1000])
    ]
    assert summarize_orders(orders).p90_delivery_seconds == 900


def test_percentile_edge_cases():
    assert percentile([5], 90) == 5
    assert percentile([3, 1, 2], 100) == 3
    assert percentile([3, 1, 2], 50) == 2
    with pytest.raises(ValueError):
        percentile([], 50)
    with pytest.raises(ValueError):
        percentile([1, 2], 0)
