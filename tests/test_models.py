import pytest

from dispatchsim.simulator.location import Location
from dispatchsim.simulator.models import Courier, CourierStatus, Order, OrderStatus

RESTAURANT = Location(51.0447, -114.0631)
CUSTOMER = Location(51.0500, -114.0700)


def make_order(created_at=0.0, food_ready_at=600.0):
    return Order("order_1", RESTAURANT, CUSTOMER, created_at, food_ready_at)


def test_order_goes_through_the_normal_lifecycle():
    order = make_order(created_at=100, food_ready_at=700)
    order.assign("courier_1", now=160)
    order.pick_up(now=720)
    order.deliver(now=1300)
    assert order.status == OrderStatus.DELIVERED
    assert order.courier_id == "courier_1"
    assert order.wait_for_courier_seconds == 60
    assert order.delivery_time_seconds == 1200


def test_unfinished_order_has_no_delivery_time():
    order = make_order()
    assert order.delivery_time_seconds is None
    assert order.wait_for_courier_seconds is None


def test_order_cannot_skip_steps():
    order = make_order()
    with pytest.raises(ValueError):
        order.deliver(now=1000)
    with pytest.raises(ValueError):
        order.pick_up(now=1000)


def test_order_cannot_be_assigned_twice():
    order = make_order()
    order.assign("courier_1", now=10)
    with pytest.raises(ValueError):
        order.assign("courier_2", now=20)


def test_pickup_can_retry_when_food_becomes_ready():
    order = make_order(food_ready_at=600)
    order.assign("courier_1", now=10)

    with pytest.raises(ValueError, match="food isn't ready"):
        order.pick_up(now=599)

    assert order.status == OrderStatus.ASSIGNED
    assert order.picked_up_at is None

    order.pick_up(now=600)

    assert order.status == OrderStatus.PICKED_UP
    assert order.picked_up_at == 600


def test_food_ready_before_order_created_is_rejected():
    with pytest.raises(ValueError):
        make_order(created_at=500, food_ready_at=100)


def test_courier_lifecycle_moves_courier_to_customer():
    courier = Courier("courier_1", location=Location(51.0, -114.0))
    assert courier.is_available
    courier.start_order("order_1")
    assert not courier.is_available
    courier.leave_restaurant_with_food(RESTAURANT)
    assert courier.location == RESTAURANT
    assert courier.status == CourierStatus.HEADING_TO_CUSTOMER
    courier.finish_delivery(CUSTOMER)
    assert courier.location == CUSTOMER
    assert courier.is_available
    assert courier.current_order_id is None


def test_busy_courier_cannot_take_second_order():
    courier = Courier("courier_1", location=RESTAURANT)
    courier.start_order("order_1")
    with pytest.raises(ValueError):
        courier.start_order("order_2")


def test_courier_cannot_drop_off_without_picking_up():
    courier = Courier("courier_1", location=RESTAURANT)
    courier.start_order("order_1")
    with pytest.raises(ValueError):
        courier.finish_delivery(CUSTOMER)
