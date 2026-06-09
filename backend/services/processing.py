"""
Background processing service:
  - process_uploaded_file   — extract GPS, create thumbnail, store in DB
  - regenerate_geojson      — rebuild photos.geojson from approved DB records
  - cleanup_orphaned_pending — remove pending-location photos older than N days
  - import_existing_geojson — one-time startup import of pre-existing approved photos
"""

import json
import logging
import os
import shutil
import subprocess
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps

from config import get_settings
from database import SessionLocal
from models import Photo, PhotoStatus

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".heic", ".heif"}


# ── GPS / EXIF extraction ────────────────────────────────────────────────────

def _extract_gps(filepath: str) -> Optional[dict]:
    cmd = [
        "exiftool", "-n", "-fast2",
        "-if", "$GPSLatitude",
        "-gpslatitude", "-gpslongitude",
        "-datetimeoriginal", "-filename", "-SourceFile",
        "-charset", "UTF8",
        "-json", filepath,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            if data and data[0].get("GPSLatitude") and data[0].get("GPSLongitude"):
                return data[0]
    except Exception as exc:
        logger.warning("exiftool failed for %s: %s", filepath, exc)
    return None


# ── EXIF orientation normaliser ──────────────────────────────────────────────

def _strip_exif_orientation(filepath: str) -> None:
    """Reset EXIF Orientation to 1 (no rotation) without re-encoding the image.
    Thumbnails are saved by Pillow without EXIF, so they always display as raw
    pixels. Resetting the original's orientation tag ensures both render the same."""
    try:
        subprocess.run(
            ["exiftool", "-n", "-Orientation=1", "-overwrite_original", filepath],
            capture_output=True, timeout=30, check=False,
        )
    except Exception as exc:
        logger.warning("EXIF orientation strip failed for %s: %s", filepath, exc)


# ── thumbnail creation ───────────────────────────────────────────────────────

def _create_thumbnail(photo_path: str, thumb_dir: str, thumb_size: int) -> Optional[str]:
    filename = os.path.basename(photo_path)
    os.makedirs(thumb_dir, exist_ok=True)
    thumb_path = os.path.join(thumb_dir, filename)
    if os.path.exists(thumb_path):
        return thumb_path
    try:
        with Image.open(photo_path) as img:
            img = ImageOps.exif_transpose(img)  # bake EXIF rotation into pixels
            img.thumbnail((thumb_size, thumb_size), Image.Resampling.LANCZOS)
            img.save(thumb_path, quality=85, optimize=True)
        return thumb_path
    except Exception as exc:
        logger.error("Thumbnail creation failed for %s: %s", photo_path, exc)
        return None


# ── main processing pipeline ─────────────────────────────────────────────────

def process_uploaded_file(filepath: str, tags: list = None) -> bool:
    """Move file from uploads/ → photos/, create thumbnail, register in DB."""
    settings = get_settings()
    filename = os.path.basename(filepath)

    meta = _extract_gps(filepath)
    if not meta:
        logger.warning("No GPS data in %s — removed from uploads", filename)
        try:
            os.unlink(filepath)
        except OSError:
            pass
        return False

    dest_path = os.path.join(settings.PHOTOS_DIR, filename)
    os.makedirs(settings.PHOTOS_DIR, exist_ok=True)
    if not os.path.exists(dest_path):
        shutil.move(filepath, dest_path)

    thumb_path = _create_thumbnail(dest_path, settings.THUMBNAILS_DIR, settings.THUMB_SIZE)

    lat = float(meta.get("GPSLatitude", 0))
    lon = float(meta.get("GPSLongitude", 0))

    db = SessionLocal()
    try:
        if db.query(Photo).filter(Photo.filename == filename).first():
            logger.info("Photo already in DB: %s", filename)
            return True
        photo = Photo(
            filename=filename,
            path=dest_path,
            thumb_path=thumb_path,
            lat=lat,
            lon=lon,
            datetime_original=meta.get("DateTimeOriginal", ""),
            tags=tags or [],
            status=PhotoStatus.pending,
        )
        db.add(photo)
        db.commit()
        logger.info("Registered new photo: %s", filename)
        return True
    except Exception as exc:
        logger.error("DB error for %s: %s", filename, exc)
        db.rollback()
        return False
    finally:
        db.close()


# ── manual location registration ─────────────────────────────────────────────

def register_location(photo_id: int, lat: float, lon: float) -> Optional[str]:
    """Move a pending_location file to photos/, create thumbnail, set coordinates in DB.
    Returns the filename on success, None on failure."""
    settings = get_settings()
    db = SessionLocal()
    try:
        photo = db.get(Photo, photo_id)
        if not photo:
            return False

        src = photo.path
        filename = os.path.basename(src)
        dest = os.path.join(settings.PHOTOS_DIR, filename)

        os.makedirs(settings.PHOTOS_DIR, exist_ok=True)
        if os.path.exists(src) and not os.path.exists(dest):
            shutil.move(src, dest)
        elif not os.path.exists(dest):
            logger.warning("Source file missing for photo %d: %s", photo_id, src)
            return False

        thumb = _create_thumbnail(dest, settings.THUMBNAILS_DIR, settings.THUMB_SIZE)

        photo.lat = lat
        photo.lon = lon
        photo.path = dest
        if thumb:
            photo.thumb_path = thumb
        db.commit()
        logger.info("Location registered for photo %d: %.6f, %.6f", photo_id, lat, lon)
        return photo.filename
    except Exception as exc:
        logger.error("register_location failed for photo %d: %s", photo_id, exc)
        db.rollback()
        return None
    finally:
        db.close()


# ── GeoJSON regeneration ─────────────────────────────────────────────────────

_geojson_lock = threading.Lock()


def regenerate_geojson() -> int:
    """Write approved photos (with tags) to photos.geojson atomically."""
    with _geojson_lock:
        return _regenerate_geojson_locked()


def _regenerate_geojson_locked() -> int:
    settings = get_settings()
    db = SessionLocal()
    try:
        photos = db.query(Photo).filter(Photo.status == PhotoStatus.approved).all()

        features = []
        for p in photos:
            if p.lat is None or p.lon is None:
                continue
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [p.lon, p.lat]},
                "properties": {
                    "filename": p.filename,
                    "datetime": p.datetime_original or "",
                    "thumb": f"thumbnails/{p.filename}",
                    "original": f"photos/{p.filename}",
                    "tags": p.tags or [],
                },
            })

        geojson = {"type": "FeatureCollection", "features": features}

        # Write to temp first, then copy over destination.
        # os.replace() (atomic rename) fails on Docker bind-mounts on Windows
        # (EBUSY), so we copy + unlink instead.
        tmp = settings.GEOJSON_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(geojson, f, ensure_ascii=False)
        shutil.copy2(tmp, settings.GEOJSON_PATH)
        os.unlink(tmp)

        logger.info("GeoJSON regenerated: %d approved photos", len(features))
        return len(features)
    finally:
        db.close()


# ── startup import from existing GeoJSON ─────────────────────────────────────

def import_existing_geojson() -> None:
    """On first start, import all features from existing GeoJSON as approved photos."""
    settings = get_settings()
    if not os.path.exists(settings.GEOJSON_PATH):
        return

    db = SessionLocal()
    try:
        if db.query(Photo).count() > 0:
            return  # Already populated

        with open(settings.GEOJSON_PATH, "r", encoding="utf-8") as f:
            geojson = json.load(f)

        imported = 0
        for feature in geojson.get("features", []):
            props = feature.get("properties", {})
            coords = (feature.get("geometry") or {}).get("coordinates", [None, None])
            filename = props.get("filename")
            if not filename or coords[0] is None:
                continue
            db.add(Photo(
                filename=filename,
                path=os.path.join(settings.PHOTOS_DIR, filename),
                thumb_path=os.path.join(settings.THUMBNAILS_DIR, filename),
                lat=float(coords[1]),
                lon=float(coords[0]),
                datetime_original=props.get("datetime", ""),
                tags=props.get("tags", []),
                status=PhotoStatus.approved,
            ))
            imported += 1

        db.commit()
        logger.info("Imported %d existing photos from GeoJSON as approved", imported)
    except Exception as exc:
        logger.error("Failed to import existing GeoJSON: %s", exc)
        db.rollback()
    finally:
        db.close()


# ── orphaned-pending cleanup ─────────────────────────────────────────────────

def cleanup_orphaned_pending(max_age_days: int = 7) -> int:
    """Delete pending-location photos with no coordinates older than max_age_days."""
    cutoff = datetime.utcnow() - timedelta(days=max_age_days)
    db = SessionLocal()
    try:
        stale = (
            db.query(Photo)
            .filter(
                Photo.status == PhotoStatus.pending,
                Photo.lat.is_(None),
                Photo.created_at < cutoff,
            )
            .all()
        )
        count = 0
        for photo in stale:
            for path in (photo.path, photo.thumb_path):
                if path and os.path.exists(path):
                    try:
                        os.unlink(path)
                    except OSError:
                        pass
            db.delete(photo)
            count += 1
        db.commit()
        if count:
            logger.info("Cleaned up %d orphaned pending-location photos", count)
        return count
    except Exception as exc:
        logger.error("cleanup_orphaned_pending failed: %s", exc)
        db.rollback()
        return 0
    finally:
        db.close()
