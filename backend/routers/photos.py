import json as _json

from fastapi import APIRouter, Depends, Query
from sqlalchemy import asc, cast, desc, func, nulls_last, or_
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from database import get_db
from models import Photo, PhotoStatus
from tags import VALID_TAGS

router = APIRouter(prefix="/api/photos", tags=["photos"])


@router.get("")
def list_photos(
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    tags: str = Query(""),
    sort: str = Query("desc"),
    db: Session = Depends(get_db),
):
    q = db.query(Photo).filter(Photo.status == PhotoStatus.approved)

    tag_list = [t for t in (t.strip() for t in tags.split(",")) if t in VALID_TAGS]
    if tag_list:
        q = q.filter(or_(*[
            Photo.tags.cast(JSONB).op("@>")(cast(_json.dumps([t]), JSONB))
            for t in tag_list
        ]))

    total = q.count()

    date_col = func.nullif(Photo.datetime_original, "")
    order_fn = asc if sort == "asc" else desc
    q = q.order_by(nulls_last(order_fn(date_col)), order_fn(Photo.created_at))

    photos = q.offset(offset).limit(limit).all()

    return {
        "total": total,
        "photos": [
            {
                "filename": p.filename,
                "thumb": f"thumbnails/{p.filename}",
                "original": f"photos/{p.filename}",
                "tags": p.tags or [],
                "datetime": p.datetime_original or "",
                "lat": p.lat,
                "lon": p.lon,
            }
            for p in photos
        ],
    }
