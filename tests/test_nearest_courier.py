from dispatchsim.policies.nearest_courier import nearest_idle_courier
from dispatchsim.simulator.location import Location
from dispatchsim.simulator.models import Courier, Order, OrderStatus
from dispatchsim.simulator.simulation import Simulation

RESTAURANT = Location(51.0480, -114.0700)
CUSTOMER = Location(51.0380, -114.0800)
NEAR_RESTAURANT = Location(51.0485, -114.0705)  # about 70 m away
A_FEW_KM_AWAY = Location(51.0700, -114.1000)


def make_order(order_id="order_1", created_at=0.0):
    return Order(order_id, RESTAURANT, CUSTOMER, created_at, created_at)


def test_picks_the_closest_courier():
    far = Courier("far", A_FEW_KM_AWAY)
    near = Courier("near", NEAR_RESTAURANT)
    assert nearest_idle_courier(make_order(), [far, near]) is near


def test_faster_courier_further_away_can_win():
    # Same spot would tie, so put the slow one a little closer and make it very slow.
    slow_but_close = Courier("slow", NEAR_RESTAURANT, speed_kmh=0.1)
    fast_but_further = Courier("fast", A_FEW_KM_AWAY, speed_kmh=40)
    chosen = nearest_idle_courier(make_order(), [slow_but_close, fast_but_further])
    assert chosen is fast_but_further


def test_tie_goes_to_the_first_courier_in_the_list():
    first = Courier("first", NEAR_RESTAURANT)
    second = Courier("second", NEAR_RESTAURANT)
    assert nearest_idle_courier(make_order(), [first, second]) is first


def test_no_idle_couriers_returns_none():
    assert nearest_idle_courier(make_order(), []) is None


def test_works_as_a_simulation_policy():
    far = Courier("far", A_FEW_KM_AWAY)
    near = Courier("near", NEAR_RESTAURANT)
    sim = Simulation([far, near], nearest_idle_courier)
    order = make_order()
    sim.add_order(order)
    sim.run_until(10_000)

    assert order.status == OrderStatus.DELIVERED
    assert order.courier_id == "near"
