"""FastAPI application: fixed-priority telemetry bus analysis."""

from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__
from .scheduler import analyze_order, optimal_order
from .validation import validate_messages, validate_order
from .schemas import AnalyzeRequest, SolveRequest

API_PREFIX = "/api"

app = FastAPI(
    title="卫星固定优先级遥测总线可调度性分析",
    version=__version__,
    description=(
        "对 2-18 条周期消息求全局最优固定优先级顺序，并给出每条消息的"
        "阻塞值、RTA 迭代轨迹与超期结论。"
    ),
)

_default_origins = "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000"
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        o.strip() for o in os.getenv("CORS_ORIGINS", _default_origins).split(",") if o.strip()
    ],
    allow_origin_regex=os.getenv("CORS_ORIGIN_REGEX") or None,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Uniform 422 body: {"detail": [{"loc": [...], "msg": ..., "type": ...}]}."""
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.get(f"{API_PREFIX}/health")
def health():
    return {"status": "ok", "version": __version__}


@app.post(f"{API_PREFIX}/solve")
def solve(req: SolveRequest):
    """Compute the exact globally-optimal fixed-priority order."""
    messages = validate_messages(req.messages)
    return optimal_order(messages)


@app.post(f"{API_PREFIX}/analyze")
def analyze(req: AnalyzeRequest):
    """Analyze an engineer-supplied priority order without optimizing."""
    messages = validate_messages(req.messages)
    order = validate_order(messages, req.order)
    results = analyze_order(messages, order)
    return {"order": order, "results": results}
