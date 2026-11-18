from random import Random

import pytest

from dispatchsim.eta_model.baseline import BaselineETAModel
from dispatchsim.eta_model.factory import create_eta_model
from dispatchsim.eta_model.rush_hour import RushHourETAModel
from dispatchsim.simulator.location import Location, travel_time_seconds


def test_baseline_travel_matches_existing_estimate_at_any_departure():
    model = BaselineETAModel()
    start = Location(51.0447, -114.0631)
    end = Location(51.0781, -114.1358)
    expected = travel_time_seconds(start, end, 18)

    assert model.travel_time_seconds(start, end, 18, departure_at=0) == expected
    assert model.travel_time_seconds(start, end, 18, departure_at=17 * 3600) == expected


def test_baseline_prep_preserves_the_seeded_uniform_draw():
    rng = Random(42)
    reference = Random(42)
    prep = BaselineETAModel().prep_time_seconds(
        Location(51.0447, -114.0631),
        created_at=120,
        min_prep_minutes=4,
        max_prep_minutes=12,
        rng=rng,
    )

    assert prep == reference.uniform(4, 12) * 60
    assert rng.getstate() == reference.getstate()


@pytest.mark.parametrize(
    ("hour", "rush_hour"),
    [(6, False), (7, True), (9, False), (16, True), (19, False), (31, True)],
)
def test_rush_hour_travel_and_prep_follow_daily_windows(hour, rush_hour):
    model = RushHourETAModel()
    restaurant = Location(51.0447, -114.0631)
    customer = Location(51.0781, -114.1358)
    timestamp = hour * 3600
    baseline = travel_time_seconds(restaurant, customer, 20)

    travel = model.travel_time_seconds(restaurant, customer, 20, departure_at=timestamp)
    assert travel == pytest.approx(baseline * (1.35 if rush_hour else 1))

    rng, reference = Random(42), Random(42)
    prep = model.prep_time_seconds(
        restaurant, created_at=timestamp, min_prep_minutes=5, max_prep_minutes=15, rng=rng
    )
    expected_minutes = reference.triangular(5, 15, 15) if rush_hour else reference.uniform(5, 15)
    assert prep == expected_minutes * 60
    assert rng.getstate() == reference.getstate()


def test_eta_model_factory_defaults_to_baseline():
    assert type(create_eta_model()) is BaselineETAModel


def test_eta_model_factory_selects_rush_hour():
    assert type(create_eta_model("rush-hour")) is RushHourETAModel


def test_eta_model_factory_rejects_unknown_names():
    with pytest.raises(ValueError, match="unknown ETA model 'rushhour'"):
        create_eta_model("rushhour")
