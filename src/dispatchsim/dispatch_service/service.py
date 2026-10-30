"""The live version of the dispatcher: real requests instead of simulated events.

The simulator decides when things happen (it schedules "courier arrived" etc.).
Here the outside world tells us instead: a restaurant posts an order, a courier's
app reports a pickup or a drop-off. The dispatching rule is the same as the
simulator's baseline: the oldest waiting order gets the nearest idle courier.

This class knows nothing about HTTP, so it can be tested on its own and the web
layer (app.py) stays a thin wrapper.

FastAPI runs plain `def` endpoints in a thread pool, so two requests can be inside
this object at the same time. Every public method takes the same lock, otherwise two
orders arriving together could both pick the same idle courier.
"""

import threading
import time
from collections import deque
from collections.abc import Callable

from dispatchsim.evaluation.metrics import DeliveryMetrics, summarize_orders
from dispatchsim.policies.nearest_courier import nearest_idle_courier
from dispatchsim.simulator.location import Location
from dispatchsim.simulator.models import Courier, Order
from dispatchsim.simulator.simulation import DispatchPolicy


class NotFoundError(Exception):
    """No order or courier with that id."""


class ConflictError(Exception):
    """The request doesn't fit the current state (duplicate id, wrong status, ...)."""


class DispatchService:
    def __init__(
        self,
        dispatch_policy: DispatchPolicy = nearest_idle_courier,
        clock: Callable[[], float] = time.time,
    ) -> None:
        # The clock is injectable so tests can control time instead of sleeping.
        self.dispatch_policy = dispatch_policy
        self.clock = clock
        self.couriers: dict[str, Courier] = {}
        self.orders: dict[str, Order] = {}
        self.waiting_orders: deque[str] = deque()
        self._lock = threading.Lock()

    # Couriers

    def add_courier(self, courier_id: str, location: Location, speed_kmh: float = 20.0) -> Courier:
        with self._lock:
            if courier_id in self.couriers:
                raise ConflictError(f"courier {courier_id} already exists")
            if speed_kmh <= 0:
                raise ValueError("speed_kmh must be positive")
            courier = Courier(courier_id, location, speed_kmh)
            self.couriers[courier_id] = courier
            # A new courier might be exactly what a waiting order needs.
            self._dispatch_waiting_orders()
            return courier

    def update_courier_location(self, courier_id: str, location: Location) -> Courier:
        with self._lock:
            courier = self._get_courier(courier_id)
            courier.location = location
            return courier

    def get_courier(self, courier_id: str) -> Courier:
        with self._lock:
            return self._get_courier(courier_id)

    # Orders

    def create_order(
        self, order_id: str, restaurant: Location, customer: Location, prep_minutes: float
    ) -> Order:
        with self._lock:
            if order_id in self.orders:
                raise ConflictError(f"order {order_id} already exists")
            if prep_minutes < 0:
                raise ValueError("prep_minutes can't be negative")
            now = self.clock()
            order = Order(order_id, restaurant, customer, now, now + prep_minutes * 60)
            self.orders[order_id] = order
            self.waiting_orders.append(order_id)
            self._dispatch_waiting_orders()
            return order

    def get_order(self, order_id: str) -> Order:
        with self._lock:
            return self._get_order(order_id)

    def mark_picked_up(self, order_id: str) -> Order:
        with self._lock:
            order = self._get_order(order_id)
            if order.courier_id is None:
                raise ConflictError(f"order {order_id} has no courier yet")
            courier = self.couriers[order.courier_id]
            try:
                order.pick_up(self.clock())
            except ValueError as error:
                # Wrong status, or the food isn't ready yet.
                raise ConflictError(str(error)) from error
            courier.leave_restaurant_with_food(order.restaurant)
            return order

    def mark_delivered(self, order_id: str) -> Order:
        with self._lock:
            order = self._get_order(order_id)
            try:
                order.deliver(self.clock())
            except ValueError as error:
                raise ConflictError(str(error)) from error
            courier = self.couriers[order.courier_id]
            courier.finish_delivery(order.customer)
            # The courier is free again, so the oldest waiting order can go out.
            self._dispatch_waiting_orders()
            return order

    def stats(self) -> tuple[DeliveryMetrics, int, int]:
        """Delivery metrics so far, plus how many orders are waiting and couriers idle."""
        with self._lock:
            metrics = summarize_orders(list(self.orders.values()))
            idle_count = sum(1 for courier in self.couriers.values() if courier.is_available)
            return metrics, len(self.waiting_orders), idle_count

    # Internals (caller must already hold the lock)

    def _get_order(self, order_id: str) -> Order:
        if order_id not in self.orders:
            raise NotFoundError(f"no order {order_id}")
        return self.orders[order_id]

    def _get_courier(self, courier_id: str) -> Courier:
        if courier_id not in self.couriers:
            raise NotFoundError(f"no courier {courier_id}")
        return self.couriers[courier_id]

    def _dispatch_waiting_orders(self) -> None:
        # Same loop as Simulation._dispatch_waiting_orders: oldest order first, and
        # stop if the policy passes on it so it can't be skipped forever.
        now = self.clock()
        while self.waiting_orders:
            idle_couriers = [c for c in self.couriers.values() if c.is_available]
            if not idle_couriers:
                return
            order = self.orders[self.waiting_orders[0]]
            courier = self.dispatch_policy(order, idle_couriers)
            if courier is None:
                return
            self.waiting_orders.popleft()
            order.assign(courier.courier_id, now)
            courier.start_order(order.order_id)
