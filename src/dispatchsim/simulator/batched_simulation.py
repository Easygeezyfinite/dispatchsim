"""A simulation where dispatch runs in batches every few seconds instead of instantly.

The plain Simulation assigns a courier the moment an order arrives. Here, orders
collect for up to batch_interval_seconds, then a batch policy matches all waiting
orders to all idle couriers in one go. Waiting a little can pay off if the better
matching saves more travel time than the batching delay costs. The experiment
runner is what tells us whether it actually does.
"""

from collections import deque
from collections.abc import Callable

from dispatchsim.simulator.event_engine import Event, EventEngine
from dispatchsim.simulator.models import Courier, Order
from dispatchsim.simulator.simulation import Simulation

# Given waiting orders (oldest first) and idle couriers, return (order, courier) pairs.
BatchDispatchPolicy = Callable[[list[Order], list[Courier]], list[tuple[Order, Courier]]]


class BatchedSimulation(Simulation):
    def __init__(
        self,
        couriers: list[Courier],
        batch_policy: BatchDispatchPolicy,
        batch_interval_seconds: float = 30.0,
    ) -> None:
        if batch_interval_seconds <= 0:
            raise ValueError("batch_interval_seconds must be positive")
        # The per-order policy isn't used: every assignment goes through _on_dispatch_tick.
        super().__init__(couriers, dispatch_policy=None)
        self.batch_policy = batch_policy
        self.batch_interval_seconds = batch_interval_seconds
        # Rule we keep: if any order is waiting, a dispatch tick is on the calendar.
        # That way no order can get stuck, and we never schedule duplicate ticks.
        self._tick_scheduled = False
        self.engine.on("dispatch_tick", self._on_dispatch_tick)

    def _dispatch_waiting_orders(self, now: float) -> None:
        # Called by the base class whenever an order arrives or a courier frees up.
        # Instead of assigning right away, make sure the next batch is coming.
        if self.waiting_orders and not self._tick_scheduled:
            self._schedule_tick(now)

    def _schedule_tick(self, now: float) -> None:
        self._tick_scheduled = True
        self.engine.schedule(Event(now + self.batch_interval_seconds, "dispatch_tick"))

    def _on_dispatch_tick(self, event: Event, engine: EventEngine) -> None:
        self._tick_scheduled = False
        now = engine.current_time
        waiting = [self.orders[order_id] for order_id in self.waiting_orders]
        idle_couriers = [c for c in self.couriers.values() if c.is_available]

        if waiting and idle_couriers:
            matches = self.batch_policy(waiting, idle_couriers)
            self._check_matches(matches, waiting, idle_couriers)
            matched_ids = set()
            for order, courier in matches:
                self._assign(order, courier, now)
                matched_ids.add(order.order_id)
            # Rebuild the queue without the matched orders, keeping oldest-first order.
            self.waiting_orders = deque(
                order_id for order_id in self.waiting_orders if order_id not in matched_ids
            )

        # Orders left over (not enough couriers) try again next tick.
        if self.waiting_orders:
            self._schedule_tick(now)

    @staticmethod
    def _check_matches(matches, waiting, idle_couriers) -> None:
        # A buggy policy should fail loudly here, not corrupt the simulation.
        waiting_ids = {o.order_id for o in waiting}
        idle_ids = {c.courier_id for c in idle_couriers}
        seen_orders, seen_couriers = set(), set()
        for order, courier in matches:
            if order.order_id not in waiting_ids or courier.courier_id not in idle_ids:
                raise ValueError(
                    f"policy matched {order.order_id} to {courier.courier_id}, "
                    "but only waiting orders and idle couriers can be matched"
                )
            if order.order_id in seen_orders or courier.courier_id in seen_couriers:
                raise ValueError("policy used the same order or courier twice in one batch")
            seen_orders.add(order.order_id)
            seen_couriers.add(courier.courier_id)
