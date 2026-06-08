import asyncio
import base64
import logging
import os
import secrets
import shutil
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, Header, HTTPException, UploadFile, status
from pydantic import BaseModel

from config import get_settings
from database import SessionLocal
from models import Photo, PhotoStatus
from services.mail import send_new_photo_notification
from services.processing import (
    _create_thumbnail,
    _extract_gps,
    process_uploaded_file,
    regenerate_geojson,
    register_location,
)

logger = logging.getLogger(__name__)


def _process_notify(filepath: str) -> None:
    """Background task: process a GPS-tagged upload, regenerate GeoJSON, notify admins."""
    if process_uploaded_file(filepath):
        regenerate_geojson()
        try:
            send_new_photo_notification(os.path.basename(filepath))
        except Exception as exc:
            logger.warning("Admin notification failed: %s", exc)

router = APIRouter(prefix="/api/upload", tags=["upload"])

_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".heic", ".heif"}
_MAX_SIZE = 50 * 1024 * 1024  # 50 MB


def _check_auth(authorization: str | None = Header(default=None)) -> None:
    """Parse Basic Auth manually — no WWW-Authenticate header on failure so
    the browser never shows its own credential popup."""
    settings = get_settings()
    ok = False
    if authorization and authorization.startswith("Basic "):
        try:
            decoded = base64.b64decode(authorization[6:]).decode("latin-1")
            password = decoded.partition(":")[2]
            ok = secrets.compare_digest(
                password.encode(), settings.UPLOAD_PASSWORD.encode()
            )
        except Exception:
            pass
    if not ok:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Falsches Passwort")


class LocateRequest(BaseModel):
    photo_id: int
    lat: float
    lon: float


@router.post("")
async def upload_photo(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    _: None = Depends(_check_auth),
):
    settings = get_settings()

    filename = file.filename or "upload.jpg"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Dateiformat nicht unterstützt: {ext}")

    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)

    dest = os.path.join(settings.UPLOAD_DIR, filename)
    if os.path.exists(dest):
        base, ext = os.path.splitext(filename)
        filename = f"{base}_{uuid.uuid4().hex[:8]}{ext}"
        dest = os.path.join(settings.UPLOAD_DIR, filename)

    size = 0
    try:
        with open(dest, "wb") as out:
            while chunk := await file.read(65_536):
                size += len(chunk)
                if size > _MAX_SIZE:
                    out.close()
                    os.unlink(dest)
                    raise HTTPException(status_code=413, detail="Datei zu groß (max. 50 MB)")
                out.write(chunk)
    except HTTPException:
        raise
    except Exception as exc:
        if os.path.exists(dest):
            os.unlink(dest)
        raise HTTPException(status_code=500, detail=str(exc))

    loop = asyncio.get_running_loop()
    meta = await loop.run_in_executor(None, _extract_gps, dest)

    if not meta:
        # No GPS — move to pending_location/, create thumbnail, register in DB
        pending_dir = settings.PENDING_LOCATION_DIR
        os.makedirs(pending_dir, exist_ok=True)
        pending_dest = os.path.join(pending_dir, filename)
        shutil.move(dest, pending_dest)

        thumb = await loop.run_in_executor(
            None, _create_thumbnail, pending_dest, settings.THUMBNAILS_DIR, settings.THUMB_SIZE
        )

        db = SessionLocal()
        try:
            photo = Photo(
                filename=filename,
                path=pending_dest,
                thumb_path=thumb,
                lat=None,
                lon=None,
                datetime_original="",
                tags=[],
                status=PhotoStatus.pending,
            )
            db.add(photo)
            db.commit()
            db.refresh(photo)
            photo_id = photo.id
        finally:
            db.close()

        return {
            "filename": filename,
            "size": size,
            "needs_location": True,
            "photo_id": photo_id,
            "message": "Kein GPS-Standort gefunden — bitte Standort manuell setzen",
        }

    background_tasks.add_task(_process_notify, dest)
    return {
        "filename": filename,
        "size": size,
        "needs_location": False,
        "message": "Upload wird verarbeitet",
    }


@router.post("/locate")
async def locate_photo(
    body: LocateRequest,
    background_tasks: BackgroundTasks,
    _: None = Depends(_check_auth),
):
    """Set manual coordinates for a photo that was uploaded without GPS."""
    loop = asyncio.get_running_loop()
    filename = await loop.run_in_executor(None, register_location, body.photo_id, body.lat, body.lon)
    if not filename:
        raise HTTPException(status_code=404, detail="Foto nicht gefunden oder Datei fehlt")
    background_tasks.add_task(send_new_photo_notification, filename)
    return {"message": "Standort gespeichert"}
