import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from database import init_db
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
def list_tags():
    return {"tags": VALID_TAGS}


@app.get("/api/health")
def health():
    return {"status": "ok"}
