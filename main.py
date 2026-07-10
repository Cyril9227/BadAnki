from dotenv import load_dotenv
load_dotenv()

# Standard library
import json
import logging
import os
import secrets
import time
from collections import deque
from datetime import datetime
from threading import Lock
from typing import Optional
import uuid
from urllib.parse import quote
import posixpath

# Third-party
import frontmatter
from google import genai
import httpx
import psycopg2
import anthropic
from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from supabase import create_client, Client, ClientOptions
from jose import jwt
from pydantic import BaseModel, Field
from telegram import Update
from supabase_auth.errors import AuthApiError

# Local application
import crud
from bot import get_bot_application
from render_auth import make_telegram_link_token, verify_render_request
from database import get_db_connection, release_db_connection
from scheduler import run_scheduler
from parsing import normalize_cards, robust_json_loads, sanitize_tags
from middleware import CSRFMiddleware, SecurityHeadersMiddleware


# --- Supabase & JWT Configuration ---
def _clean_env_value(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1].strip()
    return value or None

SECRET_KEY = _clean_env_value("SECRET_KEY")
SCHEDULER_SECRET = _clean_env_value("SCHEDULER_SECRET")
TELEGRAM_WEBHOOK_SECRET = _clean_env_value("TELEGRAM_WEBHOOK_SECRET")
TELEGRAM_BOT_USERNAME = _clean_env_value("TELEGRAM_BOT_USERNAME")
SUPABASE_URL = _clean_env_value("SUPABASE_URL")
SUPABASE_KEY_SOURCE = "SUPABASE_ANON_KEY" if _clean_env_value("SUPABASE_ANON_KEY") else "SUPABASE_KEY"
SUPABASE_KEY = _clean_env_value("SUPABASE_ANON_KEY") or _clean_env_value("SUPABASE_KEY")
IS_PRODUCTION = os.environ.get("ENVIRONMENT") == "production"

if not all([SECRET_KEY, SCHEDULER_SECRET, SUPABASE_URL, SUPABASE_KEY]):
    raise ValueError("One or more critical environment variables are not set.")

def _get_unverified_supabase_role(key: str | None) -> str | None:
    if not key:
        return None
    try:
        return jwt.get_unverified_claims(key).get("role")
    except Exception:
        return None

if SUPABASE_KEY and SUPABASE_KEY.startswith("sb_secret_"):
    raise ValueError(f"{SUPABASE_KEY_SOURCE} must be the public anon/publishable key, not a Supabase secret key.")

if _get_unverified_supabase_role(SUPABASE_KEY) == "service_role":
    raise ValueError(f"{SUPABASE_KEY_SOURCE} must be the public anon key, not the service-role key.")

# This client is shared across all requests, so it must never act on its own
# stored session: sign_in/sign_up would otherwise arm a background refresh
# timer that rotates the *last logged-in user's* refresh token server-side,
# invalidating the copy in that user's cookie (Supabase rotates tokens on use).
supabase: Client = create_client(
    SUPABASE_URL, SUPABASE_KEY, options=ClientOptions(auto_refresh_token=False)
)

MAX_COURSE_PATH_LEN = 512
MAX_COURSE_CONTENT_LEN = 1_000_000
MAX_CARD_QUESTION_LEN = 10_000
MAX_CARD_ANSWER_LEN = 50_000
MAX_GENERATED_CARDS_PER_REQUEST = 100
MAX_SECRET_INPUT_LEN = 512

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


# --- FastAPI App ---
app = FastAPI(
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
)
app.add_middleware(CSRFMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


def should_resolve_user_for_request(request: Request) -> bool:
    # A lone refresh-token cookie still identifies a returning user — the
    # access-token cookie may have expired first (7d vs 30d lifetime).
    if not (request.cookies.get("access_token") or request.cookies.get("refresh_token")):
        return False

    path = request.url.path
    if (
        path == "/health"
        or path == "/logout"
        or path == "/auth/callback"
        or path == "/api/cron"
        or path == "/api/trigger-scheduler"
        or path == "/api/ensure-webhook"
        or path.startswith("/static/")
        or path.startswith("/_vercel/")
        or path.startswith("/webhook/")
        or path.startswith("/render/")
    ):
        return False

    # The password-reset POSTs never read the user and typically arrive with
    # stale cookies (that's why the visitor is there) — don't burn a DB
    # connection and GoTrue round trips on them. The GET still resolves so
    # the navbar renders correctly for logged-in visitors.
    if request.method == "POST" and path.startswith("/auth/reset"):
        return False

    return True


# --- Webhook Endpoint ---
@app.post("/webhook/{secret}")
async def webhook(request: Request, secret: str):
    """
    Handle incoming Telegram webhook updates.
    This is called by Telegram servers when users interact with the bot.
    """
    logger.info("Webhook endpoint was hit!")

    # Refuse webhook requests when no secret is configured; otherwise a guessed
    # fallback value could expose the endpoint.
    if not TELEGRAM_WEBHOOK_SECRET:
        logger.error("TELEGRAM_WEBHOOK_SECRET is not configured; rejecting webhook.")
        raise HTTPException(status_code=503, detail="Webhook is not configured")
    if not secrets.compare_digest(secret, TELEGRAM_WEBHOOK_SECRET):
        logger.warning("Invalid secret received in webhook request.")
        raise HTTPException(status_code=403, detail="Invalid secret")

    bot_app = None
    initialized = False
    try:
        # Get the update data from Telegram
        data = await request.json()
        logger.info("Received Telegram webhook update_id=%s", data.get("update_id"))
        
        # Create a fresh bot application for this request (serverless pattern)
        bot_app = get_bot_application()
        if not bot_app:
            logger.error("Failed to create bot application")
            return Response(status_code=500)
        
        # Initialize the bot for this request
        await bot_app.initialize()
        initialized = True
        
        # Parse the update
        update = Update.de_json(data, bot_app.bot)
        
        # Process the update through the bot's handlers
        await bot_app.process_update(update)
        
        logger.info("Successfully processed webhook update.")
        
        return Response(status_code=200)
        
    except Exception as e:
        logger.error(f"Error processing webhook update: {e}", exc_info=True)
        return Response(status_code=500)
    finally:
        if bot_app and initialized:
            try:
                await bot_app.shutdown()
            except Exception as e:
                logger.warning(f"Error shutting down Telegram bot application: {e}", exc_info=True)


async def _ensure_webhook():
    """Helper function to ensure the Telegram webhook is set correctly."""
    app_url = os.environ.get("APP_URL")
    if not app_url or not TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Webhook is not configured")

    bot_app = get_bot_application()
    if not bot_app:
        raise HTTPException(status_code=503, detail="Telegram bot is not configured")

    initialized = False
    try:
        await bot_app.initialize()
        initialized = True
        webhook_url = f"{app_url.rstrip('/')}/webhook/{TELEGRAM_WEBHOOK_SECRET}"
        redacted_webhook_url = webhook_url.replace(TELEGRAM_WEBHOOK_SECRET, "[redacted]")
        info = await bot_app.bot.get_webhook_info()

        if info.url != webhook_url:
            await bot_app.bot.set_webhook(url=webhook_url, drop_pending_updates=False)
            return {"status": "webhook (re)set", "url": redacted_webhook_url}
        else:
            return {
                "status": "already correct",
                "url": info.url.replace(TELEGRAM_WEBHOOK_SECRET, "[redacted]"),
            }
    finally:
        if bot_app and initialized:
            try:
                await bot_app.shutdown()
            except Exception as e:
                logger.warning(f"Error shutting down Telegram bot application: {e}", exc_info=True)


@app.get("/api/ensure-webhook")
async def ensure_webhook(request: Request):
    submitted_secret = request.headers.get("x-scheduler-secret")
    if not scheduler_secret_is_valid(submitted_secret):
        raise HTTPException(status_code=403, detail="Invalid secret")
    return await _ensure_webhook()



# --- Middleware ---
@app.middleware("http")
async def db_session_middleware(request: Request, call_next):
    """
    Manages the database connection lifecycle for each request.

    Public unauthenticated traffic should not burn a DB connection just to
    serve the home/auth pages, health checks, or static assets. A connection is
    opened lazily when an authenticated cookie needs profile resolution or when
    an endpoint explicitly depends on get_db().
    """
    request.state.db = None
    request.state.user = None
    request.state.auth_resolution_failed = False
    try:
        if should_resolve_user_for_request(request):
            try:
                conn = get_request_db(request)
                request.state.user = await get_current_user(request, conn)
            except Exception as e:
                request.state.auth_resolution_failed = True
                logger.warning("Unable to resolve authenticated user for this request: %s", e, exc_info=True)
        response = await call_next(request)
        # A session refreshed during this request produced new tokens; persist
        # them so the next request skips the refresh round trip.
        refreshed = getattr(request.state, "refreshed_session", None)
        if refreshed:
            _set_session_cookies(response, request, refreshed["access_token"], refreshed["refresh_token"])
        elif getattr(request.state, "clear_refresh_cookie", False):
            response.delete_cookie(
                "refresh_token", path="/",
                secure=should_use_secure_cookies(request), httponly=True, samesite="lax",
            )
        return response
    finally:
        conn = request.state.db
        if conn:
            release_db_connection(conn)

def get_request_db(request: Request) -> psycopg2.extensions.connection:
    conn = getattr(request.state, "db", None)
    if conn is None:
        conn = get_db_connection()
        request.state.db = conn
    return conn

# --- Pydantic Models ---
class User(BaseModel):
    auth_user_id: uuid.UUID
    username: str
    telegram_chat_id: Optional[str] = None
    gemini_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None

class CourseContent(BaseModel):
    path: str = Field(..., min_length=1, max_length=MAX_COURSE_PATH_LEN)
    content: str = Field(..., max_length=MAX_COURSE_CONTENT_LEN)

class CourseItem(BaseModel):
    path: str = Field(..., min_length=1, max_length=MAX_COURSE_PATH_LEN)
    type: str = Field(..., pattern="^(file|folder|directory)$")

class CourseItemRename(BaseModel):
    path: str = Field(..., min_length=1, max_length=MAX_COURSE_PATH_LEN)
    new_path: str = Field(..., min_length=1, max_length=MAX_COURSE_PATH_LEN)
    type: str = Field(..., pattern="^(file|folder|directory)$")

class GeneratedCard(BaseModel):
    question: str = Field(..., min_length=1, max_length=MAX_CARD_QUESTION_LEN)
    answer: str = Field(..., min_length=1, max_length=MAX_CARD_ANSWER_LEN)
    card_type: str = Field(default="basic", pattern="^(basic|cloze)$")

class CourseContentForGeneration(BaseModel):
    content: str = Field(..., max_length=MAX_COURSE_CONTENT_LEN)
    card_type: str = Field(default="basic", pattern="^(basic|cloze)$")

class GeneratedCards(BaseModel):
    cards: list[GeneratedCard] = Field(..., min_length=1, max_length=MAX_GENERATED_CARDS_PER_REQUEST)

class ApiKeys(BaseModel):
    gemini_api_key: str | None = Field(default=None, max_length=MAX_SECRET_INPUT_LEN)
    anthropic_api_key: str | None = Field(default=None, max_length=MAX_SECRET_INPUT_LEN)

class Secrets(BaseModel):
    telegram_token: str | None = Field(default=None, max_length=MAX_SECRET_INPUT_LEN)
    telegram_chat_id: str | None = Field(default=None, max_length=MAX_SECRET_INPUT_LEN)
    scheduler_secret: str | None = Field(default=None, max_length=MAX_SECRET_INPUT_LEN)

class ReviewUndo(BaseModel):
    # Echo of the `previous` scheduling values returned by the rating call.
    # Only ever applied to the caller's own cards, so at worst a user
    # reschedules a card they could rate anyway.
    interval: int = Field(..., ge=0, le=36500)
    ease_factor: float = Field(..., gt=0, le=1000)
    due_date: datetime

class AuthCallback(BaseModel):
    access_token: str = Field(..., min_length=1, max_length=8192)
    refresh_token: str | None = Field(default=None, max_length=8192)

class PasswordResetConfirm(BaseModel):
    access_token: str = Field(..., min_length=1, max_length=8192)
    refresh_token: str | None = Field(default=None, max_length=8192)
    password: str = Field(..., min_length=1, max_length=MAX_SECRET_INPUT_LEN)

# --- Database Dependency ---
def get_db(request: Request):
    """
    FastAPI dependency that retrieves the database connection
    from the request state, managed by the middleware.
    """
    return get_request_db(request)

def should_use_secure_cookies(request: Request) -> bool:
    """Return True when cookies should be marked Secure."""
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    return (
        IS_PRODUCTION
        or request.url.scheme == "https"
        or forwarded_proto.split(",")[0].strip().lower() == "https"
    )

# The Supabase access token itself expires after ~1 hour; the refresh-token
# cookie is what keeps users logged in across the whole cookie lifetime.
ACCESS_COOKIE_MAX_AGE = 3600 * 24 * 7
REFRESH_COOKIE_MAX_AGE = 3600 * 24 * 30


def _set_session_cookies(response: Response, request: Request, access_token: str, refresh_token: Optional[str]) -> None:
    secure_cookie = should_use_secure_cookies(request)
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        max_age=ACCESS_COOKIE_MAX_AGE,
        samesite="lax",
        secure=secure_cookie,
    )
    if refresh_token:
        response.set_cookie(
            key="refresh_token",
            value=refresh_token,
            httponly=True,
            max_age=REFRESH_COOKIE_MAX_AGE,
            samesite="lax",
            secure=secure_cookie,
        )


def set_flash_cookie(response: Response, request: Request, value: str) -> None:
    response.set_cookie(
        key="flash",
        value=value,
        max_age=5,
        samesite="lax",
        secure=should_use_secure_cookies(request),
    )

def scheduler_secret_is_valid(candidate: str | None) -> bool:
    return bool(
        SCHEDULER_SECRET
        and candidate
        and secrets.compare_digest(candidate, SCHEDULER_SECRET)
    )

# --- Authentication ---
# Validating the access token with Supabase is an HTTPS round trip on every
# authenticated request. Cache token -> (auth_user_id, email) for a short TTL
# so warm instances skip that call; profile data is still read from the DB on
# every request so API-key/chat-id changes take effect immediately. A revoked
# token can outlive sign-out by at most the TTL, which is acceptable here
# because logout also clears the cookie. Disabled under tests, where the same
# fake token is reused for different mocked users.
_AUTH_CACHE_TTL_SECS = 0 if os.environ.get("ENVIRONMENT") == "test" else 300
_AUTH_CACHE_MAX_ENTRIES = 1000
_auth_token_cache: dict[str, tuple[float, str, str]] = {}
_auth_token_cache_lock = Lock()


def _auth_cache_get(token: str) -> Optional[tuple[str, str]]:
    if not _AUTH_CACHE_TTL_SECS:
        return None
    now = time.monotonic()
    with _auth_token_cache_lock:
        entry = _auth_token_cache.get(token)
        if entry is None:
            return None
        expires_at, auth_user_id, email = entry
        if expires_at <= now:
            del _auth_token_cache[token]
            return None
        return auth_user_id, email


def _auth_cache_put(token: str, auth_user_id: str, email: str) -> None:
    if not _AUTH_CACHE_TTL_SECS:
        return
    now = time.monotonic()
    with _auth_token_cache_lock:
        if len(_auth_token_cache) >= _AUTH_CACHE_MAX_ENTRIES:
            expired = [key for key, (exp, _, _) in _auth_token_cache.items() if exp <= now]
            for key in expired:
                del _auth_token_cache[key]
            if len(_auth_token_cache) >= _AUTH_CACHE_MAX_ENTRIES:
                _auth_token_cache.clear()
        _auth_token_cache[token] = (now + _AUTH_CACHE_TTL_SECS, auth_user_id, email)


def _refresh_session_sync(refresh_token: str) -> Optional[dict]:
    """Exchange a refresh token for a new session via the GoTrue REST API.

    The shared supabase client keeps session state internally, so it isn't
    safe for refreshing arbitrary users' tokens; the raw endpoint is
    stateless. Returns the session payload, or None on any failure.
    """
    try:
        response = httpx.post(
            f"{SUPABASE_URL}/auth/v1/token",
            params={"grant_type": "refresh_token"},
            json={"refresh_token": refresh_token},
            headers={"apikey": SUPABASE_KEY},
            timeout=10.0,
        )
    except httpx.HTTPError as e:
        logger.warning("Session refresh request failed: %s", e)
        return None
    if response.status_code != 200:
        # Expired/rotated refresh tokens are normal; the user just logs in
        # again. False = definitive rejection (so the caller can drop the dead
        # cookie and stop retrying); None = transient failure, keep the cookie.
        logger.debug("Session refresh rejected with status %s", response.status_code)
        return False if response.status_code in (400, 401, 403, 404) else None
    payload = response.json()
    if not payload.get("access_token") or not (payload.get("user") or {}).get("id"):
        return None
    return payload


def _sign_out_sync(access_token: str) -> None:
    """Revoke the session behind this access token via the GoTrue REST API.

    The shared supabase client's sign_out() operates on the client's own
    internal session, not on an arbitrary user's token, so the raw endpoint
    is used here — same reasoning as _refresh_session_sync. Best-effort: the
    cookies are cleared regardless, a failure only means the refresh token
    stays valid until it expires or rotates.
    """
    try:
        response = httpx.post(
            f"{SUPABASE_URL}/auth/v1/logout",
            params={"scope": "local"},
            headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {access_token}"},
            timeout=10.0,
        )
        if response.status_code >= 400:
            # An expired/invalid token can't revoke anything — that's fine.
            logger.debug("Supabase sign out rejected with status %s", response.status_code)
    except httpx.HTTPError as e:
        logger.warning("Supabase sign out request failed: %s", e)


def _new_password_error(password: str) -> Optional[str]:
    """Single password policy shared by registration, reset and change."""
    if len(password) < 8 or not any(char.isdigit() for char in password):
        return "Password must be at least 8 characters and contain one number."
    return None


def _auth_error(message: str, **extra) -> JSONResponse:
    """App-level auth failure in the shape the auth pages' JS reads."""
    return JSONResponse(content={"success": False, "error": message, **extra})


def _recover_password_sync(email: str, redirect_to: str) -> Optional[bool]:
    """Ask GoTrue to email a password-recovery link — stateless like
    _refresh_session_sync. Returns True when accepted, False when rate
    limited, None when the service is unreachable. GoTrue answers 200 whether
    or not the email has an account, so acceptance leaks nothing.
    """
    try:
        response = httpx.post(
            f"{SUPABASE_URL}/auth/v1/recover",
            params={"redirect_to": redirect_to},
            json={"email": email},
            headers={"apikey": SUPABASE_KEY},
            timeout=10.0,
        )
    except httpx.HTTPError as e:
        logger.warning("Password recovery request failed: %s", e)
        return None
    if response.status_code == 429:
        return False
    if response.status_code >= 400:
        # Other rejections (e.g. malformed email) must look identical to the
        # unknown-address case, or the endpoint becomes an enumeration oracle.
        logger.debug("Password recovery rejected with status %s", response.status_code)
    return True


def _update_password_sync(access_token: str, new_password: str) -> tuple[Optional[int], Optional[str]]:
    """Set a new password on the account behind this access token via the
    stateless GoTrue REST API. Returns (status_code, server_message);
    status None means the request itself failed.
    """
    try:
        response = httpx.put(
            f"{SUPABASE_URL}/auth/v1/user",
            json={"password": new_password},
            headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {access_token}"},
            timeout=10.0,
        )
    except httpx.HTTPError as e:
        logger.warning("Password update request failed: %s", e)
        return None, None
    if response.status_code == 200:
        return 200, None
    message = None
    try:
        body = response.json()
        message = body.get("msg") or body.get("message") or body.get("error_description")
    except Exception:
        pass
    logger.debug("Password update rejected with status %s: %s", response.status_code, message)
    return response.status_code, message


def _verify_password_sync(email: str, password: str) -> bool:
    """Check an email/password pair via the stateless password grant. The
    minted session is discarded unused — this is only a credentials check
    for the change-password flow.
    """
    try:
        response = httpx.post(
            f"{SUPABASE_URL}/auth/v1/token",
            params={"grant_type": "password"},
            json={"email": email, "password": password},
            headers={"apikey": SUPABASE_KEY},
            timeout=10.0,
        )
        return response.status_code == 200
    except httpx.HTTPError as e:
        logger.warning("Password verification request failed: %s", e)
        return False


async def _try_refresh_session(request: Request) -> Optional[tuple[str, str]]:
    """When the access token is missing or expired, mint a new session from
    the refresh-token cookie. Returns the refreshed identity, or None to fall
    back to the logged-out behavior. The new tokens are stashed on
    request.state so the middleware can persist them as cookies.
    """
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        return None
    payload = await run_in_threadpool(_refresh_session_sync, refresh_token)
    if payload is False:
        # The token is dead — have the middleware drop the cookie so we don't
        # burn a failing Supabase round trip on every future request.
        request.state.clear_refresh_cookie = True
        return None
    if not payload:
        return None
    access_token = payload["access_token"]
    auth_user = payload["user"]
    identity = (str(auth_user["id"]), auth_user.get("email"))
    _auth_cache_put(access_token, *identity)
    request.state.refreshed_session = {
        "access_token": access_token,
        # Supabase rotates refresh tokens; fall back to the current one just in
        # case the response omits it.
        "refresh_token": payload.get("refresh_token") or refresh_token,
    }
    return identity


async def get_current_user(request: Request, conn: psycopg2.extensions.connection) -> Optional[User]:
    token = request.cookies.get("access_token")
    identity = None
    if token:
        try:
            cached = _auth_cache_get(token)
            if cached is not None:
                identity = cached
            else:
                # The Supabase client is synchronous; keep the network call off
                # the event loop.
                user_response = await run_in_threadpool(supabase.auth.get_user, token)
                auth_user = user_response.user
                if auth_user:
                    identity = (str(auth_user.id), auth_user.email)
                    _auth_cache_put(token, *identity)
        except AuthApiError as e:
            # Expired/invalid tokens are normal — debug level avoids log spam.
            logger.debug("Supabase auth rejected token: %s", e)

    # Access token gone or expired: transparently refresh instead of logging
    # the user out mid-session.
    if identity is None:
        identity = await _try_refresh_session(request)
    if identity is None:
        return None

    auth_user_id, auth_email = identity
    # Look up the profile first and only create one when it's missing.
    # This keeps the common (already-registered) request path read-only
    # instead of issuing an INSERT ... ON CONFLICT on every authenticated
    # request. create_profile stays idempotent, so first-seen users still
    # get a profile created here.
    profile = crud.get_profile_by_auth_id(conn, auth_user_id)
    if profile is None:
        crud.create_profile(conn, username=auth_email, auth_user_id=auth_user_id)
        profile = crud.get_profile_by_auth_id(conn, auth_user_id)
    if profile:
        return User(**profile)
    return None

@app.get("/logout")
async def logout(request: Request):
    token = request.cookies.get("access_token")
    if token:
        with _auth_token_cache_lock:
            _auth_token_cache.pop(token, None)
        await run_in_threadpool(_sign_out_sync, token)

    response = RedirectResponse(url="/", status_code=303)
    secure_cookie = should_use_secure_cookies(request)
    response.delete_cookie("access_token", path="/", secure=secure_cookie, httponly=True, samesite="lax")
    response.delete_cookie("refresh_token", path="/", secure=secure_cookie, httponly=True, samesite="lax")
    response.delete_cookie("csrf_token", path="/", secure=secure_cookie, samesite="lax")
    return response

async def get_current_active_user(request: Request):
    if not request.state.user:
        if getattr(request.state, "auth_resolution_failed", False):
            raise HTTPException(status_code=503, detail="Authentication service is temporarily unavailable.")
        # Redirect to the unified auth page if user is not authenticated
        raise HTTPException(status_code=303, headers={"Location": "/auth"})
    return request.state.user

# --- Input Validation Helpers ---

def _validate_course_path(path: str) -> str:
    """Reject paths that try to traverse outside the user's course space.

    Courses are stored keyed by a relative path per user; we never hit the
    filesystem, but validating at the boundary keeps untrusted input from
    reaching the DB and avoids surprises if callers ever interpret the path
    as a filesystem location (e.g. for downloads).
    """
    if not path:
        raise HTTPException(status_code=400, detail="Course path cannot be empty.")
    if len(path) > MAX_COURSE_PATH_LEN:
        raise HTTPException(status_code=400, detail="Course path is too long.")
    if "\x00" in path:
        raise HTTPException(status_code=400, detail="Invalid course path.")
    normalized = path.replace("\\", "/")
    if normalized.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid course path.")
    if any(part in {"", ".", ".."} for part in normalized.split("/")):
        raise HTTPException(status_code=400, detail="Invalid course path.")
    if any(ord(char) < 32 for char in normalized):
        raise HTTPException(status_code=400, detail="Invalid course path.")
    return normalized


def _validate_card_input(question: str, answer: str, card_type: str = "basic") -> tuple[str, str, str]:
    question = question.strip()
    answer = answer.strip()
    if not question or not answer:
        raise HTTPException(status_code=400, detail="Question and answer are required.")
    if len(question) > MAX_CARD_QUESTION_LEN or len(answer) > MAX_CARD_ANSWER_LEN:
        raise HTTPException(status_code=400, detail="Card content is too large.")
    if card_type not in ("basic", "cloze"):
        raise HTTPException(status_code=400, detail="Invalid card type.")
    return question, answer, card_type


# --- Rate Limiting ---
# Simple in-memory per-user token bucket. Sufficient as a first line of defence
# against a single logged-in user burning through their own LLM quota or
# flooding the provider. On Vercel each serverless instance gets its own map,
# so the effective limit is per-instance — good enough for now. Swap for a
# shared store (Redis) if you need a strict global cap.
_LLM_RATE_LIMIT_MAX = 10
_LLM_RATE_LIMIT_WINDOW_SECS = 60
_llm_rate_limit_state: dict[str, deque] = {}
_llm_rate_limit_lock = Lock()


def _check_llm_rate_limit(user_id: str) -> None:
    now = time.monotonic()
    window_start = now - _LLM_RATE_LIMIT_WINDOW_SECS
    with _llm_rate_limit_lock:
        bucket = _llm_rate_limit_state.setdefault(user_id, deque())
        while bucket and bucket[0] < window_start:
            bucket.popleft()
        if len(bucket) >= _LLM_RATE_LIMIT_MAX:
            retry_after = int(_LLM_RATE_LIMIT_WINDOW_SECS - (now - bucket[0])) + 1
            raise HTTPException(
                status_code=429,
                detail=f"Too many card-generation requests. Please retry in {retry_after}s.",
                headers={"Retry-After": str(retry_after)},
            )
        bucket.append(now)


# --- LLM Output Validation ---

def _validate_generated_cards(cards) -> list[dict]:
    """Coerce whatever the LLM returned into a safe list of card dicts.

    The LLM is instructed to return a specific schema but can drift. We drop
    malformed entries rather than failing the whole batch so the user still
    gets something useful, and we cap lengths so a runaway response can't
    flood the UI or the DB.
    """
    if not isinstance(cards, list):
        return []
    valid: list[dict] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        question = card.get("question")
        answer = card.get("answer")
        if not isinstance(question, str) or not isinstance(answer, str):
            continue
        question = question.strip()
        answer = answer.strip()
        if not question or not answer:
            continue
        if len(question) > MAX_CARD_QUESTION_LEN or len(answer) > MAX_CARD_ANSWER_LEN:
            continue
        card_type = card.get("card_type", "basic")
        if card_type not in ("basic", "cloze"):
            card_type = "basic"
        valid.append({"question": question, "answer": answer, "card_type": card_type})
    return valid


# --- LLM & Card Generation ---

# One JSON Schema enforced natively by both providers (Anthropic structured
# outputs, Gemini constrained decoding). The decoder can only emit
# schema-valid JSON, so LaTeX backslashes can no longer break parsing —
# no escaping instructions or regex repair needed.
CARDS_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "cards": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "answer": {"type": "string"},
                    "card_type": {"type": "string", "enum": ["basic", "cloze"]},
                },
                "required": ["question", "answer", "card_type"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["cards"],
    "additionalProperties": False,
}


def generate_cards(text: str, mode="gemini", api_key: str = None, card_type: str = "basic") -> list[dict]:
    if card_type == "cloze":
        prompt = f"""
        Analyze the following text and generate cloze deletion flashcards.
        **Instructions:**
        1.  **Language:** Generate the cards in the same language as the provided text.
        2.  **Focus:** Concentrate on the core concepts, definitions, key terms, and formulas. Avoid trivial details.
        3.  **Cloze Format:** Create fill-in-the-blank cards using the {{{{c1::answer}}}} syntax.
            - The "question" field contains the full sentence with cloze deletions, e.g., "The {{{{c1::mitochondria}}}} is the powerhouse of the cell."
            - The "answer" field contains ONLY the hidden word(s), e.g., "mitochondria"
            - Each card should have exactly ONE cloze deletion.
        4.  **LaTeX:** Use LaTeX for mathematical formulas. Enclose inline math with `$` and block math with `$$`.
        5.  **card_type:** Set "card_type" to "cloze" for every card.

        **Text to Analyze:**
        ---
        {text}
        ---
        """
    else:
        prompt = f"""
        Analyze the following text and generate a list of question-and-answer pairs for flashcards.
        **Instructions:**
        1.  **Language:** Generate the cards in the same language as the provided text.
        2.  **Focus:** Concentrate on the core concepts, definitions, and key formulas. Avoid trivial details.
        3.  **LaTeX:** Use LaTeX for all mathematical formulas. Enclose inline math with `$` and block math with `$$`.
        4.  **card_type:** Set "card_type" to "basic" for every card.

        **Text to Analyze:**
        ---
        {text}
        ---
        """

    try:
        if mode == "gemini":
            if not api_key:
                raise ValueError("Gemini API key is required.")
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config={
                    'temperature': 0.5,
                    'top_p': 0.95,
                    'top_k': 64,
                    'max_output_tokens': 8192,
                    'response_mime_type': 'application/json',
                    'response_json_schema': CARDS_JSON_SCHEMA,
                },
            )
            response_text = response.text.strip()

        elif mode == "anthropic":
            if not api_key:
                raise ValueError("Anthropic API key is required.")
            client = anthropic.Anthropic(api_key=api_key)
            # Sonnet 5 thinks by default when `thinking` is omitted; card
            # generation is structured extraction, so keep the old no-thinking
            # behavior and spend the whole budget on cards. 16k output absorbs
            # Sonnet 5's ~30% denser tokenizer (8k truncated large batches
            # before). output_config rides in extra_body only because the
            # pinned SDK predates the typed parameter — the API itself is GA.
            message = client.messages.create(
                model='claude-sonnet-5',
                max_tokens=16000,
                thinking={"type": "disabled"},
                extra_body={"output_config": {"format": {"type": "json_schema", "schema": CARDS_JSON_SCHEMA}}},
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
            )
            response_text = next((b.text for b in message.content if b.type == "text"), "")

        # All providers enforce CARDS_JSON_SCHEMA at decode time, so this is
        # normally just json.loads; the repair fallback stays as a safety net.
        parsed = robust_json_loads(response_text)
        raw_cards = parsed.get("cards", []) if isinstance(parsed, dict) else []
        cards = _validate_generated_cards(raw_cards)
        return normalize_cards(cards)

    except Exception as e:
        logger.error(f"An error occurred during {mode} API call: {e}")
        return []


@app.get("/settings", response_class=HTMLResponse)
async def settings_form(request: Request, user: User = Depends(get_current_active_user)):
    # Never send stored secrets back to the browser. Surface only booleans so
    # the UI can indicate whether a key is configured.
    return templates.TemplateResponse(request, "settings.html", {
        "csrf_token": request.state.csrf_token,
        "gemini_key_set": bool(user.gemini_api_key),
        "anthropic_key_set": bool(user.anthropic_api_key),
        "telegram_linked": bool(user.telegram_chat_id),
        "telegram_bot_username": TELEGRAM_BOT_USERNAME,
        "telegram_link_token": make_telegram_link_token(user.auth_user_id),
    })

@app.get("/api-keys")
@app.get("/secrets")
async def legacy_settings_redirect():
    # The API-keys and secrets pages were merged into /settings.
    return RedirectResponse(url="/settings")

@app.post("/secrets")
async def save_secrets(telegram_chat_id: str = Form(None), conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    # Chat IDs are only ever written by the bot's /start deep link, which
    # proves the caller owns the chat — a self-reported ID could point this
    # account's reminders (and cards) at someone else's chat. This endpoint
    # only disconnects.
    if (telegram_chat_id or "").strip():
        raise HTTPException(status_code=400, detail="Telegram is connected through the bot — use the Connect Telegram button in Settings.")

    crud.save_secrets_for_user(conn, user.auth_user_id, None)
    return JSONResponse(content={"success": True})


# --- Auth Routes (Supabase email-based login/register) ---
@app.get("/auth", response_class=HTMLResponse)
async def auth_form(request: Request):
    """Display the unified authentication form."""
    return templates.TemplateResponse(request, "auth.html", {
        "supabase_url": SUPABASE_URL,
        "supabase_key": SUPABASE_KEY,
        "csrf_token": request.state.csrf_token
    })

@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    """Redirect to the main authentication page for backward compatibility."""
    return RedirectResponse(url="/auth")

@app.post("/auth")
async def handle_auth(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    action: str = Form("login"), # Can be "login" or "register"
    conn: psycopg2.extensions.connection = Depends(get_db)
):
    """
    Handles both login and registration with a unified, intelligent endpoint.
    - For login: attempts sign-in directly, handles errors appropriately
    - For register: validates password, creates user, auto-logs in
    - Returns JSON with redirect URL for frontend navigation
    """
    def error_response(error: str, prompt_register: bool = False):
        """Helper to return consistent error responses. The frontend
        (auth.html) reads only these fields."""
        return JSONResponse(content={
            "success": False,
            "error": error,
            "prompt_register": prompt_register,
        })

    def success_response(session, flash_message: str):
        """Helper to return successful auth response with session cookies."""
        response = JSONResponse(content={
            "success": True,
            "redirect_url": "/"
        })
        _set_session_cookies(response, request, session.access_token, getattr(session, "refresh_token", None))
        set_flash_cookie(response, request, f"success:{flash_message}")
        return response

    try:
        if action == "register":
            # --- REGISTRATION FLOW ---
            policy_error = _new_password_error(password)
            if policy_error:
                return error_response(policy_error)

            # With Supabase's "confirm email" setting enabled the account is
            # created but can't sign in yet — surfaced either as a missing
            # auto-login session or as a "not confirmed" AuthApiError.
            confirm_email_response = JSONResponse(content={
                "success": False,
                "info": "Account created! Check your email to confirm your address, then log in.",
            })

            try:
                # Create user in Supabase
                auth_response = supabase.auth.sign_up({"email": email, "password": password})
                if not auth_response.user:
                    return error_response("Could not create account. The email may be invalid.")

                # Create local profile and auto-login
                crud.create_profile(conn, username=email, auth_user_id=auth_response.user.id)
                auto_login_response = supabase.auth.sign_in_with_password({"email": email, "password": password})

                if not auto_login_response.session:
                    return confirm_email_response
                return success_response(auto_login_response.session, "Account created successfully!")

            except AuthApiError as e:
                error_msg = str(e)
                if "already registered" in error_msg.lower() or "already exists" in error_msg.lower():
                    # account_exists tells the page to drop its register intent
                    # and treat the next submit as a login attempt again.
                    return _auth_error(
                        "An account with this email already exists — check your password and log in instead.",
                        account_exists=True,
                    )
                if "not confirmed" in error_msg.lower():
                    return confirm_email_response
                return error_response(f"Registration failed: {error_msg}")
        else:
            # --- LOGIN FLOW ---
            try:
                auth_response = supabase.auth.sign_in_with_password({"email": email, "password": password})
                if auth_response.session:
                    return success_response(auth_response.session, "Welcome back!")
                else:
                    return error_response("Login failed. Please try again.")

            except AuthApiError as e:
                error_msg = str(e)
                # Supabase returns "Invalid login credentials" for both wrong password and non-existent user
                # We prompt to register since we can't distinguish between the two
                if "invalid" in error_msg.lower() or "credentials" in error_msg.lower():
                    return error_response("Invalid email or password.", prompt_register=True)
                return error_response(f"Login failed: {error_msg}")

    except Exception as e:
        logger.error(f"General auth error: {e}", exc_info=True)
        return error_response("An unexpected error occurred. Please try again.")

@app.post("/auth/callback")
async def auth_callback(
    request: Request,
    data: AuthCallback,
    conn: psycopg2.extensions.connection = Depends(get_db)
):
    """
    Handles the callback from the frontend after a successful Supabase OAuth login.
    Receives tokens, validates them, creates a local user profile if needed,
    and sets a session cookie.
    """
    try:
        user_response = supabase.auth.get_user(data.access_token)
        auth_user = user_response.user

        if not auth_user:
            raise HTTPException(status_code=401, detail="Invalid token")

        # Create a profile if it doesn't exist. Without one, every request
        # treats the session as logged out — fail loudly rather than set
        # cookies that produce an invisible login loop.
        crud.create_profile(conn, username=auth_user.email, auth_user_id=auth_user.id)
        if not crud.get_profile_by_auth_id(conn, auth_user.id):
            raise HTTPException(status_code=500, detail="Could not initialize your profile. Please try again.")

        # Set the session cookies to log the user in. The refresh token keeps
        # the session alive after the ~1h access token expires.
        response = JSONResponse(content={"success": True, "redirect_url": "/"})
        _set_session_cookies(response, request, data.access_token, data.refresh_token)
        set_flash_cookie(response, request, "success:Logged in successfully!")
        return response

    except HTTPException:
        # An invalid token is the client's fault — don't collapse it into a 500.
        raise
    except Exception as e:
        logger.error(f"Auth callback error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Authentication callback failed.")

# --- Password reset (lost password) and change ---
@app.get("/auth/reset", response_class=HTMLResponse)
async def password_reset_form(request: Request):
    """Request-a-reset-email form. The same page finishes the flow when the
    Supabase recovery link lands back here with tokens in the URL fragment."""
    return templates.TemplateResponse(request, "reset_password.html", {
        "csrf_token": request.state.csrf_token,
    })


@app.post("/auth/reset")
async def password_reset_request(request: Request, email: str = Form(...)):
    """Send a password-recovery email via Supabase.

    The response is deliberately identical for known and unknown addresses so
    the endpoint can't be used to enumerate accounts. Abuse is bounded by
    Supabase's own per-email and global email rate limits (surfaced as 429).
    """
    # The recovery link must land back on this page to finish the flow. The
    # host comes from the request so every deployment works unchanged; a
    # spoofed Host header can't hijack the link because Supabase only
    # redirects to allowlisted URLs and falls back to the Site URL otherwise.
    scheme = "https" if should_use_secure_cookies(request) else "http"
    redirect_to = f"{scheme}://{request.url.netloc}/auth/reset"

    result = await run_in_threadpool(_recover_password_sync, email.strip(), redirect_to)
    if result is False:
        return _auth_error("Too many reset emails requested. Please wait a while and try again.")
    if result is None:
        return _auth_error("The authentication service is temporarily unavailable. Please try again.")
    return JSONResponse(content={
        "success": True,
        "message": "If an account exists for that address, a password reset link is on its way.",
    })


@app.post("/auth/reset/confirm")
async def password_reset_confirm(request: Request, data: PasswordResetConfirm):
    """Set a new password using the short-lived recovery session from the
    emailed link (tokens arrive in the URL fragment, so only the browser can
    see them — the page posts them here)."""
    policy_error = _new_password_error(data.password)
    if policy_error:
        return _auth_error(policy_error)

    status_code, message = await run_in_threadpool(_update_password_sync, data.access_token, data.password)
    if status_code == 200:
        # The recovery session survives the update; reuse it to log the user
        # straight in, exactly like the OAuth callback does.
        response = JSONResponse(content={"success": True, "redirect_url": "/"})
        _set_session_cookies(response, request, data.access_token, data.refresh_token)
        set_flash_cookie(response, request, "success:Password updated!")
        return response
    if status_code in (401, 403):
        return _auth_error("This reset link has expired or was already used. Please request a new one.")
    return _auth_error(message or "Could not update the password. Please request a new reset link.")


@app.post("/auth/change-password")
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    user: User = Depends(get_current_active_user),
):
    """Change the password of the logged-in user, gated on the current one so
    a stolen session cookie can't be parlayed into account takeover."""
    policy_error = _new_password_error(new_password)
    if policy_error:
        return _auth_error(policy_error)

    # user.username is the auth email (profiles are created from it). OAuth-only
    # accounts have no password to verify — they set one via the reset email.
    verified = await run_in_threadpool(_verify_password_sync, user.username, current_password)
    if not verified:
        return _auth_error("Current password is incorrect.")

    # Use the freshest token for this session: the cookie one may have just
    # been rotated by the transparent refresh earlier in this request.
    refreshed = getattr(request.state, "refreshed_session", None)
    access_token = refreshed["access_token"] if refreshed else request.cookies.get("access_token")
    status_code, message = await run_in_threadpool(_update_password_sync, access_token, new_password)
    if status_code == 200:
        return JSONResponse(content={"success": True})
    return _auth_error(message or "Could not update the password. Please try again.")


@app.get("/health", response_class=JSONResponse)
async def health_check():
    """A simple endpoint to keep the service alive."""
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse(request, "home.html", {
        "telegram_bot_username": TELEGRAM_BOT_USERNAME,
        "supabase_url": SUPABASE_URL,
        "supabase_key": SUPABASE_KEY
    })

@app.get("/courses", response_class=HTMLResponse)
async def list_courses(request: Request, user: User = Depends(get_current_active_user)):
    return templates.TemplateResponse(request, "courses_list.html")

@app.get("/edit-course/{course_path:path}", response_class=HTMLResponse)
async def edit_course(request: Request, course_path: str, user: User = Depends(get_current_active_user)):
    # Starlette already percent-decodes path params; decoding again would
    # corrupt names containing literal % sequences (e.g. "a%20b.md").
    course_path = _validate_course_path(course_path)
    return templates.TemplateResponse(request, "course_editor.html", {
        "course_path": course_path,
        "gemini_api_key_exists": bool(user.gemini_api_key),
        "anthropic_api_key_exists": bool(user.anthropic_api_key),
        "csrf_token": request.state.csrf_token
    })

@app.get("/courses/{course_path:path}", response_class=HTMLResponse)
async def view_course(request: Request, course_path: str, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    course_path = _validate_course_path(course_path)
    course = crud.get_course_content_for_user(conn, course_path, auth_user_id=user.auth_user_id)
    if not course or not course['content']:
        raise HTTPException(status_code=404, detail="Course not found")

    content = course['content']
    # Legacy rows stored the markdown JSON-encoded; only unwrap when the
    # decoded value is still a string, otherwise frontmatter.loads would crash
    # on plain markdown that happens to parse as JSON (e.g. "123").
    try:
        decoded = json.loads(content)
        if isinstance(decoded, str):
            content = decoded
    except (json.JSONDecodeError, TypeError):
        pass

    # Hand-edited frontmatter can be invalid YAML (or parse to a non-dict) —
    # render the file raw rather than 500; the crud helpers already tolerate
    # this the same way.
    try:
        post = frontmatter.loads(content)
        metadata = post.metadata if isinstance(post.metadata, dict) else {}
        body = post.content
    except Exception:
        metadata, body = {}, content

    if 'tags' in metadata:
        metadata['tags'] = sanitize_tags(metadata['tags'])

    return templates.TemplateResponse(request, "course_viewer.html", {
        "metadata": metadata,
        "content": body,
        "course_path": course_path,
        "gemini_api_key_exists": bool(user.gemini_api_key),
        "anthropic_api_key_exists": bool(user.anthropic_api_key),
        "csrf_token": request.state.csrf_token
    })

# --- API for Courses ---
@app.get("/api/courses-tree")
async def api_get_courses_tree(conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    return crud.get_courses_tree_for_user(conn, auth_user_id=user.auth_user_id)

@app.get("/api/download-course/{course_path:path}")
async def download_course(course_path: str, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    course_path = _validate_course_path(course_path)
    course = crud.get_course_content_for_user(conn, course_path, auth_user_id=user.auth_user_id)
    if not course:
        raise HTTPException(status_code=404, detail="File not found")
  
    # Create a safe filename for the Content-Disposition header
    filename = posixpath.basename(course_path)
    if not filename.endswith('.md'):
        filename += '.md'
        
    # For cross-browser compatibility with special characters, we create a complex header.
    # 1. A simple ASCII version of the filename for older browsers.
    ascii_filename = filename.encode('ascii', 'ignore').decode()
    ascii_filename = ascii_filename.replace("\\", "_").replace('"', "_") or "course.md"
    # 2. The properly URL-encoded UTF-8 version for modern browsers.
    utf8_filename = quote(filename)
    
    disposition = f'attachment; filename="{ascii_filename}"; filename*=UTF-8\'\'{utf8_filename}'
    
    return Response(
        content=course['content'],
        media_type="text/markdown",
        headers={"Content-Disposition": disposition}
    )

@app.get("/api/course-content/{course_path:path}", response_class=JSONResponse)
async def api_get_course_content(course_path: str, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    course_path = _validate_course_path(course_path)
    course = crud.get_course_content_for_user(conn, course_path, auth_user_id=user.auth_user_id)
    if not course:
        raise HTTPException(status_code=404, detail="File not found")
    return JSONResponse(content=course['content'])

@app.post("/api/course-content")
async def api_save_course_content(item: CourseContent, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    path = _validate_course_path(item.path)
    crud.save_course_content_for_user(conn, path, item.content, auth_user_id=user.auth_user_id)
    return {"success": True}

@app.api_route("/api/course-item", methods=["POST", "DELETE"])
async def api_manage_course_item(item: CourseItem, request: Request, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    path = _validate_course_path(item.path)
    if request.method == "POST":
        crud.create_course_item_for_user(conn, path, item.type, auth_user_id=user.auth_user_id)
    elif request.method == "DELETE":
        crud.delete_course_item_for_user(conn, path, item.type, auth_user_id=user.auth_user_id)
    return {"success": True}

@app.post("/api/course-item/rename")
async def api_rename_course_item(item: CourseItemRename, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    old_path = _validate_course_path(item.path)
    new_path = _validate_course_path(item.new_path)
    if new_path == old_path:
        return {"success": True}
    if item.type != "file" and new_path.startswith(f"{old_path}/"):
        raise HTTPException(status_code=400, detail="Cannot move a folder inside itself.")
    try:
        renamed = crud.rename_course_item_for_user(conn, old_path, new_path, item.type, user.auth_user_id)
    except psycopg2.IntegrityError:
        raise HTTPException(status_code=409, detail="Something already exists at the destination path.")
    if not renamed:
        raise HTTPException(status_code=404, detail="Item not found.")
    return {"success": True}

async def _generate_cards_response(data: CourseContentForGeneration, user: User, mode: str, api_key: Optional[str]):
    if not data.content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty.")
    _check_llm_rate_limit(str(user.auth_user_id))
    generated_cards = await run_in_threadpool(
        generate_cards,
        data.content,
        mode=mode,
        api_key=api_key,
        card_type=data.card_type,
    )
    if not generated_cards:
        raise HTTPException(status_code=500, detail="Failed to generate cards.")
    return {"cards": generated_cards}

@app.post("/api/generate-cards")
async def api_generate_cards(data: CourseContentForGeneration, user: User = Depends(get_current_active_user)):
    return await _generate_cards_response(data, user, mode="gemini", api_key=user.gemini_api_key)

@app.post("/api/generate-cards-anthropic")
async def api_generate_cards_anthropic(data: CourseContentForGeneration, user: User = Depends(get_current_active_user)):
    return await _generate_cards_response(data, user, mode="anthropic", api_key=user.anthropic_api_key)

@app.post("/api/save-cards")
async def api_save_cards(data: GeneratedCards, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    crud.save_generated_cards_for_user(conn, data.cards, user.auth_user_id)
    return {"success": True, "message": f"{len(data.cards)} cards saved successfully."}

@app.get("/api/tags")
async def api_get_tags(conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    tags = crud.get_all_tags_for_user(conn, auth_user_id=user.auth_user_id)
    return JSONResponse(content=tags)

@app.post("/api/save-api-keys")
async def api_save_api_keys(data: ApiKeys, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    # Treat blank/omitted fields as "leave existing value alone" rather than
    # wiping the stored key. The form deliberately does not round-trip the
    # current value, so a user who only wants to update one key can leave the
    # other blank without losing it.
    def _resolve(submitted: Optional[str], current: Optional[str]) -> Optional[str]:
        if submitted is None:
            return current
        trimmed = submitted.strip()
        return trimmed if trimmed else current

    gemini_key = _resolve(data.gemini_api_key, user.gemini_api_key)
    anthropic_key = _resolve(data.anthropic_api_key, user.anthropic_api_key)
    crud.save_api_keys_for_user(conn, user.auth_user_id, gemini_key, anthropic_key)
    return {"success": True}

# --- Tag-based Views ---
@app.get("/tags/{tag_name}", response_class=HTMLResponse)
async def view_courses_by_tag(request: Request, tag_name: str, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    courses = crud.get_courses_by_tag_for_user(conn, tag_name, auth_user_id=user.auth_user_id)
    return templates.TemplateResponse(request, "tag_courses.html", {"tag": tag_name, "courses": courses})

# --- Scheduler ---
@app.get("/api/trigger-scheduler")
async def trigger_scheduler(request: Request):
    submitted_secret = request.headers.get("x-scheduler-secret")
    if not scheduler_secret_is_valid(submitted_secret):
        raise HTTPException(status_code=403, detail="Invalid secret")
    
    webhook_status = await _ensure_webhook()
    logger.info(f"Webhook status: {webhook_status}")
    
    result = await run_scheduler()
    return JSONResponse(content={"status": "completed", "result": result, "webhook_status": webhook_status})

# --- Card Management Routes ---
@app.get("/render/card/{card_id}", response_class=HTMLResponse)
async def render_card_for_screenshot(request: Request, card_id: int, exp: int, sig: str, conn: psycopg2.extensions.connection = Depends(get_db)):
    """Minimal page rendering a card's answer (Markdown + MathJax) for the
    Telegram screenshot function. Unauthenticated by design: access is
    granted by a short-lived HMAC signature instead of a session."""
    if not verify_render_request(card_id, exp, sig):
        raise HTTPException(status_code=403, detail="Invalid or expired signature")
    card = crud.get_card_by_id(conn, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")
    return templates.TemplateResponse(request, "render_card.html", {"content": card["answer"]})

@app.get("/card/{card_id}", response_class=HTMLResponse)
async def view_card(request: Request, card_id: int, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    card = crud.get_card_for_user(conn, card_id, user.auth_user_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")
    return templates.TemplateResponse(request, "card_viewer.html", {"card": card})

@app.get("/review", response_class=HTMLResponse)
async def review(request: Request, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    card = crud.get_review_cards_for_user(conn, user.auth_user_id)
    stats = crud.get_review_stats_for_user(conn, user.auth_user_id)

    if card is None:
        return templates.TemplateResponse(request, "no_cards.html", {
            "total_cards": stats['total_cards'],
            "streak": crud.get_review_streak_for_user(conn, user.auth_user_id),
            "leaderboard": crud.get_leaderboard(conn, user.auth_user_id),
        })

    csrf_token = request.state.csrf_token
    return templates.TemplateResponse(request, "review.html", {
        "card": card,
        "due_today_count": stats['due_today'],
        "new_cards_count": stats['new_cards'],
        "total_cards": stats['total_cards'],
        "streak": crud.get_review_streak_for_user(conn, user.auth_user_id),
        "csrf_token": csrf_token
    })

@app.post("/review/{card_id}")
async def update_review(card_id: int, status: str = Form(...), conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    if crud.update_card_for_user(conn, card_id, user.auth_user_id, status == "remembered"):
        crud.record_review_activity(conn, user.auth_user_id, status == "remembered")
    return RedirectResponse(url="/review", status_code=303)


@app.post("/api/review/{card_id}", response_class=JSONResponse)
async def update_review_ajax(
    card_id: int,
    status: str = Form(...),
    exclude: str = Form(None),
    conn: psycopg2.extensions.connection = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Record a rating and return the next due card + deck stats as JSON.

    Powers the no-reload review loop. The form-based /review/{card_id} endpoint
    above is kept as a no-JS fallback.
    """
    if status not in ("remembered", "forgot"):
        raise HTTPException(status_code=400, detail="Invalid review status.")

    result = crud.update_card_for_user(conn, card_id, user.auth_user_id, status == "remembered")
    if result:
        crud.record_review_activity(conn, user.auth_user_id, status == "remembered")

    payload = _review_state_payload(conn, user, _parse_exclude(exclude))
    if result:
        payload["review"] = {
            "interval": result["interval"],
            "previous": {
                "interval": result["previous"]["interval"],
                "ease_factor": result["previous"]["ease_factor"],
                "due_date": result["previous"]["due_date"].isoformat(),
            },
        }
    return JSONResponse(content=payload)


@app.post("/api/review/{card_id}/undo", response_class=JSONResponse)
async def undo_review_ajax(
    card_id: int,
    payload: ReviewUndo,
    conn: psycopg2.extensions.connection = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Restores a card's pre-rating scheduling so a mis-keyed rating can be
    undone from the toast. Review activity is left as recorded — streaks
    count effort, not outcomes."""
    crud.restore_card_schedule_for_user(
        conn, card_id, user.auth_user_id,
        payload.interval, payload.ease_factor, payload.due_date,
    )
    return JSONResponse(content=_review_state_payload(conn, user))


def _parse_exclude(exclude: str | None) -> list[int]:
    """Comma-separated card ids the client has set aside this session."""
    if not exclude:
        return []
    return [int(part) for part in exclude.split(",")[:200] if part.strip().isdigit()]


@app.get("/api/review/next", response_class=JSONResponse)
async def next_review_card(
    exclude: str = None,
    conn: psycopg2.extensions.connection = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Next due card minus skipped ids — powers swipe-to-skip."""
    return JSONResponse(content=_review_state_payload(conn, user, _parse_exclude(exclude)))


def _review_state_payload(conn, user: User, exclude_ids=None) -> dict:
    """The next due card plus deck stats, as consumed by the review page JS."""
    next_card = crud.get_review_cards_for_user(conn, user.auth_user_id, exclude_ids)
    stats = crud.get_review_stats_for_user(conn, user.auth_user_id)
    streak = crud.get_review_streak_for_user(conn, user.auth_user_id)

    payload = {
        "next_card": None,
        "stats": {
            "due_today": stats["due_today"],
            "new_cards": stats["new_cards"],
            "total_cards": stats["total_cards"],
            # None when activity tracking is unavailable — the UI then leaves
            # the streak badge alone.
            "streak": streak["current"] if streak else None,
        },
    }
    if next_card is not None:
        card = dict(next_card)
        payload["next_card"] = {
            "id": card["id"],
            "question": card["question"],
            "answer": card["answer"],
            "card_type": card.get("card_type") or "basic",
        }
    return payload

@app.get("/manage", response_class=HTMLResponse)
async def manage_cards(request: Request, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    cards = crud.get_all_cards_for_user(conn, user.auth_user_id)
    csrf_token = request.state.csrf_token
    return templates.TemplateResponse(request, "manage_cards.html", {"cards": cards, "csrf_token": csrf_token})

@app.get("/new", response_class=HTMLResponse)
async def new_card_form(request: Request, user: User = Depends(get_current_active_user)):
    csrf_token = request.state.csrf_token
    return templates.TemplateResponse(request, "new_card.html", {"csrf_token": csrf_token})

@app.post("/new")
async def create_new_card(request: Request, question: str = Form(...), answer: str = Form(...), card_type: str = Form("basic"), conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    question, answer, card_type = _validate_card_input(question, answer, card_type)
    crud.create_card_for_user(conn, question, answer, user.auth_user_id, card_type=card_type)
    response = RedirectResponse(url="/", status_code=303)
    set_flash_cookie(response, request, "success:Card created successfully!")
    return response

@app.get("/edit-card/{card_id}", response_class=HTMLResponse)
async def edit_card_form(request: Request, card_id: int, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    card = crud.get_card_for_user(conn, card_id, user.auth_user_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")
    csrf_token = request.state.csrf_token
    return templates.TemplateResponse(request, "edit_card.html", {"card": card, "csrf_token": csrf_token})

@app.post("/edit-card/{card_id}")
async def update_existing_card(card_id: int, question: str = Form(...), answer: str = Form(...), conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    question, answer, _ = _validate_card_input(question, answer)
    crud.update_card_content_for_user(conn, card_id, user.auth_user_id, question, answer)
    return RedirectResponse(url="/manage", status_code=303)

@app.post("/delete/{card_id}")
async def delete_card(request: Request, card_id: int, conn: psycopg2.extensions.connection = Depends(get_db), user: User = Depends(get_current_active_user)):
    crud.delete_card_for_user(conn, card_id, user.auth_user_id)
    response = RedirectResponse(url="/manage", status_code=303)
    set_flash_cookie(response, request, "success:Card deleted successfully!")
    return response
