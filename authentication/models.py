import secrets
import hashlib
import logging
from django.db import models
from django.utils import timezone

logger = logging.getLogger(__name__)


def generate_api_key():
    """
    Generates a cryptographically secure API key.
    Format: paysync_<32 random bytes as hex>
    Example: paysync_a3f9c2d1e4b5f6a7b8c9d0e1f2a3b4c5...
    
    The prefix makes it identifiable in logs and source code scanners.
    GitHub's secret scanning will flag 'paysync_' keys if accidentally committed.
    """
    return f"paysync_{secrets.token_hex(32)}"


def hash_api_key(raw_key: str) -> str:
    """
    We store a SHA-256 hash of the key — never the key itself.
    
    Why? If your database is breached, attackers get hashes,
    not usable keys. Same principle as password hashing.
    The raw key is shown ONCE at creation time and never again.
    """
    return hashlib.sha256(raw_key.encode()).hexdigest()


class APIClient(models.Model):
    """
    Represents an authorised system that can call PaySync.
    
    One row per system: one for Tixora, one for Scott.
    Each has its own key, its own rate limit, its own audit trail.
    """

    class Status(models.TextChoices):
        ACTIVE   = 'active',   'Active'
        REVOKED  = 'revoked',  'Revoked'
        SUSPENDED = 'suspended', 'Suspended'

    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="e.g. 'Tixora Production', 'Scott Staging'"
    )

    # source_system must match what the client sends in request body
    source_system = models.CharField(
        max_length=50,
        unique=True,
        help_text="Must match Payment.source_system (e.g. 'tixora', 'scott')"
    )

    # Stored as SHA-256 hash — raw key shown once at creation, never again
    key_hash = models.CharField(max_length=64, unique=True)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True,
    )

    # Rate limiting
    rate_limit_per_minute = models.PositiveIntegerField(
        default=30,
        help_text="Max payment initiations per minute"
    )

    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.source_system}) [{self.status}]"

    def verify_key(self, raw_key: str) -> bool:
        """Check if a raw key matches this client's stored hash."""
        return hash_api_key(raw_key) == self.key_hash

    def record_usage(self):
        """Update last_used_at timestamp. Called on every authenticated request."""
        self.last_used_at = timezone.now()
        self.save(update_fields=['last_used_at'])

    @classmethod
    def create_with_key(cls, name: str, source_system: str, **kwargs):
        """
        Factory method — creates client and returns (client, raw_key).
        raw_key is shown ONCE and never retrievable again.
        
        Usage:
            client, raw_key = APIClient.create_with_key('Tixora', 'tixora')
            print(raw_key)  # Store this securely — it won't be shown again
        """
        raw_key  = generate_api_key()
        key_hash = hash_api_key(raw_key)
        client   = cls.objects.create(
            name=name,
            source_system=source_system,
            key_hash=key_hash,
            **kwargs
        )
        logger.info(f"API client created: {client.name} / {client.source_system}")
        return client, raw_key


class APIRequestLog(models.Model):
    """
    Lightweight audit log for every authenticated API call.
    
    Used for:
    - Rate limiting (count requests in last 60 seconds)
    - Security auditing (who called what, when, from where)
    - Debugging (what did Tixora send at 10:31?)
    """
    client     = models.ForeignKey(
        APIClient,
        on_delete=models.PROTECT,
        related_name='request_logs',
    )
    endpoint   = models.CharField(max_length=200)
    method     = models.CharField(max_length=10)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    status_code = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            # Index for rate limit queries: client + recent time window
            models.Index(fields=['client', 'created_at']),
        ]

    def __str__(self):
        return f"{self.client.name} {self.method} {self.endpoint} [{self.created_at}]"