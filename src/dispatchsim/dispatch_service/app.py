"""HTTP API for the dispatch service.

Run it with:

    uvicorn dispatchsim.dispatch_service.app:app --reload

Interactive docs are at http://127.0.0.1:8000/docs once it's running.

All the dispatching logic lives in DispatchService. This file only turns JSON into
calls on it and turns its errors into status codes (404 unknown id, 409 wrong state).
State is in memory, so restarting the server starts from an empty city.
"""

from dataclasses import asdict
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from dispatchsim.dispatch_service.service import ConflictError, DispatchService, NotFoundError
from dispatchsim.evaluation.experiment import run_strategy
from dispatchsim.evaluation.scenario import ScenarioConfig
from dispatchsim.simulator.location import Location
from dispatchsim.simulator.models import Courier, Order

# A /simulate request runs synchronously inside the request, so keep it small enough
# to finish in a second or two. Bigger experiments belong in compare_strategies.py.
MAX_SIMULATED_ORDERS = 5000
MAX_SIMULATED_COURIERS = 200


class LocationIn(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)

    def to_location(self) -> Location:
        return Location(self.latitude, self.longitude)


class CourierIn(BaseModel):
    courier_id: str = Field(min_length=1, max_length=64)
    location: LocationIn
    speed_kmh: float = Field(default=20.0, gt=0, le=100)


class OrderIn(BaseModel):
    order_id: str = Field(min_length=1, max_length=64)
    restaurant: LocationIn
    customer: LocationIn
    prep_minutes: float = Field(default=10.0, ge=0, le=180)


class SimulationIn(BaseModel):
    strategy: Literal["nearest", "hungarian_batch"] = "nearest"
    seed: int = 1
    order_count: int = Field(default=500, ge=1, le=MAX_SIMULATED_ORDERS)
    courier_count: int = Field(default=40, ge=1, le=MAX_SIMULATED_COURIERS)
    orders_per_hour: float = Field(default=60.0, gt=0, le=1000)
    batch_interval_seconds: float = Field(default=30.0, gt=0, le=600)


def location_to_dict(location: Location) -> dict:
    return {"latitude": location.latitude, "longitude": location.longitude}


def courier_to_dict(courier: Courier) -> dict:
    return {
        "courier_id": courier.courier_id,
        "location": location_to_dict(courier.location),
        "speed_kmh": courier.speed_kmh,
        "status": courier.status.value,
        "current_order_id": courier.current_order_id,
    }


def order_to_dict(order: Order) -> dict:
    return {
        "order_id": order.order_id,
        "status": order.status.value,
        "courier_id": order.courier_id,
        "restaurant": location_to_dict(order.restaurant),
        "customer": location_to_dict(order.customer),
        "created_at": order.created_at,
        "food_ready_at": order.food_ready_at,
        "assigned_at": order.assigned_at,
        "picked_up_at": order.picked_up_at,
        "delivered_at": order.delivered_at,
        "delivery_time_seconds": order.delivery_time_seconds,
    }


def create_app(service: DispatchService | None = None) -> FastAPI:
    # Passing a service in lets each test start from a clean, clock-controlled one.
    service = service or DispatchService()
    api = FastAPI(title="DispatchSim")

    def call(action, *args):
        try:
            return action(*args)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @api.get("/health")
    def health():
        return {"status": "ok"}

    @api.post("/couriers", status_code=201)
    def add_courier(body: CourierIn):
        courier = call(
            service.add_courier, body.courier_id, body.location.to_location(), body.speed_kmh
        )
        return courier_to_dict(courier)

    @api.get("/couriers/{courier_id}")
    def get_courier(courier_id: str):
        return courier_to_dict(call(service.get_courier, courier_id))

    @api.put("/couriers/{courier_id}/location")
    def update_courier_location(courier_id: str, body: LocationIn):
        courier = call(service.update_courier_location, courier_id, body.to_location())
        return courier_to_dict(courier)

    @api.post("/orders", status_code=201)
    def create_order(body: OrderIn):
        order = call(
            service.create_order,
            body.order_id,
            body.restaurant.to_location(),
            body.customer.to_location(),
            body.prep_minutes,
        )
        return order_to_dict(order)

    @api.get("/orders/{order_id}")
    def get_order(order_id: str):
        return order_to_dict(call(service.get_order, order_id))

    @api.post("/orders/{order_id}/pickup")
    def pick_up_order(order_id: str):
        return order_to_dict(call(service.mark_picked_up, order_id))

    @api.post("/orders/{order_id}/deliver")
    def deliver_order(order_id: str):
        return order_to_dict(call(service.mark_delivered, order_id))

    @api.get("/stats")
    def stats():
        metrics, waiting_count, idle_count = service.stats()
        return {
            **asdict(metrics),
            "waiting_orders": waiting_count,
            "idle_couriers": idle_count,
        }

    @api.post("/simulate")
    def simulate(body: SimulationIn):
        # Runs one seeded scenario, so the same request always returns the same numbers.
        config = ScenarioConfig(
            order_count=body.order_count,
            courier_count=body.courier_count,
            orders_per_hour=body.orders_per_hour,
        )
        result = run_strategy(body.strategy, config, body.seed, body.batch_interval_seconds)
        return {
            "strategy": result.strategy,
            "seed": result.seed,
            "events_processed": result.events_processed,
            **asdict(result.metrics),
            "undelivered_orders": result.metrics.undelivered_orders,
        }

    return api


app = create_app()
