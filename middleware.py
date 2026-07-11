import os
import secrets
from urllib.parse import parse_qs

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp, Receive, Scope, Send, Message


MAX_REQUEST_BODY_BYTES = int(os.environ.get("MAX_REQUEST_BODY_BYTES", str(5 * 1024 * 1024)))


def _header_value(scope: Scope, name: bytes) -> str | None:
    for header_name, header_value in scope.get("headers", []):
        if header_name == name:
            return header_value.decode()
    return None


def _cookie_value(scope: Scope, name: str) -> str | None:
    cookies_header = _header_value(scope, b"cookie")
    if not cookies_header:
        return None
    prefix = f"{name}="
    for cookie in cookies_header.split(";"):
        cookie = cookie.strip()
        if cookie.startswith(prefix):
            return cookie[len(prefix):]
    return None


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds security headers to all responses."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)

        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"

        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # XSS protection (legacy but still useful for older browsers)
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # Referrer policy - don't leak full URL to other origins
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Permissions policy - disable unnecessary browser features
        response.headers["Permissions-Policy"] = (
            "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
            "magnetometer=(), microphone=(), payment=(), usb=()"
        )

        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "img-src 'self' data: https:; "
            "font-src 'self' data: https://cdn.jsdelivr.net; "
            "connect-src 'self' https://*.supabase.co wss://*.supabase.co https://vitals.vercel-insights.com; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "frame-ancestors 'none'; "
            "form-action 'self'"
        )

        if (
            os.environ.get("ENVIRONMENT") == "production"
            or request.url.scheme == "https"
            or request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower() == "https"
        ):
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        # Every /auth* page handles credentials; the prefix match keeps new
        # auth sub-pages covered without touching this list.
        if request.url.path in {"/login", "/logout", "/settings"} or request.url.path.startswith("/auth"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"

        return response


class CSRFMiddleware:
    """
    Pure ASGI middleware for CSRF protection.

    Unlike BaseHTTPMiddleware, this properly handles request body caching
    so the body can be read both in the middleware and in endpoint handlers.
    """

    def __init__(self, app: ASGIApp):
        self.app = app
        # Static-ish paths render no forms; minting tokens there lets a
        # first visit's parallel asset responses race Set-Cookie against the
        # document's token, 403ing the no-JS form fallbacks.
        self.exempt_paths = ["/webhook/", "/docs", "/openapi.json", "/health",
                             "/static/", "/_vercel/", "/favicon.ico"]

    def _should_use_secure_cookies(self, scope: Scope) -> bool:
        forwarded_proto = _header_value(scope, b"x-forwarded-proto") or ""
        return (
            os.environ.get("ENVIRONMENT") == "production"
            or scope.get("scheme", "http") == "https"
            or forwarded_proto.split(",")[0].strip().lower() == "https"
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "GET")

        # Paths that should be exempt from CSRF protection
        if any(path.startswith(exempt) for exempt in self.exempt_paths):
            await self.app(scope, receive, send)
            return

        # For GET requests, generate and set the token (only if not already present)
        if method == "GET":
            existing_csrf_token = _cookie_value(scope, "csrf_token")

            # Use existing token or generate a new one
            csrf_token = existing_csrf_token if existing_csrf_token else secrets.token_hex(16)

            # Store in scope state so templates can access it
            if "state" not in scope:
                scope["state"] = {}
            scope["state"]["csrf_token"] = csrf_token

            # Only set the cookie if we generated a new token
            if not existing_csrf_token:
                async def send_with_csrf_cookie(message: Message) -> None:
                    if message["type"] == "http.response.start":
                        headers = list(message.get("headers", []))
                        # Match the session cookie lifetime (7 days). A shorter
                        # CSRF cookie expired mid-session and made every POST
                        # fail with 403 until the page was reloaded — e.g. after
                        # an hour-long editing session, Save silently broke.
                        cookie_value = f"csrf_token={csrf_token}; SameSite=Lax; Max-Age={7 * 24 * 3600}; Path=/"
                        if self._should_use_secure_cookies(scope):
                            cookie_value += "; Secure"
                        headers.append((b"set-cookie", cookie_value.encode()))
                        message = {**message, "headers": headers}
                    await send(message)

                await self.app(scope, receive, send_with_csrf_cookie)
            else:
                await self.app(scope, receive, send)
            return

        # For state-changing methods, validate the token
        if method in ["POST", "PUT", "DELETE", "PATCH"]:
            csrf_token_from_cookie = _cookie_value(scope, "csrf_token")

            # Always read the entire body first so it can be passed to the endpoint
            body_bytes = b""
            while True:
                message = await receive()
                body_bytes += message.get("body", b"")
                if len(body_bytes) > MAX_REQUEST_BODY_BYTES:
                    response = JSONResponse(
                        status_code=413,
                        content={"detail": "Request body too large"},
                    )
                    await response(scope, receive, send)
                    return
                if not message.get("more_body", False):
                    break

            # Get CSRF token from request: header first, then form body
            csrf_token_from_request = _header_value(scope, b"x-csrf-token")
            if csrf_token_from_request is None:
                try:
                    content_type = _header_value(scope, b"content-type")
                    if content_type and "application/x-www-form-urlencoded" in content_type:
                        form_data = parse_qs(body_bytes.decode(), keep_blank_values=True)
                        csrf_tokens = form_data.get("csrf_token", [])
                        if csrf_tokens:
                            csrf_token_from_request = csrf_tokens[0]
                except Exception:
                    pass

            # Validate CSRF token
            if not csrf_token_from_cookie or not csrf_token_from_request or not secrets.compare_digest(csrf_token_from_cookie, csrf_token_from_request):
                response = JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF token mismatch"},
                )
                await response(scope, receive, send)
                return

            # Store token in state for templates
            if "state" not in scope:
                scope["state"] = {}
            scope["state"]["csrf_token"] = csrf_token_from_cookie

            # Create a new receive function that returns the cached body
            # This is critical - it allows the endpoint handler to re-read the body
            body_consumed = False

            async def receive_with_cached_body() -> Message:
                nonlocal body_consumed
                if not body_consumed:
                    body_consumed = True
                    return {"type": "http.request", "body": body_bytes, "more_body": False}
                # Return empty body for subsequent calls
                return {"type": "http.request", "body": b"", "more_body": False}

            await self.app(scope, receive_with_cached_body, send)
            return

        # For other methods, just pass through
        await self.app(scope, receive, send)
