"""
Application middleware for rate limiting, request logging, and security headers.
"""
import time
from collections import defaultdict
from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from app.logging_config import logger


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Simple in-memory rate limiter.
    Tracks requests per IP per window and blocks excess requests.
    
    Not suitable for multi-process deployments (use Redis-based limiter instead).
    For a single Render instance, this works perfectly.
    """

    def __init__(self, app, requests_per_minute: int = 60, burst_paths: dict = None):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.burst_paths = burst_paths or {}  # path -> max_per_minute
        self._requests = defaultdict(list)  # ip -> [timestamps]
        self._path_requests = defaultdict(lambda: defaultdict(list))  # path -> ip -> [timestamps]

    def _clean_old(self, timestamps: list, window: int = 60) -> list:
        """Remove timestamps older than the window."""
        cutoff = time.time() - window
        return [t for t in timestamps if t > cutoff]

    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        path = request.url.path

        # Check path-specific rate limits (stricter for auth endpoints)
        for protected_path, max_rpm in self.burst_paths.items():
            if path.startswith(protected_path):
                key = f"{client_ip}:{protected_path}"
                self._path_requests[protected_path][client_ip] = self._clean_old(
                    self._path_requests[protected_path][client_ip]
                )
                if len(self._path_requests[protected_path][client_ip]) >= max_rpm:
                    logger.warning(f"Rate limit exceeded: {client_ip} on {path}")
                    return JSONResponse(
                        {"detail": "Too many requests. Please slow down."},
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        headers={"Retry-After": "60"},
                    )
                self._path_requests[protected_path][client_ip].append(now)
                break

        # Global rate limit
        self._requests[client_ip] = self._clean_old(self._requests[client_ip])
        if len(self._requests[client_ip]) >= self.requests_per_minute:
            return JSONResponse(
                {"detail": "Too many requests. Please slow down."},
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                headers={"Retry-After": "60"},
            )
        self._requests[client_ip].append(now)

        # Periodic cleanup to prevent memory leak (every ~1000 requests)
        if len(self._requests) > 5000:
            self._requests.clear()
            self._path_requests.clear()

        response = await call_next(request)
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds security headers to all responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response
