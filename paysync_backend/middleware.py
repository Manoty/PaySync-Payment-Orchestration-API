"""
Request/response logging middleware.

Logs every API request with timing, status, and client info.
This gives you a full access log in structured JSON — no separate
nginx log parsing needed.
"""

import time
import logging
import uuid

logger = logging.getLogger('payments')


class RequestLoggingMiddleware:
    """
    Logs every HTTP request and response with:
    - Unique request ID (for tracing across logs)
    - Method, path, status code
    - Response time in milliseconds
    - Client identity (API key owner or anonymous)
    - IP address
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Generate unique ID for this request
        # Attach to request so views can reference it in their own logs
        request.request_id = str(uuid.uuid4())[:8]
        start_time         = time.monotonic()

        response = self.get_response(request)

        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        # Identify the caller
        client_name = 'anonymous'
        if hasattr(request, 'user') and hasattr(request.user, 'name'):
            client_name = request.user.name

        # Skip health check logging — it's called every minute by monitors
        # and would flood the logs with noise
        if request.path == '/api/v1/health/':
            return response

        log_level = 'warning' if response.status_code >= 400 else 'info'

        getattr(logger, log_level)(
            f"{request.method} {request.path} → {response.status_code}",
            extra={
                "event":       "http_request",
                "request_id":  request.request_id,
                "method":      request.method,
                "path":        request.path,
                "status_code": response.status_code,
                "elapsed_ms":  elapsed_ms,
                "client":      client_name,
                "ip":          self._get_ip(request),
            }
        )

        # Attach request ID to response header
        # Clients can log this to correlate their logs with PaySync's
        response['X-Request-ID'] = request.request_id

        return response

    def _get_ip(self, request):
        forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
        if forwarded:
            return forwarded.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', 'unknown')