"""
Custom DRF exception handler and Django error views.

DRF's default exception handler returns different shapes for
different errors. We normalize everything to PaySync's envelope:
{
    "success": false,
    "message": "...",
    "errors":  { ... }    # optional
}
"""

import logging
from rest_framework.views import exception_handler as drf_exception_handler
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import (
    AuthenticationFailed,
    NotAuthenticated,
    PermissionDenied,
    NotFound,
    ValidationError,
    Throttled,
)

logger = logging.getLogger('payments')


def paysync_exception_handler(exc, context):
    """
    Custom DRF exception handler.
    Called for every exception raised inside DRF views.

    Normalizes ALL error responses to the PaySync envelope shape.
    Logs with structured context so every error is traceable.
    """

    # Let DRF handle the exception first — it converts known
    # exceptions to Response objects
    response = drf_exception_handler(exc, context)

    if response is None:
        # Unhandled exception — DRF returned nothing
        # Django will return a 500. We log it here for visibility.
        logger.critical(
            "Unhandled exception in view",
            extra={
                "event":      "unhandled_exception",
                "exception":  str(exc),
                "view":       str(context.get('view')),
                "request_method": getattr(context.get('request'), 'method', 'UNKNOWN'),
                "request_path":   getattr(
                    context.get('request'), 'path', 'UNKNOWN'
                ),
            },
            exc_info=True,
        )
        return Response(
            {
                "success": False,
                "message": "An unexpected error occurred. Our team has been notified.",
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # ── Map DRF exception types to clean messages ─────────────────────────────
    if isinstance(exc, NotAuthenticated):
        message = "Authentication required. Include X-API-Key header."
        log_level = 'warning'
    elif isinstance(exc, AuthenticationFailed):
        message = "Invalid or expired API key."
        log_level = 'warning'
    elif isinstance(exc, PermissionDenied):
        message = str(exc.detail) if hasattr(exc, 'detail') else "Permission denied."
        log_level = 'warning'
    elif isinstance(exc, NotFound):
        message = "The requested resource was not found."
        log_level = 'info'
    elif isinstance(exc, ValidationError):
        message = "Validation failed. Check the errors field for details."
        log_level = 'info'
    elif isinstance(exc, Throttled):
        wait = getattr(exc, 'wait', None)
        message = (
            f"Rate limit exceeded. "
            f"{'Try again in ' + str(int(wait)) + ' seconds.' if wait else 'Try again later.'}"
        )
        log_level = 'warning'
    else:
        message = "An error occurred processing your request."
        log_level = 'error'

    # ── Build structured error payload ────────────────────────────────────────
    payload = {
        "success": False,
        "message": message,
    }

    # Include field-level errors for validation failures
    if isinstance(exc, ValidationError) and hasattr(exc, 'detail'):
        payload["errors"] = exc.detail

    # ── Structured log with full context ──────────────────────────────────────
    request     = context.get('request')
    view        = context.get('view')
    log_context = {
        "event":          "api_exception",
        "exception_type": type(exc).__name__,
        "status_code":    response.status_code,
        "path":           getattr(request, 'path', 'unknown'),
        "method":         getattr(request, 'method', 'unknown'),
        "view":           type(view).__name__ if view else 'unknown',
        "client":         getattr(
            getattr(request, 'user', None), 'name', 'unauthenticated'
        ),
    }

    getattr(logger, log_level)(
        f"API exception: {type(exc).__name__}",
        extra=log_context,
    )

    response.data = payload
    return response