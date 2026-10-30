import typing

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")  # TestClient needs it

from fastapi.testclient import TestClient

from dispatchsim.dispatch_service.app import SimulationIn, create_app
from dispatchsim.dispatch_service.service import DispatchService
from dispatchsim.evaluation.experiment import STRATEGIES

DOWNTOWN = {"latitude": 51.0447, "longitude": -114.0631}
NEAR_DOWNTOWN = {"latitude": 51.0460, "longitude": -114.0640}
CUSTOMER = {"latitude": 51.0380, "longitude": -114.0800}


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make_client():
    clock = FakeClock()
    return TestClient(create_app(DispatchService(clock=clock))), clock


def new_order(order_id, prep_minutes=10):
    return {"order_id": order_id, "restaurant": DOWNTOWN, "customer": CUSTOMER,
            "prep_minutes": prep_minutes}


def test_health():
    client, _ = make_client()
    assert client.get("/health").json() == {"status": "ok"}


def test_order_lifecycle_over_http():
    client, clock = make_client()
    response = client.post("/couriers", json={"courier_id": "c1", "location": NEAR_DOWNTOWN})
    assert response.status_code == 201
    assert response.json()["status"] == "idle"

    response = client.post("/orders", json=new_order("o1"))
    assert response.status_code == 201
    assert response.json()["status"] == "assigned"
    assert response.json()["courier_id"] == "c1"

    clock.now += 600
    assert client.post("/orders/o1/pickup").json()["status"] == "picked_up"
    clock.now += 300
    delivered = client.post("/orders/o1/deliver").json()
    assert delivered["status"] == "delivered"
    assert delivered["delivery_time_seconds"] == 900

    stats = client.get("/stats").json()
    assert stats["delivered_orders"] == 1
    assert stats["mean_delivery_seconds"] == 900
    assert stats["idle_couriers"] == 1
    assert client.get("/couriers/c1").json()["location"] == CUSTOMER


def test_order_without_courier_waits():
    client, _ = make_client()
    body = client.post("/orders", json=new_order("o1")).json()
    assert body["status"] == "waiting_for_courier"
    assert body["courier_id"] is None
    assert client.get("/stats").json()["waiting_orders"] == 1


def test_error_status_codes():
    client, _ = make_client()
    assert client.get("/orders/missing").status_code == 404
    assert client.get("/couriers/missing").status_code == 404
    client.post("/orders", json=new_order("o1"))
    assert client.post("/orders", json=new_order("o1")).status_code == 409
    assert client.post("/orders/o1/deliver").status_code == 409
    client.post("/couriers", json={"courier_id": "c1", "location": NEAR_DOWNTOWN})
    # Food takes 10 minutes and no time has passed.
    assert client.post("/orders/o1/pickup").status_code == 409


def test_invalid_input_is_422():
    client, _ = make_client()
    bad_latitude = {"courier_id": "c1", "location": {"latitude": 95, "longitude": 0}}
    assert client.post("/couriers", json=bad_latitude).status_code == 422
    assert client.post("/orders", json=new_order("o1", prep_minutes=-5)).status_code == 422
    assert client.post("/orders", json={"order_id": "o2"}).status_code == 422
    empty_id = {"courier_id": "", "location": DOWNTOWN}
    assert client.post("/couriers", json=empty_id).status_code == 422


def test_update_courier_location():
    client, _ = make_client()
    client.post("/couriers", json={"courier_id": "c1", "location": DOWNTOWN})
    response = client.put("/couriers/c1/location", json=CUSTOMER)
    assert response.status_code == 200
    assert response.json()["location"] == CUSTOMER


def test_simulate_is_repeatable():
    client, _ = make_client()
    request = {"strategy": "hungarian_batch", "seed": 3, "order_count": 200,
               "courier_count": 15, "orders_per_hour": 40}
    first = client.post("/simulate", json=request).json()
    second = client.post("/simulate", json=request).json()
    assert first == second
    assert first["delivered_orders"] == 200
    assert first["undelivered_orders"] == 0


def test_simulate_rejects_huge_or_unknown_requests():
    client, _ = make_client()
    assert client.post("/simulate", json={"order_count": 10_000_000}).status_code == 422
    assert client.post("/simulate", json={"strategy": "random"}).status_code == 422


def test_simulate_offers_every_strategy_the_runner_has():
    allowed = typing.get_args(SimulationIn.model_fields["strategy"].annotation)
    assert set(allowed) == set(STRATEGIES)
