"""Plays out orders and couriers on top of the event engine.

Every order goes through the same four events:

    order_created                  -> the order joins the waiting list, dispatch runs
    courier_arrived_at_restaurant  -> the courier waits for the food if it isn't ready
    order_picked_up                -> the courier heads to the customer
    order_delivered                -> the courier is free again, dispatch runs

Which courier gets which order is NOT decided here. That's the dispatch policy's
job, passed in as a function, so different strategies can run on exactly the same
simulator and be compared fairly.
"""

from collections import deque
from collections.abc import Callable

from dispatchsim.simulator.event_engine import Event, EventEngine
from dispatchsim.simulator.location import travel_time_seconds
from dispatchsim.simulator.models import Courier, Order

# Given an order and the couriers who are idle right now, pick one (or None to
# leave the order waiting until the next dispatch attempt).
DispatchPolicy = Callable[[Order, list[Courier]], Courier | None]
AssignmentObserver = Callable[[Order, Courier, float], None]


class Simulation:
    def __init__(self, couriers: list[Courier], dispatch_policy: DispatchPolicy) -> None:
        self.assignment_observer: AssignmentObserver | None = None
        self.engine = EventEngine()
        self.dispatch_policy = dispatch_policy
        self.couriers = {courier.courier_id: courier for courier in couriers}
        if len(self.couriers) != len(couriers):
            raise ValueError("courier ids must be unique")
        self.orders: dict[str, Order] = {}
        # Oldest order first, so an order that has waited longest gets the first
        # chance at a courier when one frees up.
        self.waiting_orders: deque[str] = deque()

        self.engine.on("order_created", self._on_order_created)
        self.engine.on("courier_arrived_at_restaurant", self._on_courier_arrived)
        self.engine.on("order_picked_up", self._on_order_picked_up)
        self.engine.on("order_delivered", self._on_order_delivered)

    @property
    def current_time(self) -> float:
        return self.engine.current_time

    def add_order(self, order: Order) -> None:
        """Queue an order to show up at its created_at time."""
        if order.order_id in self.orders:
            raise ValueError(f"duplicate order id {order.order_id}")
        self.orders[order.order_id] = order
        self.engine.schedule(Event(order.created_at, "order_created", order.order_id))

    def run_until(self, end_time: float) -> None:
        self.engine.run_until(end_time)

    def delivered_orders(self) -> list[Order]:
        return [order for order in self.orders.values() if order.delivered_at is not None]

    # Dispatching

    def _dispatch_waiting_orders(self, now: float) -> None:
        while self.waiting_orders:
            idle_couriers = [c for c in self.couriers.values() if c.is_available]
            if not idle_couriers:
                return
            order = self.orders[self.waiting_orders[0]]
            courier = self.dispatch_policy(order, idle_couriers)
            if courier is None:
                # Stop instead of trying younger orders, so a policy can't keep
                # skipping the oldest order forever.
                return
            self.waiting_orders.popleft()
            self._assign(order, courier, now)

    def _assign(self, order: Order, courier: Courier, now: float) -> None:
        if self.assignment_observer is not None:
            self.assignment_observer(order, courier, now)
        order.assign(courier.courier_id, now)
        courier.start_order(order.order_id)
        trip = travel_time_seconds(courier.location, order.restaurant, courier.speed_kmh)
        self.engine.schedule(Event(now + trip, "courier_arrived_at_restaurant", order.order_id))

    # Event handlers

    def _on_order_created(self, event: Event, engine: EventEngine) -> None:
        self.waiting_orders.append(event.payload)
        self._dispatch_waiting_orders(engine.current_time)

    def _on_courier_arrived(self, event: Event, engine: EventEngine) -> None:
        order = self.orders[event.payload]
        # If the kitchen is still cooking, the courier waits. Scheduling the pickup
        # for "now" is fine too: the engine allows events at the current time.
        pickup_time = max(engine.current_time, order.food_ready_at)
        engine.schedule(Event(pickup_time, "order_picked_up", order.order_id))

    def _on_order_picked_up(self, event: Event, engine: EventEngine) -> None:
        order = self.orders[event.payload]
        courier = self.couriers[order.courier_id]
        order.pick_up(engine.current_time)
        courier.leave_restaurant_with_food(order.restaurant)
        trip = travel_time_seconds(order.restaurant, order.customer, courier.speed_kmh)
        engine.schedule(Event(engine.current_time + trip, "order_delivered", order.order_id))

    def _on_order_delivered(self, event: Event, engine: EventEngine) -> None:
        order = self.orders[event.payload]
        courier = self.couriers[order.courier_id]
        order.deliver(engine.current_time)
        courier.finish_delivery(order.customer)
        # This courier is free now, so an order that was waiting can go out.
        self._dispatch_waiting_orders(engine.current_time)
