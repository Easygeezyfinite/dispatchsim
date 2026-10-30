import pytest

from dispatchsim.simulator.location import Location, travel_time_seconds
from dispatchsim.simulator.models import Courier, CourierStatus, Order, OrderStatus
from dispatchsim.simulator.simulation import Simulation

# A few spots in downtown Calgary, a couple of km apart.
COURIER_START = Location(51.0447, -114.0631)
RESTAURANT = Location(51.0480, -114.0700)
CUSTOMER = Location(51.0380, -114.0800)
FAR_AWAY = Location(51.1200, -114.2000)

SPEED_KMH = 20.0
TO_RESTAURANT = travel_time_seconds(COURIER_START, RESTAURANT, SPEED_KMH)
TO_CUSTOMER = travel_time_seconds(RESTAURANT, CUSTOMER, SPEED_KMH)


def first_idle_courier(order, idle_couriers):
    # Placeholder policy for these tests. Real strategies live in policies/.
    return idle_couriers[0]


def never_assign(order, idle_couriers):
    return None


def make_order(order_id="order_1", created_at=0.0, food_ready_at=None):
    # By default the food is ready as soon as the order is placed.
    if food_ready_at is None:
        food_ready_at = created_at
    return Order(order_id, RESTAURANT, CUSTOMER, created_at, food_ready_at)


def make_courier(courier_id="courier_1", location=COURIER_START):
    return Courier(courier_id, location, speed_kmh=SPEED_KMH)


def test_one_order_goes_from_created_to_delivered():
    sim = Simulation([make_courier()], first_idle_courier)
    order = make_order(created_at=100, food_ready_at=100)
    sim.add_order(order)
    sim.run_until(10_000)

    assert order.status == OrderStatus.DELIVERED
    assert order.assigned_at == 100
    # Food was ready immediately, so pickup happens the moment the courier arrives.
    assert order.picked_up_at == pytest.approx(100 + TO_RESTAURANT)
    assert order.delivered_at == pytest.approx(100 + TO_RESTAURANT + TO_CUSTOMER)
    assert sim.delivered_orders() == [order]


def test_courier_waits_at_restaurant_until_food_is_ready():
    sim = Simulation([make_courier()], first_idle_courier)
    food_ready = 100 + TO_RESTAURANT + 300  # five minutes after the courier gets there
    order = make_order(created_at=100, food_ready_at=food_ready)
    sim.add_order(order)
    sim.run_until(10_000)

    assert order.picked_up_at == pytest.approx(food_ready)
    assert order.delivered_at == pytest.approx(food_ready + TO_CUSTOMER)


def test_courier_ends_up_idle_at_the_customer():
    courier = make_courier()
    sim = Simulation([courier], first_idle_courier)
    sim.add_order(make_order())
    sim.run_until(10_000)

    assert courier.status == CourierStatus.IDLE
    assert courier.location == CUSTOMER
    assert courier.current_order_id is None


def test_order_waits_until_the_only_courier_is_free():
    sim = Simulation([make_courier()], first_idle_courier)
    first = make_order("first", created_at=0)
    second = make_order("second", created_at=10)
    sim.add_order(first)
    sim.add_order(second)
    sim.run_until(20_000)

    # The second order can't be assigned until the courier drops off the first one.
    assert second.assigned_at == pytest.approx(first.delivered_at)
    assert second.wait_for_courier_seconds == pytest.approx(first.delivered_at - 10)
    assert second.status == OrderStatus.DELIVERED


def test_two_couriers_take_two_orders_at_once():
    sim = Simulation([make_courier("a"), make_courier("b")], first_idle_courier)
    first = make_order("first", created_at=0)
    second = make_order("second", created_at=0)
    sim.add_order(first)
    sim.add_order(second)
    sim.run_until(10_000)

    assert first.assigned_at == 0 and second.assigned_at == 0
    assert {first.courier_id, second.courier_id} == {"a", "b"}
    assert len(sim.delivered_orders()) == 2


def test_oldest_waiting_order_gets_the_next_free_courier():
    sim = Simulation([make_courier()], first_idle_courier)
    orders = [make_order(f"order_{i}", created_at=i) for i in range(3)]
    for order in orders:
        sim.add_order(order)
    sim.run_until(50_000)

    assigned_times = [order.assigned_at for order in orders]
    assert assigned_times == sorted(assigned_times)
    assert len(sim.delivered_orders()) == 3


def test_stopping_mid_delivery_leaves_order_in_progress():
    sim = Simulation([make_courier()], first_idle_courier)
    order = make_order(created_at=0, food_ready_at=0)
    sim.add_order(order)

    # Stop halfway through the trip to the customer.
    sim.run_until(TO_RESTAURANT + TO_CUSTOMER / 2)
    assert order.status == OrderStatus.PICKED_UP
    assert sim.delivered_orders() == []

    sim.run_until(10_000)
    assert order.status == OrderStatus.DELIVERED


def test_closer_courier_is_reached_faster():
    # The simulator uses each courier's own position for the trip to the restaurant.
    near = Courier("near", COURIER_START, speed_kmh=SPEED_KMH)
    far = Courier("far", FAR_AWAY, speed_kmh=SPEED_KMH)
    near_sim = Simulation([near], first_idle_courier)
    far_sim = Simulation([far], first_idle_courier)
    near_order, far_order = make_order(), make_order()
    near_sim.add_order(near_order)
    far_sim.add_order(far_order)
    near_sim.run_until(50_000)
    far_sim.run_until(50_000)

    assert near_order.picked_up_at < far_order.picked_up_at


def test_policy_can_leave_an_order_waiting():
    sim = Simulation([make_courier()], never_assign)
    order = make_order()
    sim.add_order(order)
    sim.run_until(10_000)

    assert order.status == OrderStatus.WAITING_FOR_COURIER
    assert list(sim.waiting_orders) == ["order_1"]


def test_duplicate_order_id_is_rejected():
    sim = Simulation([make_courier()], first_idle_courier)
    sim.add_order(make_order("same"))
    with pytest.raises(ValueError):
        sim.add_order(make_order("same"))


def test_duplicate_courier_id_is_rejected():
    with pytest.raises(ValueError):
        Simulation([make_courier("x"), make_courier("x")], first_idle_courier)


def test_order_created_in_the_past_is_rejected():
    sim = Simulation([make_courier()], first_idle_courier)
    sim.run_until(500)
    with pytest.raises(ValueError):
        sim.add_order(make_order(created_at=100, food_ready_at=100))
