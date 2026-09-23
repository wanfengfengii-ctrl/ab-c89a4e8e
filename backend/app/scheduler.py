"""Fixed-priority response-time analysis and exact priority optimization.

Priority convention
-------------------
An ``order`` is listed from *highest* priority to *lowest* priority.

For a message ``i``:

* ``B_i`` is the maximum transmission time ``C`` among all lower-priority
  messages (``0`` if there are none).
* The higher-priority set ``H`` interferes through the recurrence

  ``r(0) = J_i + C_i + B_i``

  ``r(k+1) = J_i + C_i + B_i
             + sum_{h in H} ceil((r(k) + J_h) / T_h) * C_h``

  The iteration stops at a fixed point or the first value strictly greater
  than ``D_i``. The final value is ``R_i``.

Exact optimization
------------------
``R_i`` depends only on the *set* of higher-priority messages and on
``max C`` over the lower-priority set -- never on the ordering inside either
set. Building a permutation from the lowest priority upwards therefore gives
an additive cost over subsets, solved by an exact subset DP (O(n 2^n)
edges). Ties on (number of misses, capped response-time sum) are resolved by
reconstructing the lexicographically smallest id sequence from the highest
priority downwards.

Performance note
----------------
Response-time values are memoized per (message, higher-priority set). RTA
iterations may only be warm-started *from below* the least fixed point (a
start above can converge to a spurious higher fixed point), so for each
message we first compute a blocking-free interference table along the
subset chain ``H -> H \\ {lowest bit}`` (each step adds interference and is a
valid from-below start), and then run the real recurrence once per state
starting from ``max(J_i + C_i + B, R_interference(H))``.
"""

from __future__ import annotations

from array import array


class Message:
    """A telemetry message with integer timing parameters."""

    __slots__ = ("id", "C", "T", "D", "J")

    def __init__(self, id: str, C: int, T: int, D: int, J: int):
        self.id = id
        self.C = C
        self.T = T
        self.D = D
        self.J = J


def response_time_trace(msg_i: Message, higher: list[Message], blocking: int):
    """Run the RTA recurrence for one message and return a full trace.

    Returns ``(R, deadline_miss, trajectory)`` where ``trajectory`` is a list
    of dicts starting with ``r(0) = J_i + C_i + B``. Each later step records,
    for every higher-priority message, the number of interfering jobs
    ``ceil((r(k) + J_h) / T_h)`` and its contributed workload.
    """
    base = msg_i.J + msg_i.C + blocking
    trajectory = [
        {
            "step": 0,
            "r": base,
            "interference": 0,
            "terms": [],
            "rule": "r(0) = J + C + B",
        }
    ]
    if base > msg_i.D:
        return base, True, trajectory

    r = base
    while True:
        terms = []
        interference = 0
        for h in higher:
            jobs = (r + h.J + h.T - 1) // h.T
            amount = jobs * h.C
            if amount:
                terms.append(
                    {
                        "id": h.id,
                        "jobs": jobs,
                        "C": h.C,
                        "T": h.T,
                        "J": h.J,
                        "amount": amount,
                    }
                )
            interference += amount
        nxt = base + interference
        trajectory.append(
            {
                "step": len(trajectory),
                "r": nxt,
                "interference": interference,
                "terms": terms,
                "rule": "r(k+1) = J + C + B + sum ceil((r(k) + J_h)/T_h) * C_h",
            }
        )
        if nxt > msg_i.D:
            return nxt, True, trajectory
        if nxt == r:
            return nxt, False, trajectory
        r = nxt


def analyze_order(messages: list[Message], order: list[str]) -> list[dict]:
    """Produce the full per-message analysis for a concrete priority order."""
    by_id = {m.id: m for m in messages}
    results = []
    for pos, mid in enumerate(order):
        msg = by_id[mid]
        higher = [by_id[h] for h in order[:pos]]
        lower = [by_id[h] for h in order[pos + 1 :]]
        if lower:
            blocking = max(m.C for m in lower)
            # Among messages attaining max C the lowest-priority one is the
            # canonical blocking source (scanning high -> low, take the last).
            blocker = next(m for m in reversed(lower) if m.C == blocking)
        else:
            blocker = None
            blocking = 0
        response, missed, trace = response_time_trace(msg, higher, blocking)
        results.append(
            {
                "id": msg.id,
                "position": pos + 1,
                "C": msg.C,
                "T": msg.T,
                "D": msg.D,
                "J": msg.J,
                "blocking": blocking,
                "blocking_from_id": blocker.id if blocker else None,
                "higher_priority_ids": [h.id for h in higher],
                "trajectory": trace,
                "response_time": response,
                "deadline_miss": missed,
                "converged": not missed,
                "criterion": (
                    f"R = {response} > D = {msg.D}，首次超过截止期发生在第 "
                    f"{trace[-1]['step']} 次迭代，判定超期"
                    if missed
                    else f"R = {response} <= D = {msg.D}，迭代到达定点，判定可行"
                ),
            }
        )
    return results


def _max_c_table(Cs: list[int], n: int) -> list[int]:
    """maxC[mask] = maximum C over the messages in ``mask`` (0 for empty)."""
    size = 1 << n
    max_c = [0] * size
    for mask in range(1, size):
        low = mask & -mask
        idx = low.bit_length() - 1
        prev = max_c[mask ^ low]
        c = Cs[idx]
        max_c[mask] = c if c > prev else prev
    return max_c


def _factorial(n: int) -> int:
    value = 1
    for k in range(2, n + 1):
        value *= k
    return value


def optimal_order(messages: list[Message]) -> dict:
    """Find the exact optimum over all ``n!`` priority orders.

    Optimization key, minimized in this order:
    ``(deadline_misses, sum min(R_i, D_i + 1), lexicographic id sequence)``.
    """
    n = len(messages)
    if not 2 <= n <= 18:
        raise ValueError("expected between 2 and 18 messages")

    ids = [m.id for m in messages]
    Cs = [m.C for m in messages]
    Ts = [m.T for m in messages]
    Ds = [m.D for m in messages]
    Js = [m.J for m in messages]

    size = 1 << n
    full = size - 1
    bits = [1 << i for i in range(n)]
    max_c = _max_c_table(Cs, n)

    # For each message i, two tables over masks H that never contain bit i:
    #   free[i][H] : blocking-free RTA (B = 0), subset-chain warm starts
    #   tab[i][H]  : real RTA with B = maxC[full \ H \ {i}]
    # Encoding:  v > 0 -> feasible, R = v
    #            v < 0 -> deadline miss, objective contribution -v = D_i + 1
    # (R > D with integers implies R >= D+1, so min(R, D+1) = D+1.)
    free = [array("q", [0]) * size for _ in range(n)]
    tab = [array("q", [0]) * size for _ in range(n)]
    iterations_run = 0

    for i in range(n):
        ci, ti, di, ji = Cs[i], Ts[i], Ds[i], Js[i]
        biti = bits[i]
        frow = free[i]
        trow = tab[i]
        base0 = ji + ci
        frow[0] = base0  # no interference, no blocking -> fixed point J + C

        # Blocking-free interference table, ascending mask order keeps each
        # strict subset already finalized.
        for hmask in range(1, size):
            if hmask & biti:
                continue
            warm = frow[hmask & (hmask - 1)]
            if warm < 0:
                # A subset of the interference already forced a miss.
                frow[hmask] = warm
                continue
            r = warm
            while True:
                total = base0
                h = hmask
                while h:
                    low = h & -h
                    j = low.bit_length() - 1
                    total += ((r + Js[j] + Ts[j] - 1) // Ts[j]) * Cs[j]
                    h ^= low
                iterations_run += 1
                if total > di:
                    frow[hmask] = -di - 1
                    break
                if total == r:
                    frow[hmask] = total
                    break
                r = total

        # Real table: blocking B plus the same interference. The blocking-free
        # fixed point is a valid from-below warm start for this (i, H).
        for hmask in range(size):
            if hmask & biti:
                continue
            no_block = frow[hmask]
            if no_block < 0:
                trow[hmask] = no_block
                continue
            lower_mask = full ^ hmask ^ biti
            block = max_c[lower_mask]
            base = base0 + block
            r = no_block if no_block > base else base
            while True:
                total = base
                h = hmask
                while h:
                    low = h & -h
                    j = low.bit_length() - 1
                    total += ((r + Js[j] + Ts[j] - 1) // Ts[j]) * Cs[j]
                    h ^= low
                iterations_run += 1
                if total > di:
                    trow[hmask] = -di - 1
                    break
                if total == r:
                    trow[hmask] = total
                    break
                r = total

    # Subset DP: S is the set already placed at the LOWEST priorities.
    infinity = 10**18
    dp_miss = [infinity] * size
    dp_sum = [0] * size
    dp_miss[0] = 0

    for placed in range(size):
        cur_miss = dp_miss[placed]
        if cur_miss == infinity:
            continue
        cur_sum = dp_sum[placed]
        remaining = full ^ placed
        while remaining:
            low = remaining & -remaining
            i = low.bit_length() - 1
            higher_mask = full ^ placed ^ low
            val = tab[i][higher_mask]
            nxt = placed | low
            if val < 0:
                cand_miss = cur_miss + 1
                cand_sum = cur_sum - val
            else:
                cand_miss = cur_miss
                cand_sum = cur_sum + val
            if cand_miss < dp_miss[nxt] or (
                cand_miss == dp_miss[nxt] and cand_sum < dp_sum[nxt]
            ):
                dp_miss[nxt] = cand_miss
                dp_sum[nxt] = cand_sum
            remaining ^= low

    best_misses = dp_miss[full]
    best_sum = dp_sum[full]

    # Greedy reconstruction from the highest priority: at each step take the
    # smallest id that can still lie on an optimal-cost path. ``prefix_*`` is
    # the accumulated cost of the already-fixed higher-priority elements.
    remaining = full
    order: list[str] = []
    prefix_miss = 0
    prefix_sum = 0
    while remaining:
        higher_mask = full ^ remaining
        candidates = []
        cand = remaining
        while cand:
            low = cand & -cand
            i = low.bit_length() - 1
            placed = remaining ^ low
            val = tab[i][higher_mask]
            miss_add = 1 if val < 0 else 0
            sum_add = -val if val < 0 else val
            if (
                prefix_miss + miss_add + dp_miss[placed] == best_misses
                and prefix_sum + sum_add + dp_sum[placed] == best_sum
            ):
                candidates.append(i)
            cand ^= low
        chosen = min(candidates, key=lambda idx: ids[idx])
        order.append(ids[chosen])
        remaining ^= bits[chosen]
        val = tab[chosen][higher_mask]
        if val < 0:
            prefix_miss += 1
            prefix_sum -= val
        else:
            prefix_sum += val

    results = analyze_order(messages, order)

    return {
        "order": order,
        "objective": {
            "deadline_misses": best_misses,
            "sum_capped_response_times": best_sum,
        },
        "tie_break": "相同 (超期数, sum min(R_i, D_i+1)) 下，取编号序列字典序最小（自高优先级向低优先级比较）",
        "search": {
            "messages": n,
            "states_evaluated": size,
            "rta_iterations": iterations_run,
            "total_permutations": _factorial(n),
            "method": "exact subset DP over priority suffixes with memoized response-time analysis",
        },
        "results": results,
    }
