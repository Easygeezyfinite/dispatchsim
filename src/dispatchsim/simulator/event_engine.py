"""The simulator's heartbeat: a clock plus a time-ordered queue of things that will happen.

The engine never decides anything. It only answers "what happens next, and when?"
Handlers (registered with `on`) react to events and may schedule new ones.
"""

import heapq
import itertools
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class Event:
    happens_at: float  # seconds since the simulation started
    event_type: str  # e.g. "order_created", "courier_arrived_at_restaurant"
    payload: Any = None


EventHandler = Callable[[Event, "EventEngine"], None]


class EventEngine:
    def __init__(self) -> None:
        self.current_time = 0.0
        self.events_processed = 0
        self._event_queue: list = []  # a min-heap, earliest event on top
        self._handlers: dict[str, EventHandler] = {}
        # Tie-breaker for events at the same time: every scheduled event gets the next
        # number, so earlier-scheduled events win ties and heapq never has to compare
        # two Event objects (dataclasses aren't orderable, so that would raise TypeError).
        self._schedule_counter = itertools.count()

    def on(self, event_type: str, handler: EventHandler) -> None:
        """Register the function that runs whenever an event of this type happens."""
        self._handlers[event_type] = handler

    def schedule(self, event: Event) -> None:
        if event.happens_at < self.current_time:
            raise ValueError(
                f"can't schedule {event.event_type!r} at t={event.happens_at}: "
                f"the clock is already at t={self.current_time}"
            )
        heapq.heappush(self._event_queue, (event.happens_at, next(self._schedule_counter), event))

    def run_until(self, end_time: float) -> None:
        while self._event_queue:
            next_time, _, next_event = self._event_queue[0]
            # Peek before popping: an event after end_time has to stay queued
            # for the next run_until call.
            if next_time > end_time:
                break
            heapq.heappop(self._event_queue)
            self.current_time = next_time

            handler = self._handlers.get(next_event.event_type)
            if handler is not None:
                handler(next_event, self)
            self.events_processed += 1

        self.current_time = end_time
