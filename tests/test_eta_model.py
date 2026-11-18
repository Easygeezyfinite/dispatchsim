from random import Random

from dispatchsim.eta_model.baseline import BaselineETAModel
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
