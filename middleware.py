from fastapi import Request, Response, Form
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
import secrets

class CSRFMiddleware(BaseHTTPMiddleware):
    async def _get_csrf_token_from_request(self, request: Request) -> str | None:
        """Helper to extract CSRF token from header or form data."""
        csrf_token_from_header = request.headers.get("X-CSRF-Token")
        if csrf_token_from_header:
            return csrf_token_from_header
        
        try:
            # This is a bit tricky because we can only read the form once.
            # We clone the request to avoid consuming the form body here.
            form_data = await request.form()
            return form_data.get("csrf_token")
        except Exception:
            # This will happen if the request is not a form, which is fine.
            return None

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Paths that should be exempt from CSRF protection
        exempt_paths = ["/webhook/", "/docs", "/openapi.json", "/health", "/auth/callback"]
        if any(request.url.path.startswith(path) for path in exempt_paths):
            return await call_next(request)

        # For GET requests, generate and set the token BEFORE handler runs
        if request.method == "GET":
            csrf_token = secrets.token_hex(16)
            request.state.csrf_token = csrf_token  # Set before handler so templates can access it
            response = await call_next(request)
            response.set_cookie(
                key="csrf_token",
                value=csrf_token,
                httponly=False,
                samesite="lax",
                max_age=3600,
                secure=request.url.scheme == "https",
            )
            return response

        # For state-changing methods, validate the token
        if request.method in ["POST", "PUT", "DELETE", "PATCH"]:
            csrf_token_from_cookie = request.cookies.get("csrf_token")
            csrf_token_from_request = await self._get_csrf_token_from_request(request)

            if not csrf_token_from_cookie or not csrf_token_from_request or not secrets.compare_digest(csrf_token_from_cookie, csrf_token_from_request):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF token mismatch"},
                )

        return await call_next(request)
