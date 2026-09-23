#!/usr/bin/env python3
"""End-to-end API smoke test against a running backend.

Usage: python api_smoke.py [base_url]   (default http://localhost:8000)

Exits 0 only if every assertion passes. Uses only the Python standard
library so the one-shot ``verify`` container needs no extra packages.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
failures: list[str] = []


def call(method: str, path: str, payload=None, expect: int = 200):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status = resp.status
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        status = e.code
        body = json.loads(e.read().decode())
    if status != expect:
        failures.append(f"{method} {path}: expected {expect}, got {status}: {body}")
    return status, body


def check(cond: bool, label: str):
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        failures.append(label)


print(f"== API smoke against {BASE} ==")

# 1. Health ----------------------------------------------------------------
status, body = call("GET", "/api/health")
check(status == 200 and body.get("status") == "ok", "GET /api/health -> ok")

# 2. Solve -----------------------------------------------------------------
messages = [
    {"id": "TM01", "C": 2, "T": 20, "D": 20, "J": 1},
    {"id": "TM02", "C": 4, "T": 50, "D": 40, "J": 2},
    {"id": "TM03", "C": 6, "T": 100, "D": 80, "J": 0},
    {"id": "TM04", "C": 1, "T": 25, "D": 10, "J": 0},
]
status, solved = call("POST", "/api/solve", {"messages": messages})
if status == 200:
    ids = {m["id"] for m in messages}
    order = solved["order"]
    check(len(order) == 4 and set(order) == ids and len(set(order)) == 4,
          "solve returns a permutation of all message ids")

    by_id = {m["id"]: m for m in messages}
    results = solved["results"]
    check(len(results) == 4, "solve returns one per-message result")

    for r in results:
        src = by_id[r["id"]]
        pos = order.index(r["id"])
        lower = [by_id[i] for i in order[pos + 1 :]]
        expected_b = max((m["C"] for m in lower), default=0)
        check(r["blocking"] == expected_b,
              f"{r['id']} blocking B={r['blocking']} equals max lower C")
        r0 = r["trajectory"][0]
        check(r0["r"] == src["J"] + src["C"] + expected_b,
              f"{r['id']} r(0) = J + C + B = {r0['r']}")
        rs = [s["r"] for s in r["trajectory"]]
        check(all(b >= a for a, b in zip(rs, rs[1:])),
              f"{r['id']} iteration values are monotonic non-decreasing")
        if r["deadline_miss"]:
            check(r["response_time"] > src["D"] and rs[-1] == r["response_time"],
                  f"{r['id']} miss conclusion consistent with R > D")
        else:
            check(rs[-1] == rs[-2] == r["response_time"] <= src["D"],
                  f"{r['id']} feasible conclusion ends at a fixed point <= D")

    check(
        solved["objective"]["deadline_misses"]
        == sum(1 for r in results if r["deadline_miss"]),
        "objective miss count matches per-row conclusions",
    )
    check(
        solved["objective"]["sum_capped_response_times"]
        == sum(min(r["response_time"], r["D"] + 1) for r in results),
        "objective sum equals sum min(R_i, D_i + 1)",
    )
else:
    check(False, "solve request succeeded")

# 3. Analyze an engineer-supplied order ------------------------------------
reverse_order = list(reversed(solved.get("order", [])))
status, analyzed = call(
    "POST", "/api/analyze", {"messages": messages, "order": reverse_order}
)
check(status == 200 and analyzed.get("order") == reverse_order,
      "analyze echoes the supplied priority order")
if status == 200:
    check(len(analyzed["results"]) == 4
          and all("trajectory" in r and "criterion" in r for r in analyzed["results"]),
          "analyze provides trajectories and criteria per message")

# 4. Validation errors must be 422 with field locations --------------------
bad = {
    "messages": [
        {"id": "x", "C": 3, "T": 8, "D": 5, "J": 9},   # J > D - C
        {"id": "x", "C": 2, "T": 6, "D": 6, "J": 0},   # duplicate id
    ]
}
status, err = call("POST", "/api/solve", bad, expect=422)
if status == 422:
    fields = {tuple(e["loc"]) for e in err["detail"]}
    check(("body", "messages", 0, "J") in fields, "422 locates J field (row 1)")
    check(("body", "messages", 1, "id") in fields, "422 locates duplicate id (row 2)")
else:
    check(False, "invalid payload rejected with 422")

print()
if failures:
    print(f"SMOKE FAILED: {len(failures)} problem(s)")
    sys.exit(1)
print("SMOKE PASSED")
