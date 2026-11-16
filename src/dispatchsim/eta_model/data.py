"""Decision-time snapshots paired with observed assignment-to-delivery durations."""

import csv
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

from dispatchsim.evaluation.experiment import DRAIN_SECONDS, STRATEGIES, build_simulation
from dispatchsim.evaluation.scenario import ScenarioConfig, generate_scenario
from dispatchsim.simulator.location import distance_km
from dispatchsim.simulator.models import Courier, Order, OrderStatus


@dataclass(frozen=True)
class ETAFeatures:
    courier_to_restaurant_km: float
    restaurant_to_customer_km: float
    courier_speed_kmh: float
    estimated_prep_seconds: float
    order_age_seconds: float
    available_couriers: int
    outstanding_orders: int


def extract_features(
    order: Order,
    courier: Courier,
    now: float,
    *,
    estimated_prep_seconds: float,
    available_couriers: int,
    outstanding_orders: int,
) -> ETAFeatures:
    """No future timestamps or actual kitchen completion times are read here."""
    if not math.isfinite(now) or now < order.created_at:
        raise ValueError("decision must be at or after order creation")
    if not math.isfinite(estimated_prep_seconds) or estimated_prep_seconds < 0:
        raise ValueError("estimated prep must be finite and nonnegative")
    if not math.isfinite(courier.speed_kmh) or courier.speed_kmh <= 0:
        raise ValueError("courier speed must be finite and positive")
    if not courier.is_available or order.status != OrderStatus.WAITING_FOR_COURIER:
        raise ValueError("features require a waiting order and idle courier")
    if available_couriers < 1 or outstanding_orders < 1:
        raise ValueError("counts must include the candidate courier and order")
    return ETAFeatures(
        distance_km(courier.location, order.restaurant),
        distance_km(order.restaurant, order.customer),
        courier.speed_kmh,
        estimated_prep_seconds,
        now - order.created_at,
        available_couriers,
        outstanding_orders,
    )


@dataclass(frozen=True)
class ETAExample:
    seed: int
    strategy: str
    order_id: str
    courier_id: str
    decision_at: float
    features: ETAFeatures
    delivery_seconds: float


def generate_examples(
    config: ScenarioConfig,
    seeds: list[int],
    strategies: tuple[str, ...] = STRATEGIES,
    batch_interval_seconds: float = 30.0,
) -> list[ETAExample]:
    if not seeds or len(set(seeds)) != len(seeds):
        raise ValueError("need nonempty, unique seeds")
    if not strategies or len(set(strategies)) != len(strategies):
        raise ValueError("need nonempty, unique strategies")
    examples = []
    estimated_prep = (config.min_prep_minutes + config.max_prep_minutes) * 30
    for seed in seeds:
        for strategy in strategies:
            orders, couriers = generate_scenario(config, seed)
            sim = build_simulation(strategy, couriers, batch_interval_seconds)
            snapshots = []

            def capture(
                order: Order,
                courier: Courier,
                now: float,
                sim=sim,
                snapshots=snapshots,
            ) -> None:
                # sim.orders includes scheduled FUTURE orders; explicitly exclude them.
                features = extract_features(
                    order,
                    courier,
                    now,
                    estimated_prep_seconds=estimated_prep,
                    available_couriers=sum(c.is_available for c in sim.couriers.values()),
                    outstanding_orders=sum(
                        o.created_at <= now and o.delivered_at is None for o in sim.orders.values()
                    ),
                )
                snapshots.append((order, courier.courier_id, now, features))

            sim.assignment_observer = capture
            for order in orders:
                sim.add_order(order)
            sim.run_until(max(o.created_at for o in orders) + DRAIN_SECONDS)
            if any(o.delivered_at is None for o in orders):
                raise ValueError(f"{strategy} seed {seed} left orders undelivered")
            for order, courier_id, now, features in snapshots:
                examples.append(
                    ETAExample(
                        seed,
                        strategy,
                        order.order_id,
                        courier_id,
                        now,
                        features,
                        order.delivered_at - now,
                    )
                )
    return examples


def write_dataset(
    path: Path,
    examples: list[ETAExample],
    config: ScenarioConfig,
    seeds: list[int],
    strategies: tuple[str, ...] = STRATEGIES,
    batch_interval_seconds: float = 30.0,
) -> None:
    """Write stable CSV and a sidecar recording the generation settings."""
    if not examples:
        raise ValueError("cannot write an empty dataset")
    rows = []
    for example in examples:
        row = asdict(example)
        features = row.pop("features")
        rows.append({**row, **features})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    metadata = {
        "schema_version": 1,
        "target": "delivered_at - assigned_at (seconds)",
        "config": asdict(config),
        "seeds": seeds,
        "strategies": list(strategies),
        "batch_interval_seconds": batch_interval_seconds,
        "rows": len(rows),
        "prep_estimate": "scenario uniform-prep mean; actual readiness excluded",
    }
    path.with_suffix(".metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
