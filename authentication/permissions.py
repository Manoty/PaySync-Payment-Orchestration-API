import logging
from rest_framework.permissions import BasePermission
from rest_framework.exceptions import PermissionDenied

logger = logging.getLogger(__name__)


class IsAuthenticatedAPIClient(BasePermission):
    """
    Grants access only to requests authenticated via APIKeyBackend.
    Returns 401 for unauthenticated requests.
    """
    message = "Valid API key required. Include X-API-Key header."

    def has_permission(self, request, view):
        # DRF sets request.auth to the second element of the
        # (user, auth) tuple returned by authenticate()
        # We set request.user to the APIClient instance
        return (
            request.user is not None
            and hasattr(request.user, 'source_system')
        )


class SourceSystemMatchesClient(BasePermission):
    """
    Ensures the source_system in the request body matches
    the authenticated client's registered source_system.
    
    Prevents Tixora from initiating payments as Scott.
    
    Applied only to payment initiation — other endpoints
    don't carry source_system in the body.
    """
    message = "source_system in request must match your API client registration."

    def has_permission(self, request, view):
        if request.method != 'POST':
            return True

        requested_system = request.data.get('source_system', '')
        client_system    = getattr(request.user, 'source_system', None)

        if not client_system:
            return False

        if requested_system != client_system:
            logger.warning(
                f"source_system mismatch: client={client_system} "
                f"requested={requested_system}"
            )
            raise PermissionDenied(
                f"Your API key is registered for '{client_system}'. "
                f"You cannot initiate payments as '{requested_system}'."
            )

        return True