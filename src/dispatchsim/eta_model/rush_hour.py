"""Time-of-day travel and prep heuristics for the simulator."""

from random import Random

from dispatchsim.eta_model.baseline import BaselineETAModel
from dispatchsim.simulator.location import Location

SECONDS_PER_HOUR = 3600
HOURS_PER_DAY = 24
RUSH_HOUR_WINDOWS = ((7, 9), (16, 19))
RUSH_HOUR_TRAVEL_MULTIPLIER = 1.35


class RushHourETAModel(BaselineETAModel):
    """Apply rush-hour travel and prep adjustments on a repeating simulated day.

    Simulation time zero is midnight. Each rush-hour window includes its
    start and excludes its end. The departure time sets the whole trip's rate.
    """

    def travel_time_seconds(
        self,
        start: Location,
        end: Location,
        speed_kmh: float,
        *,
        departure_at: float,
    ) -> float:
        duration = super().travel_time_seconds(
            start, end, speed_kmh, departure_at=departure_at
        )
        if _is_rush_hour(departure_at):
            return duration * RUSH_HOUR_TRAVEL_MULTIPLIER
        return duration


    def prep_time_seconds(
        self,
        restaurant: Location,
        *,
        created_at: float,
        min_prep_minutes: float,
        max_prep_minutes: float,
        rng: Random,
    ) -> float:
        """Bias rush-hour prep toward the upper end of the scenario's range."""
        if _is_rush_hour(created_at):
            return rng.triangular(min_prep_minutes, max_prep_minutes, max_prep_minutes) * 60
        return super().prep_time_seconds(
            restaurant,
            created_at=created_at,
            min_prep_minutes=min_prep_minutes,
            max_prep_minutes=max_prep_minutes,
            rng=rng,
        )


def _is_rush_hour(timestamp: float) -> bool:
    hour = (timestamp / SECONDS_PER_HOUR) % HOURS_PER_DAY
    return any(start_hour <= hour < end_hour for start_hour, end_hour in RUSH_HOUR_WINDOWS)
