import uuid
from django.db import models


class Payment(models.Model):
    """
    Represents a single payment intention from an external system.

    One Payment can have multiple PaymentAttempts (retries).
    The status here always reflects the LATEST known truth.

    External systems (Tixora, Scott) reference this via `reference`.
    They pass their own order ID as `external_reference`.
    """

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        SUCCESS = 'success', 'Success'
        FAILED  = 'failed',  'Failed'

    class Provider(models.TextChoices):
        MPESA = 'mpesa', 'M-Pesa'
        
    MAX_RETRY_ATTEMPTS = 3   
    
    # --- Retry control fields ---
    retry_count = models.PositiveIntegerField(default=0)
    next_retry_at = models.DateTimeField(null=True, blank=True, db_index=True)
    is_processing = models.BooleanField(default=False, db_index=True)


    # Internal unique identifier — this is what PaySync uses
    reference = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_index=True,
    )

    # The ID from Tixora/Scott — e.g. "ORDER_123" or "DELIVERY_456"
    external_reference = models.CharField(
        max_length=100,
        db_index=True,
    )

    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    # Stored in international format: 2547XXXXXXXX
    phone_number = models.CharField(max_length=15)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )

    provider = models.CharField(
        max_length=20,
        choices=Provider.choices,
        default=Provider.MPESA,
    )

    # Which system initiated this payment
    source_system = models.CharField(
        max_length=50,
        help_text="e.g. 'tixora', 'scott'",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['external_reference', 'source_system']),
        ]

    def __str__(self):
        return f"[{self.source_system.upper()}] {self.reference} | {self.status} | KES {self.amount}"


class PaymentAttempt(models.Model):
    """
    Represents one attempt to process a Payment.

    Each retry = one new PaymentAttempt row.
    Never deleted — this is your audit trail.

    response_payload stores exactly what M-Pesa returned,
    so you can debug any failure without guessing.
    """

    class Status(models.TextChoices):
        INITIATED = 'initiated', 'Initiated'
        SUCCESS   = 'success',   'Success'
        FAILED    = 'failed',    'Failed'

    payment = models.ForeignKey(
        Payment,
        on_delete=models.PROTECT,   # Never delete a Payment that has attempts
        related_name='attempts',
    )

    attempt_number = models.PositiveIntegerField(default=1)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.INITIATED,
    )

    # Raw response from M-Pesa — store everything, filter later
    response_payload = models.JSONField(
        null=True,
        blank=True,
    )

    # M-Pesa's own transaction ID (MpesaReceiptNumber)
    # Populated after success callback
    mpesa_checkout_request_id = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        db_index=True,
    )

    error_message = models.TextField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['attempt_number']
        # Ensures attempt numbers are unique per payment
        unique_together = [['payment', 'attempt_number']]

    def __str__(self):
        return f"Attempt #{self.attempt_number} for {self.payment.reference} — {self.status}"


class CallbackLog(models.Model):
    """
    Stores EVERY raw callback received from M-Pesa, immediately,
    before any processing happens.

    Why? Because:
    1. M-Pesa can send duplicate callbacks
    2. Your processing code might crash — you still have the raw data
    3. You can replay callbacks if something goes wrong
    4. It's a tamper-evident audit trail

    This is a write-first, process-second pattern.
    """

    # Link to the PaymentAttempt once we identify it
    # null=True because we log FIRST, link AFTER
    payment_attempt = models.ForeignKey(
        PaymentAttempt,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='callback_logs',
    )

    # Raw payload exactly as received — never modified
    raw_payload = models.JSONField()

    # The checkout request ID from M-Pesa — used to match the callback
    # to the correct PaymentAttempt
    checkout_request_id = models.CharField(
        max_length=100,
        db_index=True,
        null=True,
        blank=True,
    )

    # False = received but not yet processed
    # True  = successfully linked and status updated
    processed = models.BooleanField(default=False, db_index=True)

    # If processing failed, why?
    processing_error = models.TextField(null=True, blank=True)

    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="IP that sent the callback — for security auditing",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        status = "✓ processed" if self.processed else "⏳ unprocessed"
        return f"CallbackLog [{status}] — {self.checkout_request_id}"