import logging
import secrets
import time
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .auth import (
    accessible_profiles,
    authenticate,
    check_origin,
    digest,
    hasher,
    login_cookie,
    profile_access,
    rate_limit_login,
    require_admin,
    require_csrf,
    require_user,
    trusted_hosts,
)
from .config import settings
from .explanations import explain_reason
from .db import session
from .models import (
    Audit,
    Connection,
    Conversation,
    Draft,
    Heartbeat,
    Job,
    LoginSession,
    Membership,
    Memory,
    Message,
    Profile,
    User,
)
from .schemas import ProfileConfig, ProfileInput
from .services import audit, eligibility, enqueue, invalidate
from .worker import lock_number

ROOT = Path(__file__).parent
app = FastAPI(title="PersonaAI · Telegram Business", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=trusted_hosts())
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")
templates.env.filters["date"] = lambda value: time.strftime("%d %b %H:%M UTC", time.gmtime(value)) if value else "—"
templates.env.filters["explain"] = explain_reason
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


@app.middleware("http")
async def security(request, call_next):
    # Bound streaming bodies as well as Content-Length, including chunked requests.
    # Multipart uploads are exempt: they are spooled by the upload route, which
    # enforces its own per-file size limit.
    content_type = request.headers.get("content-type", "")
    if request.method in ("POST", "PUT", "PATCH") and not content_type.startswith("multipart/form-data"):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 262144:
                return JSONResponse({"detail": "Request too large"}, 413)
        request._body = bytes(body)
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "no-store"
    if settings().cookie_secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


def render(request, name, **context):
    return templates.TemplateResponse(
        request=request,
        name=name,
        context={
            "user": getattr(request.state, "user", None),
            "csrf": getattr(getattr(request.state, "login", None), "csrf", ""),
            **context,
        },
    )


def redirect(path):
    return RedirectResponse(path, 303)


def lock(db, cid):
    if db.bind.dialect.name == "postgresql":
        acquired = db.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": lock_number(cid)})
        if not acquired:
            raise HTTPException(409, "This connection is processing a message. Please retry shortly.")
    db.expire_all()


def conversation_access(db, user, pid, cid, mutate=False):
    profile = profile_access(db, user, pid)
    conv = db.scalar(select(Conversation).where(Conversation.id == cid, Conversation.profile_id == pid))
    if not conv:
        raise HTTPException(404, "Conversation not found")
    if mutate:
        lock(db, conv.connection_id)
    return profile, conv


def form_text(form, key, maximum=4000, required=True, trim=True):
    value = str(form.get(key, ""))
    if trim:
        value = value.strip()
    if (required and not value) or len(value) > maximum:
        raise HTTPException(422, f"Invalid {key}")
    return value


@app.get("/health/live")
def live():
    return {"status": "ok"}


@app.get("/health/ready")
def ready(db=Depends(session)):
    try:
        db.execute(text("SELECT 1"))
        seen = db.scalar(select(func.max(Heartbeat.seen)))
        healthy = bool(seen and seen > time.time() - 660)
        return JSONResponse(
            {"status": "ready" if healthy else "worker_unavailable"}, status_code=200 if healthy else 503
        )
    except Exception:
        return JSONResponse({"status": "database_unavailable"}, 503)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    token = secrets.token_urlsafe(32)
    response = render(request, "login.html", login_csrf=token)
    response.set_cookie(
        "login_csrf", token, httponly=True, secure=settings().cookie_secure, samesite="strict", max_age=900
    )
    return response


@app.post("/login")
async def login(request: Request, db=Depends(session)):
    check_origin(request)
    form = await request.form()
    token = str(form.get("csrf", ""))
    if not token or not secrets.compare_digest(token, request.cookies.get("login_csrf", "")):
        raise HTTPException(403, "Invalid CSRF token")
    email = form_text(form, "email", 254).lower()
    password = form_text(form, "password", 1024, trim=False)
    rate_limit_login(db, email, request.client.host if request.client else "unknown")
    user = authenticate(db, email, password)
    if not user:
        response = render(request, "login.html", login_csrf=token, error="Email or password is incorrect.")
        response.status_code = 401
        return response
    session_token = secrets.token_urlsafe(48)
    db.add(
        LoginSession(
            token_hash=digest(session_token),
            user_id=user.id,
            csrf=secrets.token_urlsafe(32),
            expires=time.time() + settings().session_hours * 3600,
        )
    )
    audit(db, user.id, "login")
    db.commit()
    response = redirect("/")
    login_cookie(response, session_token)
    response.delete_cookie("login_csrf")
    return response


@app.post("/logout")
def logout(request: Request, user=Depends(require_csrf), db=Depends(session)):
    login = db.get(LoginSession, digest(request.cookies.get("session", "")))
    if login:
        db.delete(login)
        db.commit()
    response = redirect("/login")
    response.delete_cookie("session")
    return response


@app.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    page: int = Query(1, ge=1, le=10000),
    profile_id: str = "",
    state: str = "",
    user=Depends(require_user),
    db=Depends(session),
):
    profiles = accessible_profiles(db, user)
    ids = [p.id for p in profiles]
    query = select(Conversation).where(Conversation.profile_id.in_(ids))
    if profile_id:
        query = query.where(Conversation.profile_id == profile_id)
    if state:
        query = query.where(Conversation.state == state)
    conversations = list(
        db.scalars(query.order_by(Conversation.updated.desc(), Conversation.id).offset((page - 1) * 40).limit(41))
    )
    has_more = len(conversations) > 40
    conversations = conversations[:40]
    pending = db.scalar(
        select(func.count()).select_from(Draft).where(Draft.profile_id.in_(ids), Draft.status == "pending")
    )
    return render(
        request,
        "dashboard.html",
        profiles=profiles,
        profiles_by_id={p.id: p for p in profiles},
        conversations=conversations,
        pending=pending,
        page=page,
        has_more=has_more,
        selected_profile=profile_id,
        selected_state=state,
        escalations=db.scalar(
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.profile_id.in_(ids), Conversation.state.in_(["escalated", "blocked"]))
        ),
    )


@app.get("/profiles/new", response_class=HTMLResponse)
def profile_new(request: Request, user=Depends(require_user)):
    require_admin(user)
    return render(request, "profile.html", profile=None, config=ProfileConfig().model_dump(), connections=[])


async def read_profile_form(request):
    form = await request.form()
    try:
        return ProfileInput(
            name=form.get("name"),
            owner_telegram_id=form.get("owner_telegram_id"),
            mode=form.get("mode", "approval"),
            enabled=form.get("enabled") == "on",
            lawful_reviewed=form.get("lawful_reviewed") == "on",
            config={key: str(form.get(key, "")) for key in ProfileConfig.model_fields},
        )
    except ValidationError:
        raise HTTPException(422, "Invalid profile settings") from None


@app.post("/profiles/new")
async def profile_create(request: Request, user=Depends(require_csrf), db=Depends(session)):
    require_admin(user)
    data = await read_profile_form(request)
    profile = Profile(**data.model_dump())
    db.add(profile)
    try:
        db.flush()
        # Only exact owner-ID matches can claim orphaned connections. Binding cannot be reassigned.
        for connection in db.scalars(
            select(Connection).where(Connection.owner_id == profile.owner_telegram_id, Connection.profile_id.is_(None))
        ):
            lock(db, connection.id)
            connection.profile_id = profile.id
        audit(db, user.id, "profile_created", profile.id, profile.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This Telegram owner already has a profile") from None
    return redirect(f"/profiles/{profile.id}")


@app.get("/profiles/{pid}", response_class=HTMLResponse)
def profile_page(pid: str, request: Request, user=Depends(require_user), db=Depends(session)):
    from .media import list_files
    profile = profile_access(db, user, pid)
    connections = list(
        db.scalars(select(Connection).where(Connection.profile_id == pid).order_by(Connection.established.desc()))
    )
    return render(
        request,
        "profile.html",
        profile=profile,
        config=ProfileConfig(**profile.config).model_dump(),
        connections=connections,
        media=list_files(pid),
        public_url=settings().app_url.rstrip("/") + f"/p/{pid}",
    )


@app.post("/profiles/{pid}")
async def profile_save(pid: str, request: Request, user=Depends(require_csrf), db=Depends(session)):
    profile = profile_access(db, user, pid)
    data = await read_profile_form(request)
    if data.owner_telegram_id != profile.owner_telegram_id:
        raise HTTPException(409, "Telegram owner bindings are immutable; create a new profile")
    for cid in db.scalars(select(Connection.id).where(Connection.profile_id == pid).order_by(Connection.id)):
        lock(db, cid)
    profile.name, profile.mode = data.name, data.mode
    profile.enabled, profile.lawful_reviewed, profile.config = (
        data.enabled,
        data.lawful_reviewed,
        data.config.model_dump(),
    )
    profile.version += 1
    db.execute(
        update(Draft)
        .where(Draft.profile_id == pid, Draft.status.in_(["pending", "queued"]))
        .values(status="stale", reason="profile_changed")
    )
    audit(db, user.id, "profile_updated", pid, pid)
    db.commit()
    return redirect(f"/profiles/{pid}")


@app.get("/profiles/{pid}/conversations/{cid}", response_class=HTMLResponse)
def conversation_page(
    pid: str,
    cid: str,
    request: Request,
    page: int = Query(1, ge=1, le=10000),
    user=Depends(require_user),
    db=Depends(session),
):
    profile, conv = conversation_access(db, user, pid, cid)
    messages = list(
        db.scalars(
            select(Message)
            .where(Message.profile_id == pid, Message.conversation_id == cid)
            .order_by(Message.created.desc(), Message.telegram_id.desc())
            .offset((page - 1) * 100)
            .limit(101)
        )
    )
    return render(
        request,
        "conversation.html",
        profile=profile,
        conv=conv,
        messages=list(reversed(messages[:100])),
        message_page=page,
        older_messages=len(messages) > 100,
        drafts=list(
            db.scalars(
                select(Draft)
                .where(Draft.profile_id == pid, Draft.conversation_id == cid)
                .order_by(Draft.created.desc())
                .limit(20)
            )
        ),
        memories=list(
            db.scalars(
                select(Memory)
                .where(Memory.profile_id == pid, Memory.conversation_id == cid)
                .order_by(Memory.created.desc())
                .limit(20)
            )
        ),
        connection=db.get(Connection, conv.connection_id),
    )


@app.post("/profiles/{pid}/conversations/{cid}/state")
async def conversation_state(pid: str, cid: str, request: Request, user=Depends(require_csrf), db=Depends(session)):
    profile, conv = conversation_access(db, user, pid, cid, True)
    form = await request.form()
    action = form.get("action")
    note = form_text(form, "note", 1000)
    next_url = str(form.get("next", ""))
    if not (next_url.startswith("/p/") or next_url.startswith("/profiles/")):
        next_url = f"/profiles/{pid}/conversations/{cid}"
    if action not in ("resume", "pause", "block"):
        raise HTTPException(422, "Invalid action")
    if conv.state == "blocked" and action != "block":
        raise HTTPException(409, "Blocked conversations cannot be resumed from the dashboard")
    conv.state = {"resume": "active", "pause": "paused", "block": "blocked"}[action]
    conv.reason = "operator_" + action
    conv.review_note = note
    invalidate(db, conv, "operator_review")
    audit(db, user.id, "conversation_" + action, cid, pid)
    if action == "resume" and profile.mode != "human":
        enqueue(
            db,
            "generate",
            f"generate:{cid}:{conv.revision}",
            conv.connection_id,
            {"profile_id": pid, "conversation_id": cid, "revision": conv.revision},
        )
    db.commit()
    return redirect(next_url)


@app.post("/profiles/{pid}/conversations/{cid}/drafts/{did}")
async def draft_action(pid: str, cid: str, did: str, request: Request, user=Depends(require_csrf), db=Depends(session)):
    profile, conv = conversation_access(db, user, pid, cid, True)
    draft = db.scalar(
        select(Draft).where(Draft.id == did, Draft.profile_id == pid, Draft.conversation_id == cid).with_for_update()
    )
    if not draft:
        raise HTTPException(404, "Draft not found")
    if draft.status != "pending":
        raise HTTPException(409, "This draft is no longer pending")
    form = await request.form()
    action = form.get("action")
    if action == "reject":
        draft.status = "rejected"
    elif action == "approve":
        if draft.revision != conv.revision or draft.profile_version != profile.version:
            raise HTTPException(409, "Draft is stale")
        reason = eligibility(profile, conv, db.get(Connection, conv.connection_id))
        if reason:
            raise HTTPException(409, reason)
        draft.text = form_text(form, "text", 3500)
        draft.status, draft.approved_by = "queued", user.id
        enqueue(
            db,
            "send",
            "send:" + draft.id,
            conv.connection_id,
            {"profile_id": pid, "conversation_id": cid, "draft_id": draft.id},
        )
    else:
        raise HTTPException(422, "Invalid action")
    audit(db, user.id, "draft_" + action, did, pid)
    db.commit()
    return redirect(f"/profiles/{pid}/conversations/{cid}")


@app.post("/profiles/{pid}/conversations/{cid}/reply")
async def manual_reply(pid: str, cid: str, request: Request, user=Depends(require_csrf), db=Depends(session)):
    from .media import save_chat_media
    profile, conv = conversation_access(db, user, pid, cid, True)
    form = await request.form()
    value = str(form.get("text", "")).strip()
    next_url = str(form.get("next", ""))
    if not (next_url.startswith("/p/") or next_url.startswith("/profiles/")):
        next_url = f"/profiles/{pid}/conversations/{cid}"

    def _err(reason):
        return redirect(next_url + ("&" if "?" in next_url else "?") + "error=" + reason)

    reason = eligibility(profile, conv, db.get(Connection, conv.connection_id))
    if reason:
        return _err(reason)
    upload = form.get("file")
    media = []
    if upload is not None and getattr(upload, "filename", ""):
        try:
            media = [save_chat_media(pid, upload.filename, await upload.read())]
        except ValueError:
            return _err("bad_file")
    if len(value) > 3500 or (not value and not media):
        return _err("empty_reply")
    invalidate(db, conv, "manual_reply")
    draft = Draft(
        profile_id=pid,
        conversation_id=cid,
        revision=conv.revision,
        profile_version=profile.version,
        text=value,
        media=media,
        status="queued",
        approved_by=user.id,
    )
    db.add(draft)
    db.flush()
    enqueue(
        db,
        "send",
        "send:" + draft.id,
        conv.connection_id,
        {"profile_id": pid, "conversation_id": cid, "draft_id": draft.id},
    )
    audit(db, user.id, "manual_reply_queued", draft.id, pid)
    db.commit()
    return redirect(next_url)


@app.post("/profiles/{pid}/conversations/{cid}/memory")
async def memory_add(pid: str, cid: str, request: Request, user=Depends(require_csrf), db=Depends(session)):
    _, conv = conversation_access(db, user, pid, cid, True)
    value = form_text(await request.form(), "text", 1000)
    db.add(Memory(profile_id=pid, conversation_id=cid, text=value))
    invalidate(db, conv, "memory_changed")
    audit(db, user.id, "memory_added", cid, pid)
    db.commit()
    return redirect(f"/profiles/{pid}/conversations/{cid}")


@app.post("/profiles/{pid}/conversations/{cid}/memory/{mid}/delete")
def memory_delete(pid: str, cid: str, mid: str, user=Depends(require_csrf), db=Depends(session)):
    _, conv = conversation_access(db, user, pid, cid, True)
    memory = db.scalar(select(Memory).where(Memory.id == mid, Memory.profile_id == pid, Memory.conversation_id == cid))
    if not memory:
        raise HTTPException(404, "Memory not found")
    db.delete(memory)
    invalidate(db, conv, "memory_changed")
    audit(db, user.id, "memory_deleted", mid, pid)
    db.commit()
    return redirect(f"/profiles/{pid}/conversations/{cid}")


@app.get("/operations", response_class=HTMLResponse)
def operations(request: Request, user=Depends(require_user), db=Depends(session)):
    require_admin(user)
    return render(
        request,
        "operations.html",
        jobs=list(
            db.scalars(
                select(Job).where(Job.status.in_(["dead", "queued", "running"])).order_by(Job.created.desc()).limit(100)
            )
        ),
        connections=list(db.scalars(select(Connection).where(Connection.profile_id.is_(None)))),
        users=list(db.scalars(select(User).order_by(User.email))),
        profiles=accessible_profiles(db, user),
        memberships=list(db.execute(select(Membership.user_id, Membership.profile_id))),
        audits=list(db.scalars(select(Audit).order_by(Audit.created.desc()).limit(50))),
    )


@app.post("/operations/users")
async def create_user(request: Request, user=Depends(require_csrf), db=Depends(session)):
    require_admin(user)
    form = await request.form()
    email, password = form_text(form, "email", 254).lower(), form_text(form, "password", 1024, trim=False)
    if "@" not in email or len(password) < 14:
        raise HTTPException(422, "Use a valid email and a password of at least 14 characters")
    member = User(email=email, password_hash=hasher.hash(password), admin=False)
    db.add(member)
    try:
        db.flush()
        audit(db, user.id, "user_created", member.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "User already exists") from None
    return redirect("/operations")


@app.post("/operations/access")
async def update_access(request: Request, user=Depends(require_csrf), db=Depends(session)):
    require_admin(user)
    form = await request.form()
    uid, pid, action = str(form.get("user_id")), str(form.get("profile_id")), str(form.get("action"))
    member, profile = db.get(User, uid), db.get(Profile, pid)
    if not member or not profile or action not in ("grant", "revoke"):
        raise HTTPException(422, "Invalid membership")
    membership = db.get(Membership, (uid, pid))
    if action == "grant" and not membership:
        db.add(Membership(user_id=uid, profile_id=pid))
    if action == "revoke" and membership:
        db.delete(membership)
    audit(db, user.id, "membership_" + action, uid, pid)
    db.commit()
    return redirect("/operations")


@app.post("/operations/jobs/{jid}/retry")
def retry_job(jid: str, user=Depends(require_csrf), db=Depends(session)):
    require_admin(user)
    job = db.get(Job, jid)
    if not job or job.status != "dead":
        raise HTTPException(409, "Only dead jobs can be retried")
    if job.kind == "send":
        raise HTTPException(409, "Send jobs require delivery reconciliation; no blind retries")
    job.status, job.attempts, job.available = "queued", 0, time.time()
    audit(db, user.id, "job_retried", jid)
    db.commit()
    return redirect("/operations")


@app.post("/webhooks/telegram")
async def webhook(request: Request, db=Depends(session)):
    secret = settings().telegram_webhook_secret
    if not secret or not secrets.compare_digest(request.headers.get("x-telegram-bot-api-secret-token", ""), secret):
        raise HTTPException(403, "Invalid webhook secret")
    try:
        payload = await request.json()
        if not isinstance(payload, dict) or type(payload.get("update_id")) is not int or payload["update_id"] < 0:
            raise ValueError()
        kinds = [
            key
            for key in (
                "business_connection",
                "business_message",
                "edited_business_message",
                "deleted_business_messages",
            )
            if key in payload
        ]
        if not kinds:
            return {"ok": True}
        if len(kinds) != 1:
            raise ValueError()
        kind, data = kinds[0], payload[kinds[0]]
        cid = data["id"] if kind == "business_connection" else data["business_connection_id"]
        if not isinstance(cid, str) or not 1 <= len(cid) <= 256:
            raise ValueError()
        if kind == "business_connection":
            if (
                type(data["is_enabled"]) is not bool
                or type(data["user"]["id"]) is not int
                or type(data["user_chat_id"]) is not int
            ):
                raise ValueError()
        else:
            if type(data["chat"]["id"]) is not int or not isinstance(data["chat"]["type"], str):
                raise ValueError()
            if kind == "deleted_business_messages":
                if (
                    not isinstance(data["message_ids"], list)
                    or len(data["message_ids"]) > 1000
                    or any(type(x) is not int for x in data["message_ids"])
                ):
                    raise ValueError()
            elif type(data["message_id"]) is not int or type(data["date"]) is not int:
                raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise HTTPException(422, "Malformed update") from None
    db.add(Job(kind="update", dedupe=f"update:{payload['update_id']}", connection_id=cid, payload=payload))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if not db.scalar(select(Job.id).where(Job.dedupe == f"update:{payload['update_id']}")):
            raise HTTPException(503, "Inbox persistence failed") from None
    return {"ok": True}


@app.get("/profiles/{pid}/card", response_class=HTMLResponse)
def profile_card(pid, request: Request, user=Depends(require_user), db=Depends(session)):
    from .media import list_files
    from .schemas import ProfileConfig
    profile = profile_access(db, user, pid)
    return render(request, "card.html", profile=profile, config=ProfileConfig(**profile.config).model_dump(), media=list_files(pid))

@app.post("/profiles/{pid}/media")
async def profile_media(pid, request: Request, user=Depends(require_csrf), db=Depends(session)):
    from .media import save_upload
    profile_access(db, user, pid)
    form = await request.form()
    upload = form.get("file")
    data = await upload.read() if upload is not None else b""
    name = getattr(upload, "filename", "") or "file.jpg"
    try:
        save_upload(pid, name, data)
    except ValueError:
        raise HTTPException(400, "bad file")
    return redirect("/profiles/" + str(pid))

@app.get("/media/{pid}/{name}")
def media_file(pid, name, user=Depends(require_user), db=Depends(session)):
    from .media import resolve
    profile_access(db, user, pid)
    path = resolve(pid, name)
    if path is None:
        raise HTTPException(404)
    return FileResponse(path)


@app.get("/media/{pid}/chat/{name}")
def chat_media(pid, name, user=Depends(require_user), db=Depends(session)):
    from .media import resolve_chat
    profile_access(db, user, pid)
    path = resolve_chat(pid, name)
    if path is None:
        raise HTTPException(404)
    return FileResponse(path)


@app.get("/p/{pid}", response_class=HTMLResponse)
def persona_page(pid: str, request: Request, cid: str = "", error: str = "", user=Depends(require_user), db=Depends(session)):
    profile = profile_access(db, user, pid)
    conversations = list(
        db.scalars(
            select(Conversation)
            .where(Conversation.profile_id == pid)
            .order_by(Conversation.updated.desc())
        )
    )
    conv, messages, connection = None, [], None
    if conversations:
        selected = cid or conversations[0].id
        conv = next((c for c in conversations if c.id == selected), conversations[0])
        messages = list(
            db.scalars(
                select(Message)
                .where(Message.profile_id == pid, Message.conversation_id == conv.id)
                .order_by(Message.created.desc(), Message.telegram_id.desc())
                .limit(100)
            )
        )
        messages = list(reversed(messages))
        connection = db.get(Connection, conv.connection_id)
    from .media import list_files
    from .schemas import ProfileConfig
    now = time.time()
    stories = []
    for c in conversations:
        unanswered = c.last_incoming > c.last_sent
        wait = (now - c.last_incoming) / 60 if unanswered else 0
        stage = c.state if c.state in ("blocked", "escalated", "paused") else ("waiting" if wait > 4 else "active")
        stories.append({
            "id": c.id,
            "client_name": c.client_name,
            "state": c.state,
            "stage": stage,
            "unanswered": 1 if unanswered else 0,
            "last_incoming": c.last_incoming,
        })
    return render(
        request,
        "persona.html",
        profile=profile,
        config=ProfileConfig(**profile.config).model_dump(),
        media=list_files(pid),
        stories=stories,
        conv=conv,
        messages=messages,
        connection=connection,
        error=error,
    )


@app.get("/p/{pid}/suggest")
def suggest_reply(pid: str, cid: str, user=Depends(require_user), db=Depends(session)):
    from .ai import AI
    from .services import context_for
    profile = profile_access(db, user, pid)
    conv = db.scalar(select(Conversation).where(Conversation.id == cid, Conversation.profile_id == pid))
    if not conv:
        raise HTTPException(404, "Not found")
    try:
        decision = AI().decide(context_for(db, profile, conv))
        text = (decision.reply or "").strip()
    except Exception:
        text = ""
    return JSONResponse({"text": text})
