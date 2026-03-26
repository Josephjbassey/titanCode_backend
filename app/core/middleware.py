"""
TitanCode Technologies — Request Logging Middleware
=====================================================
This middleware logs every HTTP request/response with timing information.

What gets logged:
    - HTTP method and path (e.g. "POST /api/v1/auth/login")
    - Response status code (200, 401, 500, etc.)
    - Request duration in milliseconds
    - Client IP address

This is essential for:
    1. **Performance monitoring** — Identify slow endpoints.
    2. **Security auditing** — Track who accessed what and when.
    3. **Debugging** — Correlate errors with specific requests.

Log Output Example:
    {"timestamp": "...", "level": "INFO",
     "message": "POST /api/v1/auth/login → 200 (45.2ms) from 127.0.0.1"}
"""

import time
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Logger for request/response tracking
logger = logging.getLogger("titancode.requests")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware that logs every HTTP request with timing and status info.

    FastAPI middleware wraps every request — it runs BEFORE the endpoint
    handler and AFTER the response is generated. This lets us measure
    the total time each request takes.

    Flow:
        Client → [Middleware START (timer)] → Endpoint → [Middleware END (log)] → Client
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        """
        Process each request: start a timer, call the endpoint, log the result.

        Args:
            request:   The incoming HTTP request.
            call_next: A function that passes the request to the next
                       middleware or the actual endpoint handler.

        Returns:
            The response from the endpoint (unmodified).
        """
        # ── Start the timer ────────────────────────────────────────────
        start_time = time.perf_counter()

        # Get client IP (may be forwarded by a proxy)
        client_ip = request.client.host if request.client else "unknown"

        # ── Call the actual endpoint ───────────────────────────────────
        try:
            response = await call_next(request)
        except Exception as e:
            # Log unhandled exceptions before re-raising
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                f"{request.method} {request.url.path} → 500 ({duration_ms:.1f}ms) "
                f"from {client_ip} — {type(e).__name__}: {e}"
            )
            raise

        # ── Calculate request duration ─────────────────────────────────
        duration_ms = (time.perf_counter() - start_time) * 1000

        # ── Log the request ────────────────────────────────────────────
        # Use different log levels based on status code:
        #   2xx = INFO   (normal)
        #   4xx = WARNING (client errors — might indicate bugs or attacks)
        #   5xx = ERROR  (server errors — needs attention)
        status_code = response.status_code
        log_message = (
            f"{request.method} {request.url.path} → {status_code} "
            f"({duration_ms:.1f}ms) from {client_ip}"
        )

        if status_code >= 500:
            logger.error(log_message)
        elif status_code >= 400:
            logger.warning(log_message)
        else:
            logger.info(log_message)

        # ── Add timing header to the response ──────────────────────────
        # Useful for frontend devs and debugging — they can see how long
        # the server took without needing access to server logs.
        response.headers["X-Process-Time"] = f"{duration_ms:.1f}ms"

        return response
