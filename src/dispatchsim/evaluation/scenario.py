"""Builds a random but repeatable city: restaurants, couriers and a stream of orders.

Everything random comes from one random.Random(seed). Same seed and same config
means the exact same orders and couriers every time, on any machine, which is what
makes a strategy comparison reproducible. We never touch the global `random`
module, so other code calling random.seed() or random.random() can't change a run.

Each call returns brand new Order and Courier objects. The simulator mutates them
(status, courier location), so two strategies must never share the same objects.
"""

import math
import random
from dataclasses import dataclass

from dispatchsim.simulator.location import Location
from dispatchsim.simulator.models import Courier, Order

# Downtown Calgary. Any city works; the numbers only need to look like a real place.
CITY_CENTER = Location(51.0447, -114.0631)
KM_PER_DEGREE_LATITUDE = 111.32


@dataclass(frozen=True)
class ScenarioConfig:
    order_count: int = 2000
    courier_count: int = 40
    orders_per_hour: float = 60.0
    restaurant_count: int = 40
    city_radius_km: float = 5.0
    min_prep_minutes: float = 5.0
    max_prep_minutes: float = 15.0
    courier_speed_kmh: float = 20.0

    def __post_init__(self) -> None:
        if self.order_count < 1 or self.courier_count < 1 or self.restaurant_count < 1:
            raise ValueError("need at least one order, courier and restaurant")
        if self.orders_per_hour <= 0 or self.city_radius_km <= 0:
            raise ValueError("orders_per_hour and city_radius_km must be positive")
        if not 0 <= self.min_prep_minutes <= self.max_prep_minutes:
            raise ValueError("need 0 <= min_prep_minutes <= max_prep_minutes")


def random_point_in_city(rng: random.Random, radius_km: float) -> Location:
    """Uniform random point within radius_km of the city center.

    Taking sqrt of the random fraction matters: without it points bunch up near the
    center, because a ring far out has more area than a ring close in.
    """
    distance_km = radius_km * math.sqrt(rng.random())
    angle = rng.uniform(0, 2 * math.pi)
    north_km = distance_km * math.sin(angle)
    east_km = distance_km * math.cos(angle)
    # A degree of longitude gets shorter the further you are from the equator.
    km_per_degree_longitude = KM_PER_DEGREE_LATITUDE * math.cos(
        math.radians(CITY_CENTER.latitude)
    )
    return Location(
        CITY_CENTER.latitude + north_km / KM_PER_DEGREE_LATITUDE,
        CITY_CENTER.longitude + east_km / km_per_degree_longitude,
    )


def generate_scenario(config: ScenarioConfig, seed: int) -> tuple[list[Order], list[Courier]]:
    rng = random.Random(seed)
    radius = config.city_radius_km

    restaurants = [random_point_in_city(rng, radius) for _ in range(config.restaurant_count)]
    couriers = [
        Courier(f"c{index}", random_point_in_city(rng, radius), config.courier_speed_kmh)
        for index in range(config.courier_count)
    ]

    # Orders arrive as a Poisson process: the gap between two orders is exponential
    # with mean 3600 / orders_per_hour seconds. Busy and quiet stretches happen
    # naturally, unlike a fixed gap where orders would arrive like a metronome.
    orders = []
    arrivals_per_second = config.orders_per_hour / 3600
    created_at = 0.0
    for index in range(config.order_count):
        created_at += rng.expovariate(arrivals_per_second)
        prep_seconds = rng.uniform(config.min_prep_minutes, config.max_prep_minutes) * 60
        orders.append(
            Order(
                order_id=f"o{index}",
                restaurant=rng.choice(restaurants),
                customer=random_point_in_city(rng, radius),
                created_at=created_at,
                food_ready_at=created_at + prep_seconds,
            )
        )
    return orders, couriers
