import logging
from django.utils import timezone
from .models import APIClient, APIRequestLog

logger = logging.getLogger(__name__)


class APIKeyBackend:
    """
    Authenticates requests using the X-API-Key header.
    
    Expected header:
        X-API-Key: paysync_a3f9c2d1...
    
    Returns the APIClient instance if valid, None otherwise.
    Never raises — authentication failures return None.
    """

    HEADER_NAME = 'HTTP_X_API_KEY'  # Django converts X-API-Key → HTTP_X_API_KEY

    def authenticate(self, request):
        """
        Validates the API key and returns (client, None) on success.
        Returns None if authentication fails.
        
        DRF calls this during request processing.
        """
        raw_key = request.META.get(self.HEADER_NAME, '').strip()

        if not raw_key:
            return None     # No key provided — let other authenticators try

        if not raw_key.startswith('paysync_'):
            logger.warning(
                f"Invalid API key format from {self._get_ip(request)} — "
                f"missing 'paysync_' prefix"
            )
            return None

        # Look up by hash — never store or log the raw key
        from .models import hash_api_key
        key_hash = hash_api_key(raw_key)

        try:
            client = APIClient.objects.get(
                key_hash=key_hash,
                status=APIClient.Status.ACTIVE,
            )
        except APIClient.DoesNotExist:
            logger.warning(
                f"Invalid or revoked API key attempt from "
                f"{self._get_ip(request)}"
            )
            return None

        # Valid key — record usage
        client.record_usage()

        logger.debug(
            f"Authenticated: {client.name} ({client.source_system}) "
            f"from {self._get_ip(request)}"
        )

        return (client, None)   # DRF expects (user, auth) tuple

    def authenticate_header(self, request):
        """Tells DRF what header to advertise in 401 responses."""
        return 'X-API-Key'

    def _get_ip(self, request):
        forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
        if forwarded:
            return forwarded.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', 'unknown')