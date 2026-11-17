# DispatchSim development notes

## Event engine

- Events scheduled for the same simulation time run in scheduling order.
  A sequence counter breaks ties in the heap so it never compares event objects.
- `run_until(end_time)` processes events at the cutoff and leaves later events
  queued for the next call.

## Time-progression benchmark

`experiments/time_progression_benchmark.py` still has an unimplemented
fixed-increment runner. A speed comparison is pending both implementations
producing the same event order.
