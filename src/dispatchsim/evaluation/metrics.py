"""Turns a finished simulation into a few numbers we can compare across strategies.

Delivery time (order placed -> food delivered) is what the customer feels.
Wait for courier (order placed -> courier assigned) shows how much of that is the
dispatcher being slow or short on couriers, versus just travel and cooking time.
"""

import math
from dataclasses import dataclass

from dispatchsim.simulator.models import Order


@dataclass
class DeliveryMetrics:
    total_orders: int
    delivered_orders: int
    mean_delivery_seconds: float | None
    p90_delivery_seconds: float | None
    mean_wait_for_courier_seconds: float | None

    @property
    def undelivered_orders(self) -> int:
        return self.total_orders - self.delivered_orders


def percentile(values: list[float], percent: float) -> float:
    """Nearest-rank percentile: the smallest value that at least `percent`% of values are <=.

    Simple and always returns a value that actually happened, which is easier to
    explain than an interpolated number.
    """
    if not values:
        raise ValueError("can't take a percentile of no values")
    if not 0 < percent <= 100:
        raise ValueError("percent must be in (0, 100]")
    ordered = sorted(values)
    rank = math.ceil(percent / 100 * len(ordered))
    return ordered[rank - 1]


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def summarize_orders(orders: list[Order]) -> DeliveryMetrics:
    """Summary stats over delivered orders.

    Orders still in progress when the simulation stopped are counted in
    total_orders but left out of the averages, since they have no delivery time
    yet. If undelivered_orders is large, the averages look better than reality,
    so check it before comparing strategies (or run the sim long enough to drain).
    """
    delivery_times = [
        o.delivery_time_seconds for o in orders if o.delivery_time_seconds is not None
    ]
    # Only orders that were also delivered, so both averages cover the same set.
    wait_times = [
        o.wait_for_courier_seconds
        for o in orders
        if o.delivery_time_seconds is not None and o.wait_for_courier_seconds is not None
    ]
    return DeliveryMetrics(
        total_orders=len(orders),
        delivered_orders=len(delivery_times),
        mean_delivery_seconds=_mean(delivery_times),
        p90_delivery_seconds=percentile(delivery_times, 90) if delivery_times else None,
        mean_wait_for_courier_seconds=_mean(wait_times),
    )
