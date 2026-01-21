from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request as StarletteRequest
from starlette.types import ASGIApp, Receive, Scope, Send, Message
import secrets
from urllib.parse import parse_qs


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

        return response


class CSRFMiddleware:
    """
    Pure ASGI middleware for CSRF protection.

    Unlike BaseHTTPMiddleware, this properly handles request body caching
    so the body can be read both in the middleware and in endpoint handlers.
    """

    def __init__(self, app: ASGIApp):
        self.app = app
        self.exempt_paths = ["/webhook/", "/docs", "/openapi.json", "/health", "/auth/callback"]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = StarletteRequest(scope, receive)
        path = scope.get("path", "")
        method = scope.get("method", "GET")

        # Paths that should be exempt from CSRF protection
        if any(path.startswith(exempt) for exempt in self.exempt_paths):
            await self.app(scope, receive, send)
            return

        # For GET requests, generate and set the token (only if not already present)
        if method == "GET":
            # Check if a CSRF token already exists in the cookie
            existing_csrf_token = None
            for header_name, header_value in scope.get("headers", []):
                if header_name == b"cookie":
                    cookies_header = header_value.decode()
                    for cookie in cookies_header.split(";"):
                        cookie = cookie.strip()
                        if cookie.startswith("csrf_token="):
                            existing_csrf_token = cookie[len("csrf_token="):]
                            break
                    break

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
                        is_https = scope.get("scheme", "http") == "https"
                        cookie_value = f"csrf_token={csrf_token}; SameSite=Lax; Max-Age=3600; Path=/"
                        if is_https:
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
            # Get CSRF token from cookie
            csrf_token_from_cookie = None
            cookies_header = None
            for header_name, header_value in scope.get("headers", []):
                if header_name == b"cookie":
                    cookies_header = header_value.decode()
                    break

            if cookies_header:
                for cookie in cookies_header.split(";"):
                    cookie = cookie.strip()
                    if cookie.startswith("csrf_token="):
                        csrf_token_from_cookie = cookie[len("csrf_token="):]
                        break

            # Always read the entire body first so it can be passed to the endpoint
            body_bytes = b""
            while True:
                message = await receive()
                body_bytes += message.get("body", b"")
                if not message.get("more_body", False):
                    break

            # Get CSRF token from request (header or form body)
            csrf_token_from_request = None

            # Check header first
            for header_name, header_value in scope.get("headers", []):
                if header_name == b"x-csrf-token":
                    csrf_token_from_request = header_value.decode()
                    break

            # If not in header, try to parse from form body
            if csrf_token_from_request is None:
                try:
                    content_type = None
                    for header_name, header_value in scope.get("headers", []):
                        if header_name == b"content-type":
                            content_type = header_value.decode()
                            break

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
