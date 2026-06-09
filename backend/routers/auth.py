import logging
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import get_settings
from database import get_db
from models import MagicLinkToken
from services.mail import send_magic_link_email

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger(__name__)


class EmailRequest(BaseModel):
    email: str


@router.post("/request")
def request_magic_link(req: EmailRequest, db: Session = Depends(get_db)):
    """Send a magic-link login email. Always returns 200 to avoid email enumeration."""
    settings = get_settings()
    email = req.email.strip().lower()

    if email in settings.admin_email_list:
        # Invalidate any unused tokens for this address
        db.query(MagicLinkToken).filter(
            MagicLinkToken.email == email,
            MagicLinkToken.used_at.is_(None),
        ).delete(synchronize_session=False)

        token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(minutes=settings.MAGIC_LINK_EXPIRE_MINUTES)
        db.add(MagicLinkToken(email=email, token=token, expires_at=expires_at))
        db.commit()

        magic_link = f"{settings.APP_URL}/api/auth/verify?token={token}"
        logger.info("Magic link requested for %s", email)
        try:
            send_magic_link_email(email, magic_link)
        except Exception as exc:
            # SMTP failure must not lock admins out — link is still valid
            logger.warning("SMTP failed (%s) — use the link above to log in", exc)

    return {"message": "Falls diese Adresse berechtigt ist, erhältst du einen Login-Link."}


@router.get("/verify")
def verify_magic_link(token: str, db: Session = Depends(get_db)):
    """Validate token, create session cookie, redirect to admin panel."""
    settings = get_settings()

    db_token = (
        db.query(MagicLinkToken)
        .filter(MagicLinkToken.token == token, MagicLinkToken.used_at.is_(None))
        .first()
    )
    if not db_token or datetime.utcnow() > db_token.expires_at:
        raise HTTPException(status_code=400, detail="Ungültiger oder abgelaufener Link")

    db_token.used_at = datetime.utcnow()
    db.commit()

    expire = datetime.utcnow() + timedelta(hours=settings.SESSION_EXPIRE_HOURS)
    session_jwt = jwt.encode(
        {"sub": db_token.email, "exp": expire},
        settings.SECRET_KEY,
        algorithm="HS256",
    )

    resp = RedirectResponse(url="/admin.html", status_code=302)
    resp.set_cookie(
        key="session",
        value=session_jwt,
        httponly=True,
        secure=settings.APP_URL.startswith("https"),
        samesite="lax",
        max_age=settings.SESSION_EXPIRE_HOURS * 3600,
    )
    return resp


@router.get("/me")
def get_me(session: str | None = Cookie(default=None)):
    """Return current admin email or 401."""
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated")
    settings = get_settings()
    try:
        payload = jwt.decode(session, settings.SECRET_KEY, algorithms=["HS256"])
        return {"email": payload.get("sub"), "authenticated": True}
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid session")


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("session")
    return {"message": "Logged out"}
