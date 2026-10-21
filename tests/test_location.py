import math

import pytest

from dispatchsim.simulator.location import (
    ROAD_DETOUR_FACTOR,
    Location,
    distance_km,
    travel_time_seconds,
)

CALGARY_TOWER = Location(51.0447, -114.0631)
UNIVERSITY_OF_CALGARY = Location(51.0781, -114.1358)


def test_distance_to_same_point_is_zero():
    assert distance_km(CALGARY_TOWER, CALGARY_TOWER) == 0


def test_one_degree_of_latitude_is_about_111_km():
    equator = Location(0, 0)
    one_degree_north = Location(1, 0)
    assert math.isclose(distance_km(equator, one_degree_north), 111.19, rel_tol=0.001)


def test_distance_is_symmetric():
    there = distance_km(CALGARY_TOWER, UNIVERSITY_OF_CALGARY)
    back = distance_km(UNIVERSITY_OF_CALGARY, CALGARY_TOWER)
    assert math.isclose(there, back)


def test_downtown_to_university_is_a_few_km():
    # Sanity check against a map: roughly 6 km in a straight line.
    assert 5 < distance_km(CALGARY_TOWER, UNIVERSITY_OF_CALGARY) < 7


def test_travel_time_uses_road_detour():
    equator, one_degree_north = Location(0, 0), Location(1, 0)
    straight_km = distance_km(equator, one_degree_north)
    expected_seconds = straight_km * ROAD_DETOUR_FACTOR / 20 * 3600
    assert math.isclose(travel_time_seconds(equator, one_degree_north, 20), expected_seconds)


def test_rejects_invalid_coordinates_and_speed():
    with pytest.raises(ValueError):
        Location(91, 0)
    with pytest.raises(ValueError):
        Location(0, -181)
    with pytest.raises(ValueError):
        travel_time_seconds(CALGARY_TOWER, UNIVERSITY_OF_CALGARY, 0)
