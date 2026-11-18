"""Time-of-day travel heuristic for the simulator."""

from dispatchsim.eta_model.baseline import BaselineETAModel
from dispatchsim.simulator.location import Location

SECONDS_PER_HOUR = 3600
HOURS_PER_DAY = 24
RUSH_HOUR_WINDOWS = ((7, 9), (16, 19))
RUSH_HOUR_TRAVEL_MULTIPLIER = 1.35


class RushHourETAModel(BaselineETAModel):
    """Apply a rush-hour travel penalty on a repeating simulated day.

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
        hour = (departure_at / SECONDS_PER_HOUR) % HOURS_PER_DAY
        if any(start_hour <= hour < end_hour for start_hour, end_hour in RUSH_HOUR_WINDOWS):
            return duration * RUSH_HOUR_TRAVEL_MULTIPLIER
        return duration
