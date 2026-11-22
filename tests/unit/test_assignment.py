"""`helpers.assignment.linear_sum_assignment` is a port of scipy's solver.

Same algorithm, same loop order, same tie-breaks — so it has to return the
*identical* pairing scipy does, not merely one of equal cost. Matching boards
are integer scores with many ties, which is exactly where two correct solvers
would disagree, so the comparison leans hard on ties.

scipy is a dev-only dependency kept for this reference check; production
never installs it.
"""

from __future__ import annotations

import math
import random

import pytest

from helpers.assignment import linear_sum_assignment

pytestmark = pytest.mark.unit


def _scipy(cost: list[list[float]]) -> tuple[list[int], list[int]]:
    np = pytest.importorskip("numpy")
    scipy_optimize = pytest.importorskip("scipy.optimize")
    rows, cols = scipy_optimize.linear_sum_assignment(np.array(cost, dtype=float).reshape(len(cost), -1))
    return rows.tolist(), cols.tolist()


def _random_board(rng: random.Random, n: int, m: int, spread: int) -> list[list[float]]:
    return [[float(rng.randint(-spread, spread)) for _ in range(m)] for _ in range(n)]


@pytest.mark.parametrize("shape", [(1, 1), (1, 7), (7, 1), (5, 5), (4, 9), (9, 4), (30, 30), (12, 40), (40, 12)])
@pytest.mark.parametrize("spread", [0, 1, 3, 50, 10_000])
def test_identical_to_scipy_on_random_integer_boards(shape, spread):
    rng = random.Random(f"{shape}-{spread}")
    for _ in range(25):
        n, m = shape
        cost = _random_board(rng, n, m, spread)
        assert linear_sum_assignment(cost) == _scipy(cost)


def test_identical_to_scipy_on_float_boards():
    rng = random.Random(7)
    for _ in range(200):
        n, m = rng.randint(1, 25), rng.randint(1, 25)
        cost = [[rng.uniform(-1000, 1000) for _ in range(m)] for _ in range(n)]
        assert linear_sum_assignment(cost) == _scipy(cost)


def test_identical_to_scipy_on_matching_shaped_boards():
    """What `match_all` actually builds: negated scores, volunteers fanned out
    into slot columns one tier deeper each, a tier priced by spread."""
    rng = random.Random(11)
    for _ in range(150):
        learners, volunteers = rng.randint(1, 30), rng.randint(1, 15)
        slots = [rng.randint(1, 3) for _ in range(volunteers)]
        tier_cost = rng.choice([0, 15, 40, learners * 301])
        scores = [[rng.randint(0, 300) for _ in range(volunteers)] for _ in range(learners)]
        columns = [(v, tier) for v, count in enumerate(slots) for tier in range(count)]
        cost = [[-(float(scores[i][v]) - tier_cost * tier) for v, tier in columns] for i in range(learners)]
        assert linear_sum_assignment(cost) == _scipy(cost)


def test_a_constant_board_pairs_rows_with_columns_in_order():
    # scipy's documented behaviour (gh-11602), which its remaining-column
    # order exists to guarantee.
    assert linear_sum_assignment([[3.0] * 4 for _ in range(4)]) == ([0, 1, 2, 3], [0, 1, 2, 3])


def test_finds_the_minimum_total():
    cost = [[4.0, 1.0, 3.0], [2.0, 0.0, 5.0], [3.0, 2.0, 2.0]]
    rows, cols = linear_sum_assignment(cost)
    assert (rows, cols) == ([0, 1, 2], [1, 0, 2])
    assert sum(cost[r][c] for r, c in zip(rows, cols)) == 5.0


def test_tall_boards_leave_the_extra_rows_unassigned():
    rows, cols = linear_sum_assignment([[1.0], [0.0], [2.0]])
    assert (rows, cols) == ([1], [0])


def test_an_empty_board_assigns_nothing():
    assert linear_sum_assignment([]) == ([], [])
    assert linear_sum_assignment([[], []]) == ([], [])


@pytest.mark.parametrize("bad", [math.nan, -math.inf])
def test_rejects_entries_scipy_rejects(bad):
    with pytest.raises(ValueError):
        linear_sum_assignment([[1.0, bad], [2.0, 3.0]])


def test_rejects_a_board_with_no_finite_assignment():
    with pytest.raises(ValueError):
        linear_sum_assignment([[math.inf, math.inf], [1.0, 2.0]])
