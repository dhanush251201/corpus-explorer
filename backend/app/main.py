"""
Corpus Explorer API - the read-only backend of the corpus explorer.

It serves JSON under /api only. The frontend is a separate static site that
calls it from another origin, which ALLOW_ORIGINS must name.

Run:  uvicorn app.main:app --reload --port 8000    (from backend/)
"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .routers.api import router
from .safety import UnsafeQuery

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("corpus")

app = FastAPI(
    title="Corpus Explorer",
    description="Read-only interface to the European think tank corpus.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOW_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],       # never PUT/PATCH/DELETE
    allow_headers=["*"],
)

app.include_router(router)


@app.exception_handler(UnsafeQuery)
async def unsafe(_request, exc: UnsafeQuery):
    return JSONResponse(status_code=400,
                        content={"detail": f"Query rejected by the read-only validator: {exc}"})


@app.on_event("startup")
def startup():
    from . import db, stats
    from .schema import knowledge
    log.info("database=%s master=%s demo=%s", settings.DB_NAME, settings.MASTER,
             settings.DEMO_MODE)
    log.info("allowed frontend origins: %s", ", ".join(settings.ALLOW_ORIGINS) or "none")
    log.info("corpus knowledge: %s (%d institutions)",
             knowledge.loaded_from or "NOT FOUND - falling back to defaults",
             len(knowledge.institutions))
    try:
        from .routers.api import _knowledge_check
        chk = _knowledge_check()
        if chk.get("ok") is False:
            log.warning("=" * 72)
            log.warning("%d source(s) in the database are not described by %s",
                        len(chk.get("undescribed") or []), chk.get("file"))
            log.warning("first few: %s", ", ".join(chk.get("undescribed") or [])[:160])
            log.warning("If KNOWLEDGE_PATH points at fixtures/, unset it and restart.")
            log.warning("=" * 72)
        else:
            log.info("sources: %d live, %d described in the metadata file",
                     chk.get("live_sources"), chk.get("described_in_file"))
    except Exception as e:
        log.warning("knowledge cross-check failed: %s", e)

    try:
        priv = db.privileges()
        if priv.get("write_capable"):
            log.warning("=" * 72)
            log.warning("This connection holds WRITE-CAPABLE roles: %s",
                        ", ".join(priv.get("writable_roles") or []))
            log.warning("The application never writes, but you should switch to a")
            log.warning("MongoDB user holding only the `read` role. See the README.")
            log.warning("=" * 72)
        else:
            log.info("connection roles: %s", priv.get("roles"))
    except Exception as e:
        log.warning("could not verify connection privileges: %s", e)

    snap = stats.load()
    log.info("stats snapshot (%s): %s%s", stats.SNAPSHOT,
             snap.get("generated", "?") if snap else "none yet",
             " (stale)" if stats.is_stale(snap) else "")
    if settings.STATS_SCHEDULER:
        stats.start_scheduler()
    else:
        log.info("stats scheduler off (STATS_SCHEDULER=0) - run compute_stats.py on a schedule")


@app.get("/")
def index():
    return {"service": "Corpus Explorer API", "version": app.version,
            "docs": "/docs", "health": "/api/health",
            "note": "This is the API only. Open the frontend's own address to use the explorer."}
