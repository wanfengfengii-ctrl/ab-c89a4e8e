"""Cross-field / cross-row validation producing field-located 422 errors."""

from __future__ import annotations

from typing import Iterable

from fastapi import HTTPException

from .schemas import MessageIn
from .scheduler import Message


def validate_messages(raw: Iterable[MessageIn]) -> list[Message]:
    """Validate relational constraints and convert to scheduler messages.

    Primitive constraints (types, ranges, id pattern) are enforced by
    Pydantic; this adds: 2..18 rows, unique ids, ``C <= D <= T`` and
    ``J <= D - C``. Every error carries a JSON-pointer-style loc so the UI
    can mark the exact field.
    """
    rows = list(raw)
    errors: list[dict] = []

    if not 2 <= len(rows) <= 18:
        raise HTTPException(
            status_code=422,
            detail=[
                {
                    "loc": ["body", "messages"],
                    "msg": f"消息数量必须在 2 至 18 条之间，当前为 {len(rows)}",
                    "type": "value_error.count",
                }
            ],
        )

    seen: dict[str, int] = {}
    for idx, row in enumerate(rows):
        loc = ["body", "messages", idx]
        if row.id in seen:
            errors.append(
                {
                    "loc": loc + ["id"],
                    "msg": f"编号重复：{row.id!r} 已在第 {seen[row.id] + 1} 行使用",
                    "type": "value_error.unique",
                }
            )
        else:
            seen[row.id] = idx

        if not (row.C <= row.D <= row.T):
            errors.append(
                {
                    "loc": loc + ["D"],
                    "msg": (
                        f"必须满足 C <= D <= T，当前 C={row.C}, "
                        f"D={row.D}, T={row.T}"
                    ),
                    "type": "value_error.ordering",
                }
            )
        if row.J > row.D - row.C:
            errors.append(
                {
                    "loc": loc + ["J"],
                    "msg": (
                        f"抖动必须满足 0 <= J <= D - C，当前 J={row.J}，"
                        f"D - C = {row.D - row.C}"
                    ),
                    "type": "value_error.jitter",
                }
            )

    if errors:
        raise HTTPException(status_code=422, detail=errors)

    return [Message(id=r.id, C=r.C, T=r.T, D=r.D, J=r.J) for r in rows]


def validate_order(messages: list[Message], order: list[str]) -> list[str]:
    ids = {m.id for m in messages}
    errors: list[dict] = []
    if len(order) != len(messages) or set(order) != ids:
        errors.append(
            {
                "loc": ["body", "order"],
                "msg": "顺序必须恰好包含每条消息的编号各一次（高优先级在前）",
                "type": "value_error.permutation",
            }
        )
    if len(set(order)) != len(order):
        errors.append(
            {
                "loc": ["body", "order"],
                "msg": "顺序中存在重复编号",
                "type": "value_error.duplicate",
            }
        )
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    return order
