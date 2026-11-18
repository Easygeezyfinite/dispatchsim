"""ETA model that preserves the simulator's original time calculations."""

from random import Random

from dispatchsim.eta_model import ETAModel
from dispatchsim.simulator.location import Location, travel_time_seconds


class BaselineETAModel(ETAModel):
    """Use fixed road detours and seeded uniform restaurant prep times."""

    def travel_time_seconds(
        self,
        start: Location,
        end: Location,
        speed_kmh: float,
        *,
        departure_at: float,
    ) -> float:
        """Estimate travel using the existing detour factor and courier speed."""
        return travel_time_seconds(start, end, speed_kmh)

    def prep_time_seconds(
        self,
        restaurant: Location,
        *,
        created_at: float,
        min_prep_minutes: float,
        max_prep_minutes: float,
        rng: Random,
    ) -> float:
        """Draw from the scenario's prep-time range once and convert to seconds."""
        return rng.uniform(min_prep_minutes, max_prep_minutes) * 60
