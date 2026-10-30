"""Baseline strategy: send the idle courier who can reach the restaurant fastest.

This is what a simple dispatcher does and what the smarter strategies have to beat.
It only looks at one order at a time, so it can make choices that look good now but
leave a later order with a far-away courier.
"""


from dispatchsim.simulator.location import travel_time_seconds
from dispatchsim.simulator.models import Courier, Order


def nearest_idle_courier(order: Order, idle_couriers: list[Courier]) -> Courier | None:
    if not idle_couriers:
        return None
    # Compare travel time rather than raw distance, so a faster courier a bit further
    # away can still win. With equal speeds it's the same as picking the closest one.
    # min() keeps the first courier on ties, which keeps runs deterministic.
    return min(
        idle_couriers,
        key=lambda courier: travel_time_seconds(
            courier.location, order.restaurant, courier.speed_kmh
        ),
    )
