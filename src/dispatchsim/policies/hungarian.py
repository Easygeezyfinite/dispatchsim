"""Batched strategy: collect waiting orders for a short window, then match them to
idle couriers all at once so the TOTAL travel time to restaurants is as small as possible.

Why bother: the nearest-courier baseline handles orders one by one. If two orders
come in together, the first one can grab the courier who was the only good option
for the second. Looking at the whole batch avoids that.

The matching uses the Hungarian algorithm, which finds the minimum-cost assignment
in O(n^2 * m) time. Trying every possible assignment would be factorial, so even
10 orders x 10 couriers (3.6 million options) would be too slow to do every 30 s.
scipy has this built in (linear_sum_assignment), but it's a heavy dependency for one
function, and writing it out makes the behaviour easy to test and explain.
"""

import math

from dispatchsim.simulator.location import travel_time_seconds
from dispatchsim.simulator.models import Courier, Order


def min_cost_assignment(cost: list[list[float]]) -> list[tuple[int, int]]:
    """Pair rows with columns so the summed cost is minimal.

    cost[r][c] is the cost of giving row r column c. Returns (row, column) pairs.
    With more columns than rows every row gets a column (and vice versa), so the
    result has min(rows, columns) pairs.

    This is the shortest-augmenting-path version of the Hungarian algorithm. It adds
    rows one at a time. Each row/column keeps a "potential" (row_potential,
    column_potential); a cell is "free to use" when its cost minus both potentials is
    zero. Adding a row means finding the cheapest chain of swaps that frees up a
    column for it, then shifting potentials so the cells used stay at zero.
    """
    if not cost:
        return []
    row_count, column_count = len(cost), len(cost[0])
    if any(len(row) != column_count for row in cost):
        raise ValueError("every row of the cost matrix must be the same length")
    if column_count == 0:
        return []

    # The algorithm below needs rows <= columns. If not, solve the flipped problem.
    if row_count > column_count:
        flipped = [[cost[r][c] for r in range(row_count)] for c in range(column_count)]
        return sorted((r, c) for c, r in min_cost_assignment(flipped))

    # 1-indexed arrays; index 0 is a dummy column used as the start of each search.
    row_potential = [0.0] * (row_count + 1)
    column_potential = [0.0] * (column_count + 1)
    row_in_column = [0] * (column_count + 1)  # 0 means the column is still free
    previous_column = [0] * (column_count + 1)  # how we reached each column, to undo the path

    for new_row in range(1, row_count + 1):
        row_in_column[0] = new_row
        current_column = 0
        # Cheapest reduced cost found so far to reach each column in this search.
        cheapest_to_column = [math.inf] * (column_count + 1)
        visited = [False] * (column_count + 1)

        # Grow a tree of rows/columns until we reach a free column.
        while True:
            visited[current_column] = True
            row = row_in_column[current_column]
            smallest_step = math.inf
            next_column = 0
            for column in range(1, column_count + 1):
                if visited[column]:
                    continue
                reduced_cost = (
                    cost[row - 1][column - 1] - row_potential[row] - column_potential[column]
                )
                if reduced_cost < cheapest_to_column[column]:
                    cheapest_to_column[column] = reduced_cost
                    previous_column[column] = current_column
                if cheapest_to_column[column] < smallest_step:
                    smallest_step = cheapest_to_column[column]
                    next_column = column

            # Shift potentials so the cheapest new cell becomes "free to use" while
            # every cell already in the tree stays that way.
            for column in range(column_count + 1):
                if visited[column]:
                    row_potential[row_in_column[column]] += smallest_step
                    column_potential[column] -= smallest_step
                else:
                    cheapest_to_column[column] -= smallest_step

            current_column = next_column
            if row_in_column[current_column] == 0:
                break  # found a free column

        # Walk back along the path, shifting each row one column over. This is what
        # lets an earlier row give up its column if that makes the total cheaper.
        while current_column != 0:
            earlier_column = previous_column[current_column]
            row_in_column[current_column] = row_in_column[earlier_column]
            current_column = earlier_column

    return sorted(
        (row_in_column[column] - 1, column - 1)
        for column in range(1, column_count + 1)
        if row_in_column[column] != 0
    )


def hungarian_batch_policy(
    waiting_orders: list[Order], idle_couriers: list[Courier]
) -> list[tuple[Order, Courier]]:
    """Match a batch of waiting orders (oldest first) to idle couriers.

    Cost = courier's travel time to the restaurant. If there are more orders than
    couriers, only the oldest ones get matched this round. Otherwise a minimum-total
    matching could keep passing over an old order whose restaurant is far from
    everyone, and that order would wait forever.
    """
    if not waiting_orders or not idle_couriers:
        return []
    orders_this_round = waiting_orders[: len(idle_couriers)]
    cost = [
        [
            travel_time_seconds(courier.location, order.restaurant, courier.speed_kmh)
            for courier in idle_couriers
        ]
        for order in orders_this_round
    ]
    return [
        (orders_this_round[order_index], idle_couriers[courier_index])
        for order_index, courier_index in min_cost_assignment(cost)
    ]
