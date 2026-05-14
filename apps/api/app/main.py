"""FastAPI app entrypoint.

Wires the M6 routers (plans, watchlist, notes) and configures CORS so the
Next.js app at ``apps/web`` can call this API in dev and prod.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes.notes import router as notes_router
from app.routes.plans import router as plans_router
from app.routes.settings import router as settings_router
from app.routes.watchlist import router as watchlist_router

DEFAULT_CORS_ORIGINS = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
)


def _cors_origins() -> list[str]:
    raw = os.getenv("WEB_CORS_ORIGINS", "")
    if not raw:
        return list(DEFAULT_CORS_ORIGINS)
    return [o.strip() for o in raw.split(",") if o.strip()]


app = FastAPI(title="StockIt API", version="0.1.0")

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
app.include_router(settings_router)


__all__ = ["app"]
