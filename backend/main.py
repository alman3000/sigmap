import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from config import get_settings
from database import get_db, init_db
from routers import admin, auth, photos, upload
from services.processing import cleanup_orphaned_pending, import_existing_geojson
from tags import VALID_TAGS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("graffmap backend starting up")
    init_db()
    import_existing_geojson()
    cleanup_orphaned_pending()
    yield
    logger.info("graffmap backend shut down")


app = FastAPI(
    title="graffmap API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().APP_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(upload.router)
app.include_router(photos.router)
app.include_router(admin.router)


@app.get("/api/tags")
def list_tags(db: Session = Depends(get_db)):
    try:
        rows = db.execute(
            text(
                "SELECT DISTINCT tag FROM "
                "(SELECT jsonb_array_elements_text(tags::jsonb) AS tag "
                " FROM photos WHERE status = 'approved') sub "
                "WHERE tag IS NOT NULL AND tag != '' ORDER BY tag"
            )
        ).fetchall()
        db_tags = [r[0] for r in rows]
    except Exception:
        db_tags = []
    seen = set(db_tags)
    merged = db_tags + [t for t in VALID_TAGS if t not in seen]
    return {"tags": merged or VALID_TAGS}


@app.get("/api/months")
def list_months(db: Session = Depends(get_db)):
    try:
        rows = db.execute(
            text(
                "SELECT SUBSTRING(datetime_original, 1, 7) AS ym, COUNT(*) AS cnt "
                "FROM photos WHERE status = 'approved' AND datetime_original != '' "
                "GROUP BY ym ORDER BY ym"
            )
        ).fetchall()
        return {"months": [{"month": r[0], "count": r[1]} for r in rows]}
    except Exception:
        return {"months": []}


@app.get("/api/health")
def health():
    return {"status": "ok"}
