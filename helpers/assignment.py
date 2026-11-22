"""Rectangular linear sum assignment (the Hungarian problem) in pure Python.

A line-for-line port of scipy's `scipy.optimize.linear_sum_assignment`
(`scipy/optimize/rectangular_lsap/rectangular_lsap.cpp`: Crouse's shortest
augmenting path, "On implementing 2D rectangular assignment algorithms",
IEEE TAES 2016). It keeps scipy's loop order, tie-breaks and float
arithmetic, so it returns the same pairing scipy would — not just one of
equal cost — which `tests/unit/test_assignment.py` checks against scipy
itself. Porting it, rather than shipping scipy for this one function, keeps
~200 MB of scipy and numpy out of the production image.

The work is one augmenting search per row of the shorter side, each a
Dijkstra over the columns that are left: O(n² · m) worst case, far less on the
tie-heavy integer boards matching builds.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

__all__ = ["linear_sum_assignment"]


def linear_sum_assignment(cost: Sequence[Sequence[float]]) -> tuple[list[int], list[int]]:
    """Pairs rows with columns at minimum total cost.

    Args:
        cost (Sequence[Sequence[float]]): A rectangular cost matrix, rows of
            equal length. A tall matrix (more rows than columns) leaves its
            extra rows unassigned, as a wide one leaves extra columns.

    Returns:
        tuple[list[int], list[int]]: `(rows, cols)` — `cost[rows[k]][cols[k]]`
            is the k-th assigned cell, rows in ascending order, exactly as
            scipy returns them.

    Raises:
        ValueError: The matrix holds a NaN or -inf, or no assignment of finite
            total cost exists.
    """
    nr = len(cost)
    nc = len(cost[0]) if nr else 0
    if nr == 0 or nc == 0:
        return [], []

    # A tall matrix is solved transposed, so every row of the solved matrix
    # gets a column.
    transpose = nc < nr
    rows: list[list[float]] = (
        [[float(x) for x in col] for col in zip(*cost, strict=True)]
        if transpose
        else [[float(x) for x in row] for row in cost]
    )
    if transpose:
        nr, nc = nc, nr

    for row in rows:
        if len(row) != nc:
            raise ValueError("cost matrix must be rectangular")
        for x in row:
            if math.isnan(x) or x == -math.inf:
                raise ValueError("matrix contains invalid numeric entries")

    inf = math.inf
    u = [0.0] * nr
    v = [0.0] * nc
    path = [-1] * nc
    col4row = [-1] * nr
    row4col = [-1] * nc

    for cur_row in range(nr):
        # ── shortest augmenting path from cur_row (scipy's augmenting_path) ──
        min_val = 0.0
        # Filled in reverse so a constant matrix solves to the identity
        # (scipy gh-11602) — and so ties break exactly as scipy's do.
        remaining = list(range(nc - 1, -1, -1))
        shortest = [inf] * nc
        visited_rows: list[int] = []
        visited_cols: list[int] = []

        i = cur_row
        sink = -1
        while sink == -1:
            visited_rows.append(i)
            row = rows[i]
            ui = u[i]
            index = -1
            lowest = inf
            # The hot loop: everything is a local, and the tie-break test runs
            # only for a column that could win. Arithmetic stays in scipy's
            # order — `(min_val + c) - u - v` — so floats round as scipy's do.
            for it, j in enumerate(remaining):
                r = min_val + row[j] - ui - v[j]
                s = shortest[j]
                if r < s:
                    path[j] = i
                    shortest[j] = s = r
                # On a tie, prefer a column that ends the path (a free one) —
                # this matters on small-integer boards like matching's.
                if s <= lowest and (s < lowest or row4col[j] == -1):
                    lowest = s
                    index = it

            min_val = lowest
            if min_val == inf:
                raise ValueError("cost matrix is infeasible")

            j = remaining[index]
            if row4col[j] == -1:
                sink = j
            else:
                i = row4col[j]
            visited_cols.append(j)
            # scipy's swap-with-last-and-shrink, keeping its column order.
            last = remaining.pop()
            if index < len(remaining):
                remaining[index] = last

        # ── update the dual variables ──
        # Each update reads only `shortest` and `col4row`, neither of which
        # changes here, so walking the visited lists gives the same values as
        # scipy's sweep over every row and column flag.
        u[cur_row] += min_val
        for i in visited_rows:
            if i != cur_row:
                u[i] += min_val - shortest[col4row[i]]
        for j in visited_cols:
            v[j] -= min_val - shortest[j]

        # ── augment along the path back to cur_row ──
        j = sink
        while True:
            i = path[j]
            row4col[j] = i
            col4row[i], j = j, col4row[i]
            if i == cur_row:
                break

    if transpose:
        # Solved rows are the caller's columns; report in caller-row order.
        order = sorted(range(nr), key=col4row.__getitem__)
        return [col4row[k] for k in order], order
    return list(range(nr)), col4row
