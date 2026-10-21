"""Where things are, and how long it takes to get between them.

Locations are latitude/longitude pairs, so real order data (which comes with
coordinates) can be replayed later without converting anything.

Distance is the straight-line "as the crow flies" distance. Real couriers follow
roads, which is longer, so ROAD_DETOUR_FACTOR stretches it a bit. A road-network
router would be more accurate but is a lot of extra machinery for a simulator
whose job is comparing dispatch strategies against each other.
"""

import math
from dataclasses import dataclass

EARTH_RADIUS_KM = 6371.0

# Roads are rarely straight. 1.3 is a common rule of thumb for city grids.
ROAD_DETOUR_FACTOR = 1.3


@dataclass(frozen=True)
class Location:
    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        if not -90 <= self.latitude <= 90:
            raise ValueError(f"latitude must be between -90 and 90, got {self.latitude}")
        if not -180 <= self.longitude <= 180:
            raise ValueError(f"longitude must be between -180 and 180, got {self.longitude}")


def distance_km(start: Location, end: Location) -> float:
    """Great-circle distance between two points (haversine formula)."""
    lat1, lon1 = math.radians(start.latitude), math.radians(start.longitude)
    lat2, lon2 = math.radians(end.latitude), math.radians(end.longitude)

    half_chord = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    # min() guards against floating point pushing the value a hair above 1,
    # which would make asin() raise.
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(half_chord)))


def travel_time_seconds(start: Location, end: Location, speed_kmh: float) -> float:
    """Estimated travel time for a courier moving at speed_kmh along city roads."""
    if speed_kmh <= 0:
        raise ValueError("speed_kmh must be positive")
    road_distance_km = distance_km(start, end) * ROAD_DETOUR_FACTOR
    return road_distance_km / speed_kmh * 3600
