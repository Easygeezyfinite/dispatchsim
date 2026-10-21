"""The simulator's heartbeat: a clock plus a time-ordered queue of things that will happen.

The engine never decides anything. It only answers "what happens next, and when?"
Handlers (registered with `on`) react to events and may schedule new ones.
"""

import heapq
from dataclasses import dataclass
from typing import Any, Callable


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

    def on(self, event_type: str, handler: EventHandler) -> None:
        """Register the function that runs whenever an event of this type happens."""
        self._handlers[event_type] = handler

    def schedule(self, event: Event) -> None:
        # TODO 1: An event can't happen in the past. If event.happens_at < self.current_time,
        #         raise a ValueError with a helpful message.

        # TODO 2: This line works... until it doesn't. Before changing it, predict what
        #         happens when two events share the same happens_at. Then make
        #         test_same_time_events_keep_insertion_order pass.
        heapq.heappush(self._event_queue, (event.happens_at, event))

    def run_until(self, end_time: float) -> None:
        # TODO 3: The main loop. While the queue isn't empty:
        #   - look at the earliest event; if it's after end_time, stop (leave it queued)
        #   - pop it and jump self.current_time to its happens_at
        #   - call its handler (skip silently if no handler is registered)
        #   - increment self.events_processed
        # Finally, set self.current_time = end_time.
        raise NotImplementedError
