import json
import logging
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import init_pool, close_pool, pool
from . import logbuffer
from .services import encontro as encontro_service
from .routers import rooms, token, chat, lobby, invites, whiteboard, recording, ws, backgrounds, admin, internal, client, breakouts, openpbl_class, encontro

APP_VERSION = "1.0.0"

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("bwl")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_pool()
    # A tabela do template do encontro nasce aqui, e nao numa migration
    # aplicada a mao: publicar NAO aplica migration neste repositorio (ver
    # `db.tem_coluna`), e a 013 passou meses fora de producao enquanto o
    # codigo ja contava com ela. Tabela nova e vazia e o caso em que criar na
    # subida nao tem risco: nada a migrar, nada a perder. Falhar aqui nao
    # derruba o servico -- sem a tabela, o template e o padrao do codigo.
    await encontro_service.garantir_tabela()
    log.info(json.dumps({"evt": "startup", "version": APP_VERSION}))
    yield
    await close_pool()


app = FastAPI(title="Video Rooms Kit", version=APP_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")] if settings.cors_origins != "*" else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def observability(request: Request, call_next):
    """Structured access + error logging (one JSON line per request)."""
    start = time.perf_counter()
    path = request.url.path
    skip = path.startswith("/api/admin/logs") or path.startswith("/health")
    try:
        resp = await call_next(request)
    except Exception:
        dur = (time.perf_counter() - start) * 1000
        entry = {"evt": "error", "method": request.method, "path": path, "status": 500, "ms": round(dur, 1)}
        log.exception(json.dumps(entry))
        if not skip:
            logbuffer.add(dict(entry))
        raise
    dur = (time.perf_counter() - start) * 1000
    entry = {"evt": "req", "method": request.method, "path": path, "status": resp.status_code, "ms": round(dur, 1)}
    log.info(json.dumps(entry))
    if not skip:
        logbuffer.add(dict(entry))
    resp.headers["X-Response-Time-Ms"] = str(round(dur, 1))
    return resp


app.include_router(rooms.router)
app.include_router(breakouts.router)
app.include_router(openpbl_class.router)
app.include_router(token.router)
app.include_router(chat.router)
app.include_router(lobby.router)
app.include_router(invites.router)
app.include_router(whiteboard.router)
app.include_router(recording.router)
app.include_router(recording.webhook_router)
app.include_router(backgrounds.router)
app.include_router(admin.router)
app.include_router(encontro.router)
app.include_router(internal.router)
app.include_router(client.router)
app.include_router(ws.router)


@app.get("/health")
async def health():
    """Lightweight liveness probe (load balancers / uptime pings)."""
    return {"ok": True, "version": APP_VERSION}


@app.get("/health/detail")
async def health_detail():
    """Deeper readiness check — DB connectivity + dependency status."""
    out: dict = {"ok": True, "version": APP_VERSION, "db": False, "livekit": False}
    try:
        await pool().fetchval("SELECT 1")
        out["db"] = True
    except Exception:
        out["ok"] = False
    try:
        from .services.livekit_service import livekit_api
        from livekit import api as lkapi
        lk = livekit_api()
        try:
            await lk.room.list_rooms(lkapi.ListRoomsRequest())
            out["livekit"] = True
        finally:
            await lk.aclose()
    except Exception:
        out["livekit"] = False  # best-effort; doesn't fail overall readiness
    return out
