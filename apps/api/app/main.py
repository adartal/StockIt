"""FastAPI app entrypoint.

Wires the M6 routers (plans, watchlist, notes), configures CORS so the
Next.js app at ``apps/web`` can call this API in dev and prod, and starts
the M9 watchlist scheduler inside the app's lifespan.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes.notes import router as notes_router
from app.routes.plans import router as plans_router
from app.routes.watchlist import router as watchlist_router
from app.scheduler import _scheduler_enabled, build_scheduler

logger = logging.getLogger(__name__)

DEFAULT_CORS_ORIGINS = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
)


def _cors_origins() -> list[str]:
    raw = os.getenv("WEB_CORS_ORIGINS", "")
    if not raw:
        return list(DEFAULT_CORS_ORIGINS)
    return [o.strip() for o in raw.split(",") if o.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    scheduler = None
    if _scheduler_enabled():
        scheduler = build_scheduler()
        scheduler.start()
        app.state.scheduler = scheduler
        logger.info("scheduler: started watchlist daily refresh job")
    else:
        app.state.scheduler = None
        logger.info("scheduler: disabled (test mode or explicit override)")
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)


app = FastAPI(title="StockIt API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(plans_router)
app.include_router(watchlist_router)
app.include_router(notes_router)


__all__ = ["app"]
