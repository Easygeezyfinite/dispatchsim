"""Side quest: fixed-increment vs next-event time progression.

Question: how much faster is a next-event engine (clock JUMPS to the next event)
than a fixed-increment engine (clock TICKS every second) for a sparse event load?

Run (after finishing the TODOs in event_engine.py):
    python experiments/time_progression_benchmark.py
"""

import random
import time

from dispatchsim.simulator.event_engine import Event, EventEngine

SECONDS_IN_A_DAY = 24 * 60 * 60
NUMBER_OF_EVENTS = 1_000
RANDOM_SEED = 42


def make_random_events(number_of_events: int, seed: int) -> list[Event]:
    """The same 1,000 events for both engines, spread across one simulated day."""
    rng = random.Random(seed)
    return [
        Event(happens_at=rng.randint(0, SECONDS_IN_A_DAY - 1), event_type="ping", payload=index)
        for index in range(number_of_events)
    ]


def run_next_event_engine(events: list[Event]) -> list[int]:
    """Uses YOUR EventEngine. Returns the payloads in the order they were handled."""
    handled_order = []
    engine = EventEngine()
    engine.on("ping", lambda event, eng: handled_order.append(event.payload))
    for event in events:
        engine.schedule(event)
    engine.run_until(SECONDS_IN_A_DAY)
    return handled_order


def run_fixed_increment_engine(events: list[Event]) -> list[int]:
    """TODO: the ticking engine.

    Idea:
        clock = 0
        while clock < SECONDS_IN_A_DAY:
            handle every event whose happens_at == clock (in the order they were scheduled)
            clock += 1

    Think first: if you scan the whole event list on every tick, that's
    86,400 ticks x 1,000 events. Is that a fair comparison, or are you
    making the fixed-increment engine look worse than it really is?
    A fairer version groups events by second up front (hint: a dict of lists).

    Return the payloads in the order they were handled.
    """
    raise NotImplementedError


def time_it(function, events: list[Event]) -> tuple[list[int], float]:
    started = time.perf_counter()
    result = function(events)
    elapsed_seconds = time.perf_counter() - started
    return result, elapsed_seconds


if __name__ == "__main__":
    events = make_random_events(NUMBER_OF_EVENTS, RANDOM_SEED)

    next_event_order, next_event_seconds = time_it(run_next_event_engine, events)
    fixed_increment_order, fixed_increment_seconds = time_it(run_fixed_increment_engine, events)

    # Correctness before speed: a fast engine that handles events in the wrong order is useless.
    assert next_event_order == fixed_increment_order, "The two engines disagree on event order!"

    print(f"next-event:      {next_event_seconds * 1000:8.2f} ms")
    print(f"fixed-increment: {fixed_increment_seconds * 1000:8.2f} ms")
    print(f"speedup:         {fixed_increment_seconds / next_event_seconds:8.1f}x")

    # TODO (after it runs): try NUMBER_OF_EVENTS = 100_000. Does the speedup shrink or grow?
    # Write down why in NOTES.md. That answer is the real interview insight.
