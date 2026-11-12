"""FastAPI application entry point — RPG NeuralMesh.

Accelerator baseline: environment-scoped CORS, structured logging, Phoenix
tracing, and a session-oriented example router. Add routers under
api/routers/ and register them in the "Routers" block.
"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import auth, context, context_graphs, health, help, mesh
from observability.tracing import init_tracing, instrument_fastapi
from shared.config import get_settings
from shared.logger import get_logger, setup_logging

log = get_logger("api.main")
settings = get_settings()

APP_VERSION = "1.0.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    init_tracing()
    # (pre-deploy pipeline step or init container), not create_all() on startup.
    log.info("api.startup", env=settings.app_env, version=APP_VERSION)
    from services.mesh_runtime import runtime  # strict mode refuses a cloud model outside development here

    rt = runtime()
    if os.getenv("NEURALMESH_REFRESH_GRAPH_ON_START", "1") == "1":
        refresh = asyncio.create_task(rt.refresh_from_nodes())  # nodes may start after the API
        app.state.graph_refresh = refresh
    yield
    log.info("api.shutdown")


app = FastAPI(
    title="RPG NeuralMesh API",
    description="Cross-subsidiary knowledge mesh and context API for SkillForge",
    version=APP_VERSION,
    lifespan=lifespan,
)
instrument_fastapi(app)

# ── CORS — wildcard is never used outside development ──────────────────────────
if settings.app_env == "development":
    _cors_origins = [
        "http://localhost:3000",
        "http://localhost:5173",
    ]
else:
    _cors_origins = [o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()]
    if not _cors_origins:
        raise RuntimeError(
            f"CORS_ALLOWED_ORIGINS must be set in app_env={settings.app_env!r}. "
            "Example: https://__APP_NAME__-fe.bravesky-d9f9eeb7.eastus2.azurecontainerapps.io"
        )

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(health.router, tags=["Health"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(mesh.router, prefix="/api/v1/mesh", tags=["Mesh"])
app.include_router(context.router, prefix="/api/v1/context", tags=["Context for applications"])
app.include_router(help.router, prefix="/api/v1/help", tags=["Help chat"])
app.include_router(context_graphs.router, prefix="/api/v1/context-graphs", tags=["Ingested context graphs"])
app.add_exception_handler(context.ProblemError, lambda request, exc: context.problem_response(exc))
