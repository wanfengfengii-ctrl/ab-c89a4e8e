"""Tests for the RTA recurrence and exact optimizer, incl. brute-force checks."""

from __future__ import annotations

import itertools
import random
import time

import pytest

from app.scheduler import (
    Message,
    analyze_order,
    optimal_order,
    response_time_trace,
)


def brute_force(messages):
    """Reference optimizer: enumerate every permutation."""
    ids = [m.id for m in messages]

    def key(perm):
        results = analyze_order(messages, list(perm))
        misses = sum(r["deadline_miss"] for r in results)
        capped = sum(min(r["response_time"], r["D"] + 1) for r in results)
        return misses, capped, tuple(perm)

    return min(itertools.permutations(ids), key=key)


def make(n, spec):
    return [Message(str(i), *vals) for i, vals in enumerate(spec)]


def test_rta_hand_example_blocking_and_interference():
    # M0: C=1 T=4 D=4 ; M1: C=2 T=6 D=6 ; order M0 high, M1 low.
    msgs = make(2, [(1, 4, 4, 0), (2, 6, 6, 0)])
    by_id = {m.id: m for m in msgs}

    r0, miss0, tr0 = response_time_trace(by_id["0"], [], blocking=2)
    assert r0 == 3 and not miss0  # J + C + B = 3
    # r(0)=3; with no interference r(1)=r(0), the fixed point is confirmed.
    assert [s["r"] for s in tr0] == [3, 3]
    assert tr0[-1]["interference"] == 0 and tr0[-1]["terms"] == []

    r1, miss1, tr1 = response_time_trace(by_id["1"], [by_id["0"]], blocking=0)
    assert not miss1 and r1 == 3
    assert [s["r"] for s in tr1] == [2, 3, 3]
    assert tr1[1]["terms"] == [
        {"id": "0", "jobs": 1, "C": 1, "T": 4, "J": 0, "amount": 1}
    ]


def test_rta_stops_at_first_value_above_deadline():
    # C=3 D=3 T=5, lower message blocks with C=3: r(0)=6 > 3 immediately.
    m = Message("a", 3, 5, 3, 0)
    r, miss, tr = response_time_trace(m, [], blocking=3)
    assert miss and r == 6 and len(tr) == 1

    # Interference driven miss: a C=3 T=3 D=3 interferer.
    hi = Message("h", 3, 3, 3, 0)
    r, miss, tr = response_time_trace(m, [hi], blocking=0)
    assert miss
    assert [s["r"] for s in tr] == [3, 6]  # r0=3 <= D, r1=6 > D stops
    assert tr[-1]["terms"][0]["jobs"] == 1


def test_jitter_enters_r0_and_ceiling():
    # J=2, C=2, T=6: alone r0 = 4.
    m = Message("a", 2, 6, 6, 2)
    r, miss, tr = response_time_trace(m, [], 0)
    assert (r, miss) == (4, False)

    # Higher message C=1 T=3 J=0: 4 -> 4+ceil(4/3)=6 -> 6+ceil(6/3)*1... = 6.
    hi = Message("h", 1, 3, 3, 0)
    r, miss, tr = response_time_trace(m, [hi], 0)
    assert (r, miss) == (6, False)
    assert [s["r"] for s in tr] == [4, 6, 6]


def test_secondary_objective_example():
    # M0 C=1 T=3 D=3, M1 C=3 T=5 D=5: both orders miss exactly one, but the
    # order with M1 high has smaller sum of capped response times.
    msgs = make(2, [(1, 3, 3, 0), (3, 5, 5, 0)])
    out = optimal_order(msgs)
    assert out["order"] == ["1", "0"]
    assert out["objective"]["deadline_misses"] == 1
    assert out["objective"]["sum_capped_response_times"] == 8
    res = {r["id"]: r for r in out["results"]}
    assert res["1"]["blocking"] == 1 and res["1"]["blocking_from_id"] == "0"
    assert res["0"]["blocking"] == 0
    assert res["0"]["deadline_miss"] and not res["1"]["deadline_miss"]


def test_lexicographic_tie_break():
    # Both orders equivalent on the numeric objectives -> smallest id first.
    msgs = make(2, [(1, 4, 4, 0), (2, 6, 6, 0)])
    out = optimal_order(msgs)
    assert out["order"] == ["0", "1"]
    assert out["objective"]["deadline_misses"] == 0


def test_lexicographic_tie_break_named_ids():
    msgs = [
        Message("beta", 1, 10, 10, 0),
        Message("alpha", 1, 10, 10, 0),
    ]
    out = optimal_order(msgs)
    assert out["order"][0] == "alpha"


def test_blocking_is_max_lower_c():
    # Three messages, lowest priority has the largest C: it blocks everyone.
    msgs = make(3, [(1, 10, 10, 0), (1, 10, 10, 0), (4, 10, 10, 0)])
    out = optimal_order(msgs)
    res = {r["id"]: r for r in out["results"]}
    for mid in ("0", "1"):
        assert res[mid]["blocking"] == 4
        assert res[mid]["blocking_from_id"] == "2"
    assert res["2"]["blocking"] == 0 and res["2"]["blocking_from_id"] is None


@pytest.mark.parametrize("seed", range(40))
def test_matches_brute_force_random_small(seed):
    rng = random.Random(seed)
    n = rng.randint(2, 5)
    msgs = []
    for i in range(n):
        T = rng.randint(4, 24)
        D = rng.randint(2, T)
        C = rng.randint(1, D)
        J = rng.randint(0, D - C)
        msgs.append(Message(f"m{i}", C, T, D, J))
    out = optimal_order(msgs)
    expected = brute_force(msgs)
    assert tuple(out["order"]) == expected
    res = analyze_order(msgs, out["order"])
    assert out["objective"]["deadline_misses"] == sum(
        r["deadline_miss"] for r in res
    )
    assert out["objective"]["sum_capped_response_times"] == sum(
        min(r["response_time"], r["D"] + 1) for r in res
    )


def test_n18_runtime():
    # 18 loose messages: exercises the full 2^18 state space and must stay
    # comfortably interactive for the engineering console.
    rng = random.Random(2026)
    msgs = []
    for i in range(18):
        T = rng.randint(50, 500)
        D = rng.randint(T // 2, T)
        C = rng.randint(1, max(1, D // 6))
        J = rng.randint(0, D - C)
        msgs.append(Message(f"M{i:02d}", C, T, D, J))
    start = time.perf_counter()
    out = optimal_order(msgs)
    elapsed = time.perf_counter() - start
    assert len(out["order"]) == 18
    assert len(set(out["order"])) == 18
    assert elapsed < 30, f"n=18 took {elapsed:.1f}s"


def test_result_payload_consistency():
    msgs = make(3, [(1, 8, 8, 0), (2, 12, 12, 1), (3, 20, 20, 0)])
    out = optimal_order(msgs)
    for r in out["results"]:
        assert r["position"] == out["order"].index(r["id"]) + 1
        assert r["higher_priority_ids"] == out["order"][: r["position"] - 1]
        assert r["trajectory"][0]["r"] == r["J"] + r["C"] + r["blocking"]
        if r["deadline_miss"]:
            assert r["response_time"] > r["D"]
            assert not r["converged"]
        else:
            assert r["response_time"] <= r["D"]
            assert r["converged"]
