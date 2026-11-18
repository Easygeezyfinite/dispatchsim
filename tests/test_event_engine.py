import pytest

from dispatchsim.simulator.event_engine import Event, EventEngine


def record_into(log):
    def handler(event, engine):
        log.append((engine.current_time, event.payload))

    return handler


def test_events_run_in_time_order_not_insertion_order():
    engine, log = EventEngine(), []
    engine.on("ping", record_into(log))
    engine.schedule(Event(30, "ping", "third"))
    engine.schedule(Event(10, "ping", "first"))
    engine.schedule(Event(20, "ping", "second"))
    engine.run_until(100)
    assert [payload for _, payload in log] == ["first", "second", "third"]


def test_clock_jumps_to_each_event_then_to_end_time():
    engine, log = EventEngine(), []
    engine.on("ping", record_into(log))
    engine.schedule(Event(42, "ping", "a"))
    engine.run_until(100)
    assert log == [(42, "a")]
    assert engine.current_time == 100


def test_events_after_end_time_stay_queued():
    engine, log = EventEngine(), []
    engine.on("ping", record_into(log))
    engine.schedule(Event(50, "ping", "now"))
    engine.schedule(Event(500, "ping", "later"))
    engine.run_until(100)
    assert [payload for _, payload in log] == ["now"]
    engine.run_until(1000)
    assert [payload for _, payload in log] == ["now", "later"]


def test_handler_can_schedule_a_follow_up_event():
    engine, log = EventEngine(), []

    def order_created(event, eng):
        log.append(("created", eng.current_time))
        eng.schedule(Event(eng.current_time + 600, "delivered", event.payload))

    engine.on("order_created", order_created)
    engine.on("delivered", lambda event, eng: log.append(("delivered", eng.current_time)))
    engine.schedule(Event(100, "order_created", "order_1"))
    engine.run_until(10_000)
    assert log == [("created", 100), ("delivered", 700)]


def test_cannot_schedule_in_the_past():
    engine = EventEngine()
    engine.run_until(100)
    with pytest.raises(ValueError):
        engine.schedule(Event(50, "ping"))


def test_same_time_events_keep_insertion_order():
    engine, log = EventEngine(), []
    engine.on("ping", record_into(log))
    engine.schedule(Event(10, "ping", "scheduled first"))
    engine.schedule(Event(10, "ping", "scheduled second"))
    engine.run_until(100)
    assert [payload for _, payload in log] == ["scheduled first", "scheduled second"]

def test_same_time_follow_up_runs_after_queued_events_at_cutoff():
    engine, log = EventEngine(), []

    def schedule_follow_up(event, engine):
        log.append((engine.current_time, event.payload))
        engine.schedule(Event(engine.current_time, "ping", "follow-up"))

    engine.on("start", schedule_follow_up)
    engine.on("ping", record_into(log))
    engine.schedule(Event(10, "start", "first"))
    engine.schedule(Event(10, "ping", "already queued"))

    engine.run_until(10)

    assert log == [(10, "first"), (10, "already queued"), (10, "follow-up")]
