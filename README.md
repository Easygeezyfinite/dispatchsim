# DispatchSim

A food delivery dispatch simulator. Orders come in, couriers get assigned, and a
discrete-event simulator plays out what happens so different dispatch strategies
can be compared on the same order stream.

**Status:** the simulator, two dispatch strategies (nearest courier and batched
Hungarian matching), a seeded experiment runner, a FastAPI dispatch service, a load
benchmark, a CI regression gate and a Docker image are done. See [Results](#results)
for what has actually been measured. An ETA model is the main thing not built yet.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

Or run just the API in Docker:

```bash
docker compose up --build -d
curl localhost:8000/health
docker compose down
```

The image only contains the package and FastAPI/uvicorn (tests, experiments and data
are left out by `.dockerignore`). It runs a single uvicorn worker on purpose: the
dispatcher keeps couriers and orders in memory, so two workers would each have their
own half of the city.

## What's here so far

```
src/dispatchsim/simulator/
  event_engine.py   clock + time-ordered event queue
  location.py       lat/lon points, haversine distance, travel time estimate
  models.py         Order and Courier with checked status transitions
  simulation.py     plays orders and couriers out as events
  batched_simulation.py   same, but dispatches in batches every N seconds
src/dispatchsim/policies/
  nearest_courier.py      baseline: idle courier who reaches the restaurant fastest
  hungarian.py            min-cost matching (Hungarian algorithm) for a batch
src/dispatchsim/dispatch_service/
  service.py        live dispatcher: couriers and orders come in as requests
  app.py            FastAPI endpoints around the service
src/dispatchsim/evaluation/
  metrics.py        mean / p90 delivery time, mean wait for a courier
  scenario.py       seeded random city: restaurants, couriers, Poisson order stream
  experiment.py     runs each strategy on the same seeds and compares them
  load_test.py      concurrent clients running orders through the API, timing each request
  regression_gate.py   compares a fixed scenario's metrics to a committed baseline
tests/
  test_event_engine.py
  test_location.py
  test_models.py
  test_simulation.py
  test_batched_simulation.py
  test_nearest_courier.py
  test_hungarian.py
  test_metrics.py
  test_scenario.py
  test_experiment.py
  test_dispatch_service.py
  test_api.py
  test_load_test.py
  test_regression_gate.py
experiments/
  compare_strategies.py           command-line strategy comparison
  load_benchmark.py               requests/sec and latency of the API
  regression_gate.py              CI gate: fails if dispatching got worse
  baseline_metrics.json           numbers the gate compares against
  time_progression_benchmark.py   next-event vs fixed-tick simulation timing
Dockerfile, docker-compose.yml    container for the dispatch API
```

Locations are latitude/longitude so real order data can be replayed later. Travel
time is straight-line distance times a 1.3 road detour factor, divided by courier
speed. That's less accurate than routing on a real road network, but it's enough to
compare dispatch strategies fairly since they all use the same estimate.

## How a simulation runs

The simulator jumps from event to event instead of ticking every second. Each order
produces four events:

| Event | What happens |
|---|---|
| `order_created` | order joins the waiting list, dispatch runs |
| `courier_arrived_at_restaurant` | courier waits if the food isn't ready yet |
| `order_picked_up` | courier heads to the customer |
| `order_delivered` | courier is idle at the customer's spot, dispatch runs again |

Dispatch runs whenever something could change the answer: a new order arrives or a
courier frees up. The oldest waiting order goes first. The choice of courier comes
from a dispatch policy, a plain function `(order, idle_couriers) -> courier or None`,
so every strategy runs on the same simulator.

```python
from dispatchsim.simulator.location import Location
from dispatchsim.simulator.models import Courier, Order
from dispatchsim.simulator.simulation import Simulation


def first_idle_courier(order, idle_couriers):
    return idle_couriers[0]


couriers = [Courier("c1", Location(51.0447, -114.0631))]
sim = Simulation(couriers, first_idle_courier)
sim.add_order(Order("o1", Location(51.0480, -114.0700), Location(51.0380, -114.0800),
                    created_at=0, food_ready_at=600))
sim.run_until(3600)
print(sim.delivered_orders()[0].delivery_time_seconds)
```

## Dispatch strategies

**Nearest courier (baseline).** When an order arrives, or a courier frees up, the
oldest waiting order gets the idle courier with the shortest travel time to its
restaurant. Simple and instant, but it looks at one order at a time, so it can give
away the only nearby courier that a second order needed.

**Batched Hungarian matching.** `BatchedSimulation` lets orders collect for
`batch_interval_seconds` (30 by default), then matches all waiting orders to all idle
couriers at once so the total travel time to restaurants is as small as possible.
The matching is the Hungarian algorithm, written out in `policies/hungarian.py`
(O(n^2 m)) instead of pulling in scipy, and tested against brute force on random
matrices. If there are more orders than couriers, only the oldest ones are matched
that round, so an order with an awkward location can't be passed over forever.

The trade-off is that every order waits up to one batch interval before anyone is
assigned. Whether the better matching makes up for that is what the experiment runner
is for.

```python
from dispatchsim.evaluation.metrics import summarize_orders
from dispatchsim.policies.hungarian import hungarian_batch_policy
from dispatchsim.policies.nearest_courier import nearest_idle_courier
from dispatchsim.simulator.batched_simulation import BatchedSimulation
from dispatchsim.simulator.simulation import Simulation

baseline = Simulation(couriers, nearest_idle_courier)
batched = BatchedSimulation(other_couriers, hungarian_batch_policy, batch_interval_seconds=30)
```

`summarize_orders(list(sim.orders.values()))` gives delivered count, mean and p90 delivery
time, and mean wait for a courier. Orders still in progress are counted but left out
of the averages, so check `undelivered_orders` before comparing two runs.

## Comparing strategies

`experiments/compare_strategies.py` builds a random city from a seed and runs every
strategy on it:

- 40 restaurants and the couriers start at random spots within 5 km of downtown Calgary
- orders arrive as a Poisson process (`--orders-per-hour`), each from a random
  restaurant to a random customer, with 5 to 15 minutes of cooking time
- couriers ride at 20 km/h

All randomness comes from one `random.Random(seed)`, so the same arguments always
give the same numbers. Each strategy gets its own fresh copy of the same orders and
couriers, which makes it a paired comparison: per seed, the only difference is the
strategy. After the last order the simulation keeps running until the backlog
clears, and the comparison refuses to use a run that left orders undelivered.

```bash
python experiments/compare_strategies.py --seeds 1 2 3 4 5 6 7 8 9 10
python experiments/compare_strategies.py --orders-per-hour 40 --batch-interval 10
python experiments/compare_strategies.py --csv data/results.csv
```

### Results so far

40 couriers, 2,000 orders per seed, seeds 1-10, batched Hungarian vs nearest courier,
change in mean delivery time (positive = batched is faster):

| Orders/hour | Batch every 10 s | Batch every 30 s | Batch every 60 s |
|---|---|---|---|
| 40 (quiet) | -0.13% (better on 0/10 seeds) | -0.31% (0/10) | -0.60% (0/10) |
| 60 (busy) | +0.37% (7/10) | +1.53% (9/10) | +2.50% (10/10) |

A bigger run, 5 seeds x 5,000 orders x 2 strategies (50,000 simulated orders, about
2.5 s in total), gave +1.46% at 60 orders/hour with a 30 s batch, better on 5/5 seeds.

What this says:

- When couriers are mostly idle, there's nothing to optimise. Every order still waits
  for the next batch, so batching is slightly slower, and longer batches are worse.
- When couriers are busy, several orders compete for the same few idle couriers, and
  matching them together starts to pay off. The gain is small (1-3%) and varies a lot
  between seeds.
- At 65+ orders/hour these 40 couriers can't keep up and the queue grows for the
  whole run. Batching wins by 15-40% there, but the number depends on how long you
  run, so it describes an overloaded system rather than a steady improvement and
  isn't reported as a result.

## Dispatch API

The simulator decides when things happen. The API is the live version: restaurants
post orders, courier apps report pickups and drop-offs, and the service assigns
couriers as those requests arrive, with the same rule as the baseline strategy (the
oldest waiting order gets the nearest idle courier).

```bash
uvicorn dispatchsim.dispatch_service.app:app --reload
```

Docs and a request playground are at http://127.0.0.1:8000/docs.

| Method | Path | What it does |
|---|---|---|
| GET | `/health` | liveness check |
| POST | `/couriers` | add a courier at a location (idle couriers get waiting orders right away) |
| GET | `/couriers/{id}` | courier status, location and current order |
| PUT | `/couriers/{id}/location` | move a courier |
| POST | `/orders` | place an order; assigned straight away if a courier is idle, otherwise it waits |
| GET | `/orders/{id}` | order status and timestamps |
| POST | `/orders/{id}/pickup` | courier has the food (409 if it isn't ready yet) |
| POST | `/orders/{id}/deliver` | food delivered; the courier is free and takes the oldest waiting order |
| GET | `/stats` | delivered count, mean / p90 delivery time, waiting orders, idle couriers |
| POST | `/simulate` | run one seeded scenario (up to 5,000 orders) and return its metrics |

Try it from a second terminal:

```bash
curl -X POST localhost:8000/couriers -H "Content-Type: application/json" -d '{"courier_id": "c1", "location": {"latitude": 51.046, "longitude": -114.064}}'
curl -X POST localhost:8000/orders -H "Content-Type: application/json" -d '{"order_id": "o1", "restaurant": {"latitude": 51.0447, "longitude": -114.0631}, "customer": {"latitude": 51.038, "longitude": -114.08}, "prep_minutes": 0}'
curl -X POST localhost:8000/orders/o1/pickup
curl -X POST localhost:8000/orders/o1/deliver
curl localhost:8000/stats
```

Errors: 404 for an unknown id, 409 when the request doesn't fit the order's state
(duplicate id, delivering before pickup, picking up before the food is ready), and
422 for bad input such as a latitude of 95.

Some decisions worth knowing about:

- `DispatchService` has no HTTP code in it, so the dispatching rules are tested
  directly and `app.py` only maps JSON and errors.
- FastAPI runs plain `def` endpoints on a thread pool, so requests can overlap. Every
  service method holds one lock; without it two orders arriving together can grab the
  same idle courier. `test_concurrent_orders_never_share_a_courier` checks this and
  fails when the lock is removed.
- The live service dispatches one order at a time. Batched matching needs a timer
  running in the background, and the experiments so far show only a small gain at
  busy load, so it stays in the simulator for now.
- State is in memory. Restarting the server starts from an empty city, and running
  more than one server process would give each its own couriers.

## Load benchmark

`experiments/load_benchmark.py` starts a number of client threads, each running
orders through the API one after another:

```
POST /orders  ->  GET /orders/{id}  ->  POST /orders/{id}/pickup  ->  POST /orders/{id}/deliver
```

Every request is timed, and the script prints requests per second plus mean, p50,
p95, p99 and max latency per endpoint. Each client holds at most one courier at a
time, so the number of clients can't exceed the number of couriers. It only uses
the standard library (`http.client` with keep-alive connections), so it doesn't add
dependencies.

Start the server without `--reload`:

```bash
uvicorn dispatchsim.dispatch_service.app:app
```

Then from a second terminal:

```bash
python experiments/load_benchmark.py --url http://127.0.0.1:8000
python experiments/load_benchmark.py --url http://127.0.0.1:8000 --concurrency 16 --orders 5000
python experiments/load_benchmark.py --url http://127.0.0.1:8000 --min-rps 300 --max-p95-ms 60
```

With `--min-rps` or `--max-p95-ms` the script exits with status 1 if a target is
missed or any request failed. Without `--url` it calls `DispatchService` directly
(no HTTP or JSON), which shows the cost of the dispatching logic and the lock alone.

### Benchmark results

HTTP numbers against uvicorn: not measured yet.

Service layer only (no HTTP), 8 client threads, 5,000 orders = 20,000 calls, on a
Linux VM with Python 3.10. Three runs on Oct 28 gave 51,000-53,500 calls/s with an
overall p95 of 0.06-0.07 ms; `create_order` is the slowest call (p95 about 1.6 ms)
because it holds the lock while it picks a courier. A run on Oct 26 on the same VM
gave about 26,000 calls/s, so treat these as rough. Either way this is an upper bound
for the HTTP numbers, not an HTTP result: it leaves out JSON, pydantic validation and
the network, which will dominate.

## Regression gate

The simulator is deterministic, so CI can check that a change didn't make dispatching
worse. `experiments/regression_gate.py` runs a fixed scenario (5 seeds x 2,000 orders,
40 couriers, 60 orders/hour, 30 s batches; about a second) and compares it with
`experiments/baseline_metrics.json`. It fails if:

- mean or p90 delivery time of either strategy is more than 1% worse,
- batched matching's advantage over nearest courier drops by more than 1 point,
- any order is left undelivered, or
- the scenario itself changed since the baseline was recorded.

```bash
python experiments/regression_gate.py
python experiments/regression_gate.py --write-baseline
```

The tolerance only has to cover floating-point differences between machines, not
random noise. If a change makes things better the gate still passes and suggests
re-recording the baseline with `--write-baseline`; commit the updated JSON so the
change in numbers shows up in review.

I checked that it catches real mistakes: picking the farthest courier instead of the
nearest (+33% mean delivery time), pairing batched orders in order instead of with
the Hungarian algorithm (+32%), and a 1.5% change to the road detour factor (+3%)
each fail the gate.

Timing is not part of the CI gate on purpose: shared CI machines vary too much
between runs, so a latency check there would fail randomly. The latency targets are
checked with `load_benchmark.py --min-rps --max-p95-ms` on a fixed machine instead.

## Results

Everything below was produced by the scripts in `experiments/` and can be rerun with
the same seeds.

| What | Measured | How |
|---|---|---|
| Simulated orders | 50,000 (5 seeds x 5,000 orders x 2 strategies) in under 3 s, 1.5% faster with batching on 5/5 seeds | `compare_strategies.py --seeds 1 2 3 4 5 --orders 5000` |
| Batched Hungarian vs nearest courier, busy load (60 orders/h, 40 couriers, 30 s batch) | 1.5% lower mean delivery time, better on 9/10 seeds (range -0.3% to +6.0%) | `compare_strategies.py --seeds 1 2 3 4 5 6 7 8 9 10` |
| Same, quiet load (40 orders/h) | 0.3% slower, worse on 10/10 seeds | `--orders-per-hour 40` |
| Service layer throughput (no HTTP) | about 26,000-53,000 calls/s, p95 under 0.1 ms overall | `load_benchmark.py` without `--url` |
| HTTP throughput and latency against uvicorn | not measured yet | `load_benchmark.py --url ...` |
| CI regression gate | catches a wrong courier choice (+33%), a broken matcher (+32%) and a 1.5% travel-time change (+3%) | `regression_gate.py` |

The honest summary: batching only helps when couriers are scarce, and even then the
gain is a couple of percent with a lot of seed-to-seed variation. When couriers are
mostly idle the batch delay costs more than the better matching saves. That matches
how the two strategies work, and it's the reason the live API dispatches one order at
a time.

### Limitations and next steps

- **ETA model.** `eta_model/` is still empty. Travel time is a straight-line estimate
  times a 1.3 detour factor at a fixed 20 km/h, and prep times are uniform 5-15
  minutes. A learned ETA (time of day, distance, restaurant) would make both the
  dispatch choices and the simulated outcomes more realistic.
- **Synthetic data.** Orders come from a random Poisson stream in a 5 km disk, not
  real order history, so the absolute delivery times mean little; only the
  comparison between strategies on the same stream does.
- **Single process.** The API keeps state in memory behind one lock. Scaling out would
  need shared state (for example Redis) and a way to stop two instances assigning the
  same courier.
- **Batching in the live service.** Not done; it would need a background timer, and
  the measured gain is small.

## Roadmap

- [x] Event engine (clock + priority queue)
- [x] Order, courier and location models
- [x] Simulator wired to the event engine (orders arrive, couriers move)
- [x] Baseline strategy: assign the nearest idle courier
- [x] Metrics: mean delivery time, time waiting for a courier
- [x] Second strategy: batched assignment (Hungarian matching)
- [x] Reproducible experiment runner with fixed seeds
- [x] FastAPI endpoints for the dispatch service
- [x] Load benchmark and CI regression gate
- [x] Docker and write-up with measured results
- [ ] ETA model (learned travel and prep times)
- [ ] HTTP load numbers against uvicorn in Docker
