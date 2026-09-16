import hashlib
import secrets
import time
from urllib.parse import urlparse
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select, text
from .config import settings
from .db import session
from .models import LoginAttempt, LoginSession, Membership, Profile, User

hasher = PasswordHasher()
DUMMY_HASH = hasher.hash("not-a-real-account-password")


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def require_user(request: Request, db=Depends(session)):
    token = request.cookies.get("session", "")
    login = db.get(LoginSession, digest(token)) if token else None
    user = db.get(User, login.user_id) if login and login.expires > time.time() else None
    if not user or not user.active:
        raise HTTPException(303, headers={"Location": "/login"})
    request.state.login, request.state.user = login, user
    return user


async def require_csrf(request: Request, user=Depends(require_user)):
    token = request.headers.get("x-csrf-token")
    if token is None and request.headers.get("content-type", "").startswith("application/x-www-form-urlencoded"):
        token = (await request.form()).get("csrf", "")
    if not secrets.compare_digest(str(token or ""), request.state.login.csrf):
        raise HTTPException(403, "Invalid CSRF token")
    check_origin(request)
    return user


def check_origin(request):
    origin = request.headers.get("origin")
    if origin != settings().app_url.rstrip("/"):
        raise HTTPException(403, "Invalid request origin")


def require_admin(user):
    if not user.admin:
        raise HTTPException(403, "Administrator required")


def profile_access(db, user, pid):
    profile = db.get(Profile, pid)
    if not profile or (not user.admin and not db.get(Membership, (user.id, pid))):
        raise HTTPException(404, "Profile not found")
    return profile


def accessible_profiles(db, user):
    query = select(Profile)
    if not user.admin:
        query = query.join(Membership, Membership.profile_id == Profile.id).where(Membership.user_id == user.id)
    return list(db.scalars(query.order_by(Profile.name)))


def rate_limit_login(db, email, ip):
    # Independent account AND source limits survive restarts and multiple API processes.
    for value in ("ip:" + ip, "email:" + email):
        key = digest(value)
        if db.bind.dialect.name == "postgresql":
            from .worker import lock_number

            db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_number("login:" + key)})
        row = db.get(LoginAttempt, key)
        if not row:
            row = LoginAttempt(key=key, count=0, since=time.time())
            db.add(row)
        if row.since < time.time() - 900:
            row.since, row.count = time.time(), 0
        if row.count >= (10 if value.startswith("email:") else 50):
            db.commit()
            raise HTTPException(429, "Too many attempts. Try again in 15 minutes.")
        row.count += 1
    db.commit()


def authenticate(db, email, password):
    user = db.scalar(select(User).where(User.email == email))
    try:
        hasher.verify(user.password_hash if user else DUMMY_HASH, password)
    except VerificationError:
        return None
    return user if user and user.active else None


def login_cookie(response, token):
    response.set_cookie(
        "session",
        token,
        httponly=True,
        secure=settings().cookie_secure,
        samesite="strict",
        max_age=settings().session_hours * 3600,
        path="/",
    )


def trusted_hosts():
    return [urlparse(settings().app_url).hostname or "localhost"] + (
        ["testserver", "127.0.0.1"] if settings().environment != "production" else []
    )
