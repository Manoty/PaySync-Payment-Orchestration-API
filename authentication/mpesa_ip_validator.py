import ipaddress
import logging
from django.conf import settings

logger = logging.getLogger(__name__)


# Safaricom's published M-Pesa callback IP ranges
# Source: Daraja developer documentation
# Update these if Safaricom publishes new ranges
MPESA_CALLBACK_IP_RANGES = [
    "196.201.214.0/24",
    "196.201.214.200/24",
    "196.201.213.0/24",
    "196.201.213.9/24",
    "196.201.212.0/24",
    "196.201.210.0/24",
    "196.201.209.0/24",
    "196.201.208.0/24",
]

# In sandbox, Safaricom uses different IPs
# We allow all in sandbox for development flexibility
MPESA_SANDBOX_ALLOW_ALL = True


class MpesaIPValidator:
    """
    Validates that M-Pesa callback requests originate from
    Safaricom's known IP ranges.
    
    Why this matters:
    Without IP validation, anyone who guesses your callback URL
    can POST fake success payloads and mark payments as paid.
    With IP validation, only Safaricom's servers can trigger status changes.
    
    Limitation: Safaricom's IP ranges can change. Monitor their
    developer portal for updates and update MPESA_CALLBACK_IP_RANGES.
    """

    def __init__(self):
        self.is_sandbox = getattr(settings, 'MPESA_ENV', 'sandbox') == 'sandbox'
        self._networks  = [
            ipaddress.ip_network(cidr)
            for cidr in MPESA_CALLBACK_IP_RANGES
        ]

    def is_valid_mpesa_ip(self, ip_address: str) -> bool:
        """
        Returns True if the IP is in Safaricom's known ranges.
        In sandbox mode, allows all IPs for development.
        """
        if self.is_sandbox and MPESA_SANDBOX_ALLOW_ALL:
            logger.debug(
                f"Sandbox mode — skipping IP validation for {ip_address}"
            )
            return True

        if not ip_address:
            logger.warning("Callback received with no IP address — rejecting.")
            return False

        try:
            ip = ipaddress.ip_address(ip_address)
        except ValueError:
            logger.warning(f"Invalid IP address format: {ip_address}")
            return False

        for network in self._networks:
            if ip in network:
                logger.debug(f"IP {ip_address} validated in range {network}")
                return True

        logger.warning(
            f"Callback from IP {ip_address} REJECTED — "
            f"not in Safaricom's known ranges. "
            f"If this is legitimate, update MPESA_CALLBACK_IP_RANGES."
        )
        return False

    def get_client_ip(self, request) -> str:
        """Extract real IP, accounting for load balancers and proxies."""
        forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if forwarded_for:
            # X-Forwarded-For: client, proxy1, proxy2
            # First IP is the original client
            return forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', '')