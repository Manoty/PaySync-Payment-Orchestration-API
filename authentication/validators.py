import re
import logging
from decimal import Decimal, InvalidOperation
from rest_framework import serializers

logger = logging.getLogger(__name__)

# ── Phone validation ───────────────────────────────────────────────────────────

# Kenyan mobile network prefixes (Safaricom only for M-Pesa)
SAFARICOM_PREFIXES = [
    '0700', '0701', '0702', '0703', '0704', '0705', '0706', '0707',
    '0708', '0709', '0710', '0711', '0712', '0713', '0714', '0715',
    '0716', '0717', '0718', '0719', '0720', '0721', '0722', '0723',
    '0724', '0725', '0726', '0727', '0728', '0729', '0740', '0741',
    '0742', '0743', '0744', '0745', '0746', '0747', '0748', '0757',
    '0758', '0759', '0768', '0769', '0790', '0791', '0792', '0793',
    '0794', '0795', '0796', '0797', '0798', '0799',
]

# Convert to 4-digit local prefixes for matching
SAFARICOM_4_DIGIT = set(p for p in SAFARICOM_PREFIXES)


def validate_and_normalize_phone(value: str) -> str:
    """
    Validates and normalizes a Kenyan M-Pesa phone number.
    
    Accepts:
        07XXXXXXXX       (local format, 10 digits)
        2547XXXXXXXX     (international, 12 digits)
        +2547XXXXXXXX    (international with +, 13 chars)
    
    Rejects:
        Non-Safaricom numbers (Airtel, Telkom)
        Numbers with wrong length
        Numbers with non-digit characters
        Sequential/test numbers (0700000000)
    
    Returns:
        Normalized 2547XXXXXXXX format
    
    Raises:
        serializers.ValidationError on any invalid input
    """
    if not value:
        raise serializers.ValidationError("Phone number is required.")

    # Strip whitespace, dashes, parentheses
    cleaned = re.sub(r'[\s\-\(\)]', '', value.strip())

    # Strip leading +
    if cleaned.startswith('+'):
        cleaned = cleaned[1:]

    # Convert 07XXXXXXXX → 2547XXXXXXXX
    if cleaned.startswith('0') and len(cleaned) == 10:
        cleaned = '254' + cleaned[1:]

    # Validate final format
    if not cleaned.isdigit():
        raise serializers.ValidationError(
            "Phone number must contain digits only. "
            f"Got: '{value}'"
        )

    if not cleaned.startswith('254'):
        raise serializers.ValidationError(
            "Phone number must be a Kenyan number starting with 254. "
            f"Got: '{value}'"
        )

    if len(cleaned) != 12:
        raise serializers.ValidationError(
            f"Phone number must be 12 digits in international format "
            f"(2547XXXXXXXX). Got {len(cleaned)} digits from '{value}'."
        )

    # Check Safaricom prefix
    local_prefix = '0' + cleaned[3:7]   # e.g. 254712... → 0712
    if local_prefix not in SAFARICOM_4_DIGIT:
        raise serializers.ValidationError(
            f"M-Pesa only works with Safaricom numbers. "
            f"'{value}' does not appear to be a Safaricom number. "
            f"Airtel/Telkom numbers are not supported yet."
        )

    # Reject obviously fake numbers
    suspicious_patterns = [
        r'^2547000000\d\d$',    # 070000000X series
        r'^2547(\d)\1{8}$',     # All same digit: 0711111111
        r'^254700000000$',      # Pure zeros
    ]
    for pattern in suspicious_patterns:
        if re.match(pattern, cleaned):
            raise serializers.ValidationError(
                f"'{value}' appears to be a test/fake number. "
                f"Use a real Safaricom number."
            )

    return cleaned


# ── Amount validation ──────────────────────────────────────────────────────────

MPESA_MIN_AMOUNT = Decimal('1')
MPESA_MAX_AMOUNT = Decimal('150000')


def validate_payment_amount(value) -> Decimal:
    """
    Validates a payment amount for M-Pesa compatibility.
    
    Rules:
    - Must be a valid number
    - Must be >= 1 (M-Pesa minimum)
    - Must be <= 150,000 (M-Pesa daily transaction limit)
    - Must be a whole number (M-Pesa doesn't accept cents)
    
    Returns:
        Validated Decimal amount
    
    Raises:
        serializers.ValidationError on invalid input
    """
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise serializers.ValidationError(
            f"'{value}' is not a valid amount."
        )

    if amount <= 0:
        raise serializers.ValidationError(
            f"Amount must be greater than 0. Got: {amount}"
        )

    if amount < MPESA_MIN_AMOUNT:
        raise serializers.ValidationError(
            f"Minimum M-Pesa transaction is KES {MPESA_MIN_AMOUNT}. "
            f"Got: KES {amount}"
        )

    if amount > MPESA_MAX_AMOUNT:
        raise serializers.ValidationError(
            f"Maximum M-Pesa transaction is KES {MPESA_MAX_AMOUNT:,}. "
            f"Got: KES {amount:,}"
        )

    # M-Pesa only accepts whole shillings
    if amount != amount.to_integral_value():
        raise serializers.ValidationError(
            f"M-Pesa requires whole shilling amounts. "
            f"Round KES {amount} to KES {int(amount)}."
        )

    return amount


# ── External reference validation ──────────────────────────────────────────────

def validate_external_reference(value: str) -> str:
    """
    Validates the external reference from client systems.
    
    Rules:
    - Not empty or whitespace-only
    - Alphanumeric + underscores/dashes only (safe for URLs and logs)
    - Max 100 characters (DB column size)
    - No SQL injection characters
    """
    if not value or not value.strip():
        raise serializers.ValidationError(
            "external_reference cannot be blank."
        )

    cleaned = value.strip()

    if len(cleaned) > 100:
        raise serializers.ValidationError(
            f"external_reference too long: {len(cleaned)} chars (max 100)."
        )

    # Only allow safe characters
    if not re.match(r'^[a-zA-Z0-9_\-]+$', cleaned):
        raise serializers.ValidationError(
            "external_reference must contain only letters, numbers, "
            "underscores, and dashes. "
            f"Got: '{cleaned}'"
        )

    return cleaned