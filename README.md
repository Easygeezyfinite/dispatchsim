# DispatchSim

A food delivery dispatch simulator. Orders come in, couriers get assigned, and a
discrete-event simulator plays out what happens so different dispatch strategies
can be compared on the same order stream.

**Status: early work in progress.** The event engine is being written and the
order, courier and location models exist. No dispatch strategy, API or
benchmark results yet.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

## What's here so far

```
src/dispatchsim/simulator/
  event_engine.py   clock + time-ordered event queue (in progress)
  location.py       lat/lon points, haversine distance, travel time estimate
  models.py         Order and Courier with checked status transitions
tests/
  test_event_engine.py
  test_location.py
  test_models.py
experiments/
  time_progression_benchmark.py   next-event vs fixed-tick simulation timing
```

Locations are latitude/longitude so real order data can be replayed later. Travel
time is straight-line distance times a 1.3 road detour factor, divided by courier
speed. That's less accurate than routing on a real road network, but it's enough to
compare dispatch strategies fairly since they all use the same estimate.

## Roadmap

- [ ] Event engine (clock + priority queue)
- [x] Order, courier and location models
- [ ] Simulator wired to the event engine (orders arrive, couriers move)
- [ ] Baseline strategy: assign the nearest idle courier
- [ ] Metrics: mean delivery time, time waiting for a courier
- [ ] Second strategy: batched assignment (Hungarian matching)
- [ ] Reproducible experiment runner with fixed seeds
- [ ] FastAPI endpoints for the dispatch service
- [ ] Load benchmark and CI regression gate
- [ ] Docker and write-up with measured results
