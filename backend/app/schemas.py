"""Pydantic request/response schemas with field-level validation."""

from __future__ import annotations

from typing import Annotated, List, Optional

from pydantic import BaseModel, ConfigDict, Field

Int1e9 = Annotated[int, Field(ge=1, le=10**9)]
NonNeg = Annotated[int, Field(ge=0, le=10**9)]


class MessageIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(
        ..., min_length=1, max_length=32, pattern=r"^[\w.\-]+$"
    )
    C: Int1e9
    T: Int1e9
    D: Int1e9
    J: NonNeg = 0


class SolveRequest(BaseModel):
    messages: List[MessageIn] = Field(..., min_length=2, max_length=18)


class AnalyzeRequest(BaseModel):
    messages: List[MessageIn] = Field(..., min_length=2, max_length=18)
    order: List[str] = Field(..., min_length=2, max_length=18)


class TermOut(BaseModel):
    id: str
    jobs: int
    C: int
    T: int
    J: int
    amount: int


class StepOut(BaseModel):
    step: int
    r: int
    interference: int
    terms: List[TermOut]
    rule: str


class MessageResultOut(BaseModel):
    id: str
    position: int
    C: int
    T: int
    D: int
    J: int
    blocking: int
    blocking_from_id: Optional[str]
    higher_priority_ids: List[str]
    trajectory: List[StepOut]
    response_time: int
    deadline_miss: bool
    converged: bool
    criterion: str


class ObjectiveOut(BaseModel):
    deadline_misses: int
    sum_capped_response_times: int


class SearchOut(BaseModel):
    messages: int
    states_evaluated: int
    rta_iterations: int
    total_permutations: int
    method: str


class SolveResponse(BaseModel):
    order: List[str]
    objective: ObjectiveOut
    tie_break: str
    search: SearchOut
    results: List[MessageResultOut]


class AnalyzeResponse(BaseModel):
    order: List[str]
    results: List[MessageResultOut]
