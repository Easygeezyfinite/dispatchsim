"""Load test for the dispatch API: many clients running orders through at once.

Each simulated client (one thread) repeats the life of one order:

    POST /orders  ->  GET /orders/{id}  ->  POST /orders/{id}/pickup  ->  POST /orders/{id}/deliver

so the mix is three writes to one read, and every write goes through the service
lock. Orders use prep_minutes=0 so pickup is allowed straight away.

There are two ways to send those requests:

- HttpClient talks to a running server over HTTP (the real measurement).
- InProcessClient calls DispatchService directly. It skips HTTP and JSON entirely,
  so it only shows how fast the dispatching logic and the lock are, and gives an
  upper bound for what the HTTP numbers could reach.

Only the standard library is used, so the benchmark doesn't need extra packages.
"""

import http.client
import json
import random
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlparse

from dispatchsim.dispatch_service.service import ConflictError, DispatchService, NotFoundError
from dispatchsim.evaluation.metrics import percentile
from dispatchsim.evaluation.scenario import random_point_in_city
from dispatchsim.simulator.location import Location

REQUESTS_PER_ORDER = 4
CITY_RADIUS_KM = 5.0


class HttpClient:
    """One keep-alive connection, so it must only be used by one thread."""

    def __init__(self, base_url: str, timeout_seconds: float = 10.0) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme != "http" or not parsed.hostname:
            raise ValueError(f"expected a URL like http://127.0.0.1:8000, got {base_url!r}")
        self.connection = http.client.HTTPConnection(
            parsed.hostname, parsed.port or 80, timeout=timeout_seconds
        )

    def send(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        headers = {}
        payload = None
        if body is not None:
            payload = json.dumps(body)
            headers["Content-Type"] = "application/json"
        try:
            self.connection.request(method, path, body=payload, headers=headers)
            response = self.connection.getresponse()
            raw = response.read()
        except (OSError, http.client.HTTPException):
            # The server dropped the connection. Close it so the next request
            # reconnects instead of failing forever, and let the caller count the error.
            self.connection.close()
            raise
        data = json.loads(raw) if raw else {}
        return response.status, data

    def close(self) -> None:
        self.connection.close()


class InProcessClient:
    """Same paths and status codes as the API, but calls the service directly."""

    def __init__(self, service: DispatchService) -> None:
        self.service = service

    def send(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        parts = path.strip("/").split("/")
        try:
            if method == "POST" and parts == ["couriers"]:
                courier = self.service.add_courier(body["courier_id"], _location(body["location"]))
                return 201, {"courier_id": courier.courier_id}
            if method == "POST" and parts == ["orders"]:
                order = self.service.create_order(
                    body["order_id"],
                    _location(body["restaurant"]),
                    _location(body["customer"]),
                    body["prep_minutes"],
                )
                return 201, {"order_id": order.order_id, "courier_id": order.courier_id}
            if len(parts) >= 2 and parts[0] == "orders":
                order_id = parts[1]
                if method == "GET" and len(parts) == 2:
                    order = self.service.get_order(order_id)
                elif method == "POST" and parts[2:] == ["pickup"]:
                    order = self.service.mark_picked_up(order_id)
                elif method == "POST" and parts[2:] == ["deliver"]:
                    order = self.service.mark_delivered(order_id)
                else:
                    return 404, {"detail": "no such route"}
                return 200, {"order_id": order.order_id, "status": order.status.value}
        except NotFoundError as error:
            return 404, {"detail": str(error)}
        except ConflictError as error:
            return 409, {"detail": str(error)}
        return 404, {"detail": "no such route"}

    def close(self) -> None:
        pass


def _location(data: dict) -> Location:
    return Location(data["latitude"], data["longitude"])


def _location_json(location: Location) -> dict:
    return {"latitude": location.latitude, "longitude": location.longitude}


@dataclass
class LoadTestResult:
    orders_completed: int
    requests_sent: int
    errors: int
    elapsed_seconds: float
    latencies_ms: dict[str, list[float]]  # endpoint name -> latency of each successful call
    first_error: str | None = None

    @property
    def requests_per_second(self) -> float:
        return self.requests_sent / self.elapsed_seconds if self.elapsed_seconds > 0 else 0.0

    def all_latencies(self) -> list[float]:
        return [value for values in self.latencies_ms.values() for value in values]

    def p95_ms(self, endpoint: str | None = None) -> float:
        values = self.latencies_ms[endpoint] if endpoint else self.all_latencies()
        return percentile(values, 95)


def check_thresholds(
    result: LoadTestResult,
    min_requests_per_second: float | None = None,
    max_p95_ms: float | None = None,
) -> list[str]:
    """Reasons the run fails its targets. An empty list means it passed."""
    failures = []
    if result.errors:
        failures.append(f"{result.errors} requests failed (first: {result.first_error})")
    if min_requests_per_second is not None and result.requests_per_second < min_requests_per_second:
        failures.append(
            f"throughput {result.requests_per_second:.0f} req/s is below "
            f"{min_requests_per_second:g} req/s"
        )
    if max_p95_ms is not None and result.all_latencies() and result.p95_ms() > max_p95_ms:
        failures.append(f"p95 latency {result.p95_ms():.1f} ms is above {max_p95_ms:g} ms")
    return failures


def register_couriers(client, courier_count: int, run_id: str, seed: int) -> None:
    rng = random.Random(seed)
    for number in range(courier_count):
        body = {
            "courier_id": f"{run_id}-courier-{number}",
            "location": _location_json(random_point_in_city(rng, CITY_RADIUS_KM)),
        }
        status, data = client.send("POST", "/couriers", body)
        if status != 201:
            raise RuntimeError(f"couldn't add courier: {status} {data}")


def run_load_test(
    make_client: Callable[[], object],
    total_orders: int,
    concurrency: int,
    courier_count: int,
    seed: int = 1,
    warmup_orders: int = 0,
) -> LoadTestResult:
    """Push total_orders through the API from `concurrency` threads and time every request.

    make_client is called once per thread, because an HTTP connection can't be shared.
    """
    if total_orders < 1 or concurrency < 1:
        raise ValueError("need at least one order and one client")
    # Each client delivers its order before placing the next one, so it holds at most
    # one courier. With more clients than couriers some orders would sit waiting with
    # nobody to pick them up and the run would stall.
    if concurrency > courier_count:
        raise ValueError("concurrency can't be higher than courier_count")

    # A fresh prefix per run so re-running against the same server never hits a
    # duplicate id (the server keeps its state between runs).
    run_id = uuid.uuid4().hex[:8]
    setup_client = make_client()
    try:
        register_couriers(setup_client, courier_count, run_id, seed)
    finally:
        setup_client.close()

    # Split the orders as evenly as possible between the threads.
    orders_per_worker = [total_orders // concurrency] * concurrency
    for index in range(total_orders % concurrency):
        orders_per_worker[index] += 1

    worker_results = [None] * concurrency
    start_line = threading.Barrier(concurrency + 1)

    def worker(index: int) -> None:
        # Each thread keeps its own lists and the main thread merges them after join(),
        # so no lock is needed around the bookkeeping.
        rng = random.Random(seed * 1000 + index)
        latencies = {"create_order": [], "get_order": [], "pickup": [], "deliver": []}
        stats = {"orders": 0, "requests": 0, "errors": 0, "first_error": None}

        def timed(name, method, path, body=None, record=True):
            started = time.perf_counter()
            try:
                status, data = client.send(method, path, body)
            except Exception as error:  # noqa: BLE001
                # Count any failure (refused connection, bad JSON, ...) as an error
                # instead of letting it kill the client thread.
                status, data = None, {"detail": repr(error)}
            elapsed_ms = (time.perf_counter() - started) * 1000
            ok = status is not None and 200 <= status < 300
            if record:
                stats["requests"] += 1
                if ok:
                    latencies[name].append(elapsed_ms)
                else:
                    stats["errors"] += 1
                    if stats["first_error"] is None:
                        stats["first_error"] = f"{method} {path} -> {status} {data}"
            return ok, data

        def one_order(order_number, record):
            order_id = f"{run_id}-w{index}-{order_number}"
            body = {
                "order_id": order_id,
                "restaurant": _location_json(random_point_in_city(rng, CITY_RADIUS_KM)),
                "customer": _location_json(random_point_in_city(rng, CITY_RADIUS_KM)),
                "prep_minutes": 0,
            }
            ok, _ = timed("create_order", "POST", "/orders", body, record)
            if not ok:
                return
            timed("get_order", "GET", f"/orders/{order_id}", record=record)
            ok, _ = timed("pickup", "POST", f"/orders/{order_id}/pickup", record=record)
            if not ok:
                return
            ok, _ = timed("deliver", "POST", f"/orders/{order_id}/deliver", record=record)
            if ok and record:
                stats["orders"] += 1

        client = None
        try:
            client = make_client()
            # Warm-up orders aren't timed: the first requests pay for connection setup
            # and cold caches, which isn't what we want to measure.
            for number in range(warmup_orders):
                one_order(f"warmup{number}", record=False)
            start_line.wait()
            for number in range(orders_per_worker[index]):
                one_order(number, record=True)
        except threading.BrokenBarrierError:
            pass
        except Exception as error:  # noqa: BLE001
            # Something broke before the start line (e.g. can't connect). Break the
            # barrier so the other threads and the main thread don't wait forever,
            # and keep the error so the main thread can report it.
            stats["first_error"] = repr(error)
            start_line.abort()
        finally:
            if client is not None:
                client.close()
            worker_results[index] = (latencies, stats)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(concurrency)]
    for thread in threads:
        thread.start()
    # Start the clock only once every thread has finished warming up.
    try:
        start_line.wait()
    except threading.BrokenBarrierError:
        for thread in threads:
            thread.join()
        errors = [stats["first_error"] for _, stats in worker_results if stats["first_error"]]
        raise RuntimeError(f"a client failed before the test started: {errors[:1]}")
    started = time.perf_counter()
    for thread in threads:
        thread.join()
    elapsed = time.perf_counter() - started

    merged = {"create_order": [], "get_order": [], "pickup": [], "deliver": []}
    orders = requests = errors = 0
    first_error = None
    for latencies, stats in worker_results:
        for name, values in latencies.items():
            merged[name].extend(values)
        orders += stats["orders"]
        requests += stats["requests"]
        errors += stats["errors"]
        first_error = first_error or stats["first_error"]
    return LoadTestResult(orders, requests, errors, elapsed, merged, first_error)
