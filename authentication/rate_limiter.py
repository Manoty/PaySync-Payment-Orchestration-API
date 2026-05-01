import logging
from datetime import timedelta
from django.utils import timezone
from .models import APIRequestLog

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Sliding window rate limiter using the APIRequestLog table.
    
    Why not Redis? We're avoiding external dependencies for now.
    PostgreSQL with a proper index handles this fine up to
    a few hundred requests per minute. Upgrade to Redis when needed.
    
    Sliding window vs fixed window:
    Fixed window: allow 30/min, resets at :00 every minute
      → Client can send 30 at :59, 30 more at :00 = 60 in 2 seconds
    Sliding window: count requests in the LAST 60 seconds always
      → Truly limits to 30/min regardless of timing
    We use sliding window — more accurate, slightly more DB load.
    """

    def check_rate_limit(self, client) -> tuple[bool, dict]:
        """
        Check if client has exceeded their rate limit.
        
        Returns:
            (allowed: bool, info: dict)
            info contains: limit, remaining, reset_seconds
        """
        window_start = timezone.now() - timedelta(minutes=1)
        request_count = APIRequestLog.objects.filter(
            client=client,
            created_at__gte=window_start,
        ).count()

        limit     = client.rate_limit_per_minute
        remaining = max(0, limit - request_count)
        allowed   = request_count < limit

        if not allowed:
            logger.warning(
                f"Rate limit exceeded: {client.name} | "
                f"count={request_count} | limit={limit}"
            )

        return allowed, {
            "limit":          limit,
            "remaining":      remaining,
            "reset_seconds":  60,
            "current_count":  request_count,
        }

    def log_request(self, client, request, status_code=None):
        """
        Record this request in the audit log.
        Called after every authenticated request — success or failure.
        """
        ip = self._get_ip(request)
        APIRequestLog.objects.create(
            client=client,
            endpoint=request.path,
            method=request.method,
            ip_address=ip,
            status_code=status_code,
        )

    def _get_ip(self, request):
        forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
        if forwarded:
            return forwarded.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', 'unknown')