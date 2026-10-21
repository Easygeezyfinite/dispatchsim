"""Orders and couriers, the two things the dispatcher moves around.

Both keep a status and only allow the transitions that make sense, e.g. an
order can't be delivered before it's picked up. Catching those mistakes here
means a bug in a dispatch strategy fails loudly instead of producing quietly
wrong delivery times.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from dispatchsim.simulator.location import Location


class OrderStatus(Enum):
    WAITING_FOR_COURIER = "waiting_for_courier"
    ASSIGNED = "assigned"
    PICKED_UP = "picked_up"
    DELIVERED = "delivered"


class CourierStatus(Enum):
    IDLE = "idle"
    HEADING_TO_RESTAURANT = "heading_to_restaurant"
    HEADING_TO_CUSTOMER = "heading_to_customer"


@dataclass
class Order:
    order_id: str
    restaurant: Location
    customer: Location
    created_at: float  # simulation seconds
    food_ready_at: float  # when the restaurant finishes cooking
    status: OrderStatus = OrderStatus.WAITING_FOR_COURIER
    courier_id: Optional[str] = None
    assigned_at: Optional[float] = None
    picked_up_at: Optional[float] = None
    delivered_at: Optional[float] = None

    def __post_init__(self) -> None:
        if self.food_ready_at < self.created_at:
            raise ValueError("food can't be ready before the order was placed")

    def _require_status(self, expected: OrderStatus, action: str) -> None:
        if self.status != expected:
            raise ValueError(
                f"order {self.order_id}: can't {action} while {self.status.value}"
            )

    def assign(self, courier_id: str, now: float) -> None:
        self._require_status(OrderStatus.WAITING_FOR_COURIER, "assign")
        self.courier_id = courier_id
        self.assigned_at = now
        self.status = OrderStatus.ASSIGNED

    def pick_up(self, now: float) -> None:
        self._require_status(OrderStatus.ASSIGNED, "pick up")
        # A courier who arrives early has to wait for the kitchen.
        if now < self.food_ready_at:
            raise ValueError(f"order {self.order_id}: food isn't ready until {self.food_ready_at}")
        self.picked_up_at = now
        self.status = OrderStatus.PICKED_UP

    def deliver(self, now: float) -> None:
        self._require_status(OrderStatus.PICKED_UP, "deliver")
        self.delivered_at = now
        self.status = OrderStatus.DELIVERED

    @property
    def delivery_time_seconds(self) -> Optional[float]:
        """Customer-facing number: from placing the order to getting the food."""
        if self.delivered_at is None:
            return None
        return self.delivered_at - self.created_at

    @property
    def wait_for_courier_seconds(self) -> Optional[float]:
        """How long the order sat before any courier was assigned."""
        if self.assigned_at is None:
            return None
        return self.assigned_at - self.created_at


@dataclass
class Courier:
    courier_id: str
    location: Location
    speed_kmh: float = 20.0  # roughly a bike or scooter in city traffic
    status: CourierStatus = CourierStatus.IDLE
    current_order_id: Optional[str] = None

    @property
    def is_available(self) -> bool:
        return self.status == CourierStatus.IDLE

    def start_order(self, order_id: str) -> None:
        if not self.is_available:
            raise ValueError(f"courier {self.courier_id} is busy with {self.current_order_id}")
        self.current_order_id = order_id
        self.status = CourierStatus.HEADING_TO_RESTAURANT

    def leave_restaurant_with_food(self, restaurant: Location) -> None:
        if self.status != CourierStatus.HEADING_TO_RESTAURANT:
            raise ValueError(f"courier {self.courier_id} isn't heading to a restaurant")
        self.location = restaurant
        self.status = CourierStatus.HEADING_TO_CUSTOMER

    def finish_delivery(self, customer: Location) -> None:
        if self.status != CourierStatus.HEADING_TO_CUSTOMER:
            raise ValueError(f"courier {self.courier_id} has no order to drop off")
        # The courier ends up wherever the customer is, which matters for the next order.
        self.location = customer
        self.current_order_id = None
        self.status = CourierStatus.IDLE
