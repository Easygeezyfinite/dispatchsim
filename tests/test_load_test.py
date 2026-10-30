import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from dispatchsim.dispatch_service.service import DispatchService
from dispatchsim.evaluation.load_test import (
    HttpClient,
    InProcessClient,
    LoadTestResult,
    check_thresholds,
    run_load_test,
)
from dispatchsim.simulator.models import OrderStatus


def run_in_process(service=None, **kwargs):
    service = service or DispatchService()
    settings = {"total_orders": 40, "concurrency": 4, "courier_count": 6}
    settings.update(kwargs)
    return service, run_load_test(lambda: InProcessClient(service), **settings)


def make_result(latencies, errors=0, elapsed=1.0):
    return LoadTestResult(
        orders_completed=len(latencies) // 4,
        requests_sent=len(latencies) + errors,
        errors=errors,
        elapsed_seconds=elapsed,
        latencies_ms={"create_order": latencies},
        first_error="POST /orders -> 500" if errors else None,
    )


def test_every_order_is_delivered_and_couriers_end_idle():
    service, result = run_in_process(total_orders=101, concurrency=4)
    assert result.errors == 0
    assert result.orders_completed == 101
    assert result.requests_sent == 101 * 4
    delivered = [o for o in service.orders.values() if o.status == OrderStatus.DELIVERED]
    assert len(delivered) == 101
    assert all(courier.is_available for courier in service.couriers.values())
    assert not service.waiting_orders


def test_warmup_orders_run_but_are_not_counted():
    service, result = run_in_process(total_orders=20, concurrency=2, warmup_orders=3)
    assert result.orders_completed == 20
    assert result.requests_sent == 80
    # 20 timed + 2 clients x 3 warm-up orders actually went through the service.
    assert len(service.orders) == 26


def test_latencies_recorded_for_every_successful_request():
    _, result = run_in_process(total_orders=12, concurrency=3)
    assert {name: len(values) for name, values in result.latencies_ms.items()} == {
        "create_order": 12,
        "get_order": 12,
        "pickup": 12,
        "deliver": 12,
    }
    assert all(value >= 0 for value in result.all_latencies())
    assert result.requests_per_second > 0


def test_two_runs_on_the_same_service_use_different_ids():
    # The server keeps its state, so a second run must not collide with the first.
    service, first = run_in_process(total_orders=8, concurrency=2)
    _, second = run_in_process(service=service, total_orders=8, concurrency=2)
    assert first.errors == 0 and second.errors == 0
    assert len(service.orders) == 16


def test_more_clients_than_couriers_is_rejected():
    with pytest.raises(ValueError):
        run_in_process(concurrency=5, courier_count=4)


def test_errors_are_counted_not_raised():
    class BrokenPickupClient(InProcessClient):
        def send(self, method, path, body=None):
            if path.endswith("/pickup"):
                return 500, {"detail": "boom"}
            return super().send(method, path, body)

    service = DispatchService()
    result = run_load_test(
        lambda: BrokenPickupClient(service), total_orders=6, concurrency=2, courier_count=6
    )
    # create + get succeed, pickup fails, deliver is never attempted.
    assert result.errors == 6
    assert result.requests_sent == 18
    assert result.orders_completed == 0
    assert "pickup" in result.first_error


def test_thresholds():
    result = make_result([float(ms) for ms in range(1, 101)], elapsed=0.5)  # 200 req/s
    assert result.p95_ms() == 95.0
    assert check_thresholds(result) == []
    assert check_thresholds(result, min_requests_per_second=150, max_p95_ms=95) == []
    failures = check_thresholds(result, min_requests_per_second=300, max_p95_ms=60)
    assert len(failures) == 2
    assert "200 req/s" in failures[0]
    assert "95.0 ms" in failures[1]


def test_any_error_fails_thresholds():
    failures = check_thresholds(make_result([1.0, 2.0], errors=1))
    assert len(failures) == 1
    assert "1 requests failed" in failures[0]


def test_http_client_rejects_bad_url():
    with pytest.raises(ValueError):
        HttpClient("127.0.0.1:8000")


def test_unreachable_server_raises_instead_of_hanging():
    # Port 9 (discard) is almost never listening, so connecting is refused quickly.
    with pytest.raises((RuntimeError, OSError)):
        run_load_test(
            lambda: HttpClient("http://127.0.0.1:9", timeout_seconds=2),
            total_orders=4,
            concurrency=2,
            courier_count=2,
        )


def test_client_failing_in_a_worker_thread_does_not_hang():
    # Setup works, then every worker fails to create its client. Without breaking the
    # start barrier, the main thread would wait forever here.
    service = DispatchService()
    calls = []

    def make_client():
        calls.append(1)
        if len(calls) > 1:
            raise ConnectionRefusedError("server went away")
        return InProcessClient(service)

    with pytest.raises(RuntimeError, match="server went away"):
        run_load_test(make_client, total_orders=4, concurrency=2, courier_count=2)


def start_stdlib_server(service):
    """A tiny HTTP front end for the service, so HttpClient can be tested over a real
    socket without FastAPI. It reuses InProcessClient's routing."""
    router = InProcessClient(service)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"  # keep-alive, like uvicorn

        def setup(self):
            super().setup()
            # Headers and body go out in two writes. Without TCP_NODELAY, Nagle's
            # algorithm holds the body back until the client ACKs, which adds ~40 ms
            # to every request. uvicorn sets this flag too.
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        def handle_any(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length)) if length else None
            status, data = router.send(self.command, self.path, body)
            payload = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        do_GET = do_POST = handle_any

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_load_test_over_real_http():
    service = DispatchService()
    server = start_stdlib_server(service)
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        result = run_load_test(
            lambda: HttpClient(url), total_orders=30, concurrency=3, courier_count=5
        )
    finally:
        server.shutdown()
        server.server_close()
    assert result.errors == 0, result.first_error
    assert result.orders_completed == 30
    assert sum(o.status == OrderStatus.DELIVERED for o in service.orders.values()) == 30


def test_http_client_returns_error_status_and_body():
    server = start_stdlib_server(DispatchService())
    try:
        client = HttpClient(f"http://127.0.0.1:{server.server_address[1]}")
        status, data = client.send("GET", "/orders/missing")
        client.close()
    finally:
        server.shutdown()
        server.server_close()
    assert status == 404
    assert "missing" in data["detail"]
