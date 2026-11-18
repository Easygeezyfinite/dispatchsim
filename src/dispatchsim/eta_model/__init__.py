"""Interface for simulator travel and restaurant preparation times."""

from random import Random
from typing import Protocol

from dispatchsim.simulator.location import Location


class ETAModel(Protocol):
    """Provide durations in seconds for a trip or an order's preparation.

    Departure and order timestamps are seconds from the start of the simulation.
    """

    def travel_time_seconds(
        self,
        start: Location,
        end: Location,
        speed_kmh: float,
        *,
        departure_at: float,
    ) -> float:
        """Estimate travel duration for a courier departing at the given time."""
        ...

    def prep_time_seconds(
        self,
        restaurant: Location,
        *,
        created_at: float,
        min_prep_minutes: float,
        max_prep_minutes: float,
        rng: Random,
    ) -> float:
        """Sample a prep duration using the scenario's bounds and random generator."""
        ...
