import threading
import time

import pytest

from dispatchsim.dispatch_service.service import ConflictError, DispatchService, NotFoundError
from dispatchsim.policies.nearest_courier import nearest_idle_courier
from dispatchsim.simulator.location import Location
from dispatchsim.simulator.models import CourierStatus, OrderStatus

DOWNTOWN = Location(51.0447, -114.0631)
NEAR_DOWNTOWN = Location(51.0460, -114.0640)
FAR_AWAY = Location(51.1200, -114.2000)
CUSTOMER = Location(51.0380, -114.0800)


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


def make_service():
    clock = FakeClock()
    return DispatchService(clock=clock), clock


def test_order_goes_to_nearest_idle_courier():
    service, _ = make_service()
    service.add_courier("far", FAR_AWAY)
    service.add_courier("near", NEAR_DOWNTOWN)
    order = service.create_order("o1", DOWNTOWN, CUSTOMER, prep_minutes=10)
    assert order.status == OrderStatus.ASSIGNED
    assert order.courier_id == "near"
    assert service.get_courier("near").status == CourierStatus.HEADING_TO_RESTAURANT
    assert service.get_courier("far").is_available


def test_order_waits_when_no_courier_is_free():
    service, _ = make_service()
    order = service.create_order("o1", DOWNTOWN, CUSTOMER, prep_minutes=10)
    assert order.status == OrderStatus.WAITING_FOR_COURIER
    _, waiting, idle = service.stats()
    assert (waiting, idle) == (1, 0)


def test_new_courier_picks_up_waiting_order():
    service, clock = make_service()
    service.create_order("o1", DOWNTOWN, CUSTOMER, prep_minutes=10)
    clock.now += 120
    service.add_courier("c1", NEAR_DOWNTOWN)
    order = service.get_order("o1")
    assert order.courier_id == "c1"
    assert order.wait_for_courier_seconds == 120


def test_full_order_lifecycle_and_stats():
    service, clock = make_service()
    service.add_courier("c1", NEAR_DOWNTOWN)
    service.create_order("o1", DOWNTOWN, CUSTOMER, prep_minutes=10)
    clock.now += 600
    service.mark_picked_up("o1")
    clock.now += 300
    order = service.mark_delivered("o1")
    assert order.status == OrderStatus.DELIVERED
    assert order.delivery_time_seconds == 900
    courier = service.get_courier("c1")
    assert courier.is_available
    assert courier.location == CUSTOMER  # free again, wherever it dropped off

    metrics, waiting, idle = service.stats()
    assert metrics.delivered_orders == 1
    assert metrics.mean_delivery_seconds == 900
    assert (waiting, idle) == (0, 1)


def test_delivery_frees_courier_for_oldest_waiting_order():
    service, clock = make_service()
    service.add_courier("c1", NEAR_DOWNTOWN)
    service.create_order("o1", DOWNTOWN, CUSTOMER, prep_minutes=0)
    service.create_order("o2", DOWNTOWN, CUSTOMER, prep_minutes=0)
    clock.now += 1
    service.create_order("o3", DOWNTOWN, CUSTOMER, prep_minutes=0)
    service.mark_picked_up("o1")
    service.mark_delivered("o1")
    # o2 has waited longest, so it gets the courier, not o3.
    assert service.get_order("o2").courier_id == "c1"
    assert service.get_order("o3").status == OrderStatus.WAITING_FOR_COURIER


def test_pickup_before_food_is_ready_is_a_conflict():
    service, clock = make_service()
    service.add_courier("c1", NEAR_DOWNTOWN)
    service.create_order("o1", DOWNTOWN, CUSTOMER, prep_minutes=10)
    clock.now += 60
    with pytest.raises(ConflictError):
        service.mark_picked_up("o1")
    # The failed pickup must not leave the courier half-moved.
    assert service.get_courier("c1").status == CourierStatus.HEADING_TO_RESTAURANT


def test_pickup_without_courier_is_a_conflict():
    service, _ = make_service()
    service.create_order("o1", DOWNTOWN, CUSTOMER, prep_minutes=0)
    with pytest.raises(ConflictError):
        service.mark_picked_up("o1")


def test_deliver_before_pickup_is_a_conflict():
    service, _ = make_service()
    service.add_courier("c1", NEAR_DOWNTOWN)
    service.create_order("o1", DOWNTOWN, CUSTOMER, prep_minutes=0)
    with pytest.raises(ConflictError):
        service.mark_delivered("o1")
    assert service.get_courier("c1").current_order_id == "o1"


def test_deliver_waiting_order_is_a_conflict():
    service, _ = make_service()
    service.create_order("o1", DOWNTOWN, CUSTOMER, prep_minutes=0)
    with pytest.raises(ConflictError):
        service.mark_delivered("o1")


def test_duplicate_ids_are_conflicts():
    service, _ = make_service()
    service.add_courier("c1", NEAR_DOWNTOWN)
    service.create_order("o1", DOWNTOWN, CUSTOMER, prep_minutes=0)
    with pytest.raises(ConflictError):
        service.add_courier("c1", FAR_AWAY)
    with pytest.raises(ConflictError):
        service.create_order("o1", DOWNTOWN, CUSTOMER, prep_minutes=0)


def test_unknown_ids_are_not_found():
    service, _ = make_service()
    with pytest.raises(NotFoundError):
        service.get_order("nope")
    with pytest.raises(NotFoundError):
        service.mark_delivered("nope")
    with pytest.raises(NotFoundError):
        service.update_courier_location("nope", DOWNTOWN)


def test_bad_numbers_are_rejected():
    service, _ = make_service()
    with pytest.raises(ValueError):
        service.add_courier("c1", DOWNTOWN, speed_kmh=0)
    with pytest.raises(ValueError):
        service.create_order("o1", DOWNTOWN, CUSTOMER, prep_minutes=-1)
    assert service.orders == {} and service.couriers == {}


def test_courier_location_update_changes_who_is_nearest():
    service, _ = make_service()
    service.add_courier("a", NEAR_DOWNTOWN)
    service.add_courier("b", FAR_AWAY)
    service.update_courier_location("a", FAR_AWAY)
    service.update_courier_location("b", NEAR_DOWNTOWN)
    assert service.create_order("o1", DOWNTOWN, CUSTOMER, 0).courier_id == "b"


def slow_nearest_courier(order, idle_couriers):
    # Sleeping inside the decision widens the window between "who is idle?" and
    # "mark them busy", so without the lock two threads reliably pick the same courier.
    time.sleep(0.002)
    return nearest_idle_courier(order, idle_couriers)


def test_concurrent_orders_never_share_a_courier():
    service = DispatchService(dispatch_policy=slow_nearest_courier)
    courier_count = 20
    for i in range(courier_count):
        service.add_courier(f"c{i}", NEAR_DOWNTOWN)

    errors = []
    start = threading.Barrier(8)

    def place_orders(thread_number):
        start.wait()
        for i in range(10):
            try:
                service.create_order(f"t{thread_number}-o{i}", DOWNTOWN, CUSTOMER, 0)
            except Exception as error:  # noqa: BLE001 - any error here means a race broke the state
                errors.append(error)

    threads = [threading.Thread(target=place_orders, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assigned = [o for o in service.orders.values() if o.courier_id is not None]
    # 80 orders, 20 couriers: exactly 20 assigned, each to a different courier.
    assert len(assigned) == courier_count
    assert len({o.courier_id for o in assigned}) == courier_count
    assert len(service.waiting_orders) == 80 - courier_count
