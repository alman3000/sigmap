import os
import shutil
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import get_settings
from database import get_db
from deps import get_current_admin
from models import Photo, PhotoStatus
from services.processing import _create_thumbnail, regenerate_geojson
from tags import VALID_TAGS

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ── Pydantic schemas ─────────────────────────────────────────────────────────

class TagUpdate(BaseModel):
    tags: List[str]


class StatusUpdate(BaseModel):
    status: PhotoStatus


class GeoUpdate(BaseModel):
    lat: float
    lon: float


# ── helpers ──────────────────────────────────────────────────────────────────

def _photo_dict(p: Photo) -> dict:
    return {
        "id": p.id,
        "filename": p.filename,
        "thumb": f"thumbnails/{p.filename}" if p.thumb_path else None,
        "lat": p.lat,
        "lon": p.lon,
        "datetime": p.datetime_original,
        "tags": p.tags or [],
        "status": p.status.value,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


# ── routes ───────────────────────────────────────────────────────────────────

@router.get("/stats")
def get_stats(
    db: Session = Depends(get_db),
    _: str = Depends(get_current_admin),
):
    return {
        "total":    db.query(Photo).count(),
        "pending":  db.query(Photo).filter(Photo.status == PhotoStatus.pending).count(),
        "approved": db.query(Photo).filter(Photo.status == PhotoStatus.approved).count(),
        "rejected": db.query(Photo).filter(Photo.status == PhotoStatus.rejected).count(),
    }


@router.get("/photos")
def list_photos(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    _: str = Depends(get_current_admin),
):
    q = db.query(Photo)
    if status:
        try:
            q = q.filter(Photo.status == PhotoStatus(status))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown status: {status}")

    total = q.count()
    photos = q.order_by(Photo.created_at.desc()).offset(offset).limit(limit).all()
    return {"total": total, "photos": [_photo_dict(p) for p in photos]}


@router.patch("/photos/{photo_id}/tags")
def update_tags(
    photo_id: int,
    body: TagUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: str = Depends(get_current_admin),
):
    invalid = [t for t in body.tags if t not in VALID_TAGS]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Invalid tags: {invalid}")

    photo = db.get(Photo, photo_id)
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")

    photo.tags = body.tags
    db.commit()
    # Regenerate GeoJSON so tags appear on the map immediately
    background_tasks.add_task(regenerate_geojson)
    return {"id": photo_id, "tags": photo.tags}


@router.patch("/photos/{photo_id}/status")
def update_status(
    photo_id: int,
    body: StatusUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: str = Depends(get_current_admin),
):
    photo = db.get(Photo, photo_id)
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")

    photo.status = body.status
    db.commit()
    background_tasks.add_task(regenerate_geojson)
    return {"id": photo_id, "status": photo.status.value}


@router.patch("/photos/{photo_id}/location")
def update_location(
    photo_id: int,
    body: GeoUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: str = Depends(get_current_admin),
):
    settings = get_settings()
    photo = db.get(Photo, photo_id)
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")

    # If file is still in pending_location, move it to photos/ and create thumbnail
    if photo.path and settings.PENDING_LOCATION_DIR in photo.path:
        filename = os.path.basename(photo.path)
        dest = os.path.join(settings.PHOTOS_DIR, filename)
        os.makedirs(settings.PHOTOS_DIR, exist_ok=True)
        if os.path.exists(photo.path) and not os.path.exists(dest):
            shutil.move(photo.path, dest)
        if os.path.exists(dest):
            thumb = _create_thumbnail(dest, settings.THUMBNAILS_DIR, settings.THUMB_SIZE)
            photo.path = dest
            if thumb:
                photo.thumb_path = thumb

    photo.lat = body.lat
    photo.lon = body.lon
    db.commit()

    if photo.status == PhotoStatus.approved:
        background_tasks.add_task(regenerate_geojson)

    return {"id": photo_id, "lat": body.lat, "lon": body.lon}


@router.delete("/photos/{photo_id}")
def delete_photo(
    photo_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: str = Depends(get_current_admin),
):
    photo = db.get(Photo, photo_id)
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")

    for path in (photo.path, photo.thumb_path):
        if path and os.path.exists(path):
            try:
                os.unlink(path)
            except OSError:
                pass

    db.delete(photo)
    db.commit()
    background_tasks.add_task(regenerate_geojson)
    return {"id": photo_id, "deleted": True}


@router.post("/regenerate")
def trigger_regenerate(
    background_tasks: BackgroundTasks,
    _: str = Depends(get_current_admin),
):
    background_tasks.add_task(regenerate_geojson)
    return {"message": "GeoJSON regeneration queued"}


@router.post("/regenerate-thumbnails")
def trigger_regenerate_thumbnails(
    background_tasks: BackgroundTasks,
    _: str = Depends(get_current_admin),
):
    """Delete and recreate all thumbnails with correct EXIF orientation."""
    background_tasks.add_task(_regenerate_all_thumbnails)
    return {"message": "Thumbnail regeneration queued"}


def _regenerate_all_thumbnails() -> None:
    from database import SessionLocal
    settings = get_settings()
    db = SessionLocal()
    try:
        photos = db.query(Photo).filter(Photo.path.isnot(None)).all()
        ok = 0
        for photo in photos:
            if not photo.path or not os.path.exists(photo.path):
                continue
            thumb = os.path.join(settings.THUMBNAILS_DIR, photo.filename)
            if os.path.exists(thumb):
                os.unlink(thumb)
            new_thumb = _create_thumbnail(photo.path, settings.THUMBNAILS_DIR, settings.THUMB_SIZE)
            if new_thumb:
                photo.thumb_path = new_thumb
                ok += 1
        db.commit()
        import logging
        logging.getLogger(__name__).info("Thumbnails regenerated: %d", ok)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error("Thumbnail regeneration failed: %s", exc)
        db.rollback()
    finally:
        db.close()
