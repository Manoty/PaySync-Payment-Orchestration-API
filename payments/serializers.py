from rest_framework import serializers
from .models import Payment, PaymentAttempt, CallbackLog


class InitiatePaymentSerializer(serializers.Serializer):
    """
    Validates incoming payment requests from Tixora/Scott.
    Intentionally NOT a ModelSerializer — we control exactly
    what fields external systems can send.
    """
    amount = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=1,        # M-Pesa minimum is KES 1
        max_value=150000,   # M-Pesa maximum per transaction
    )
    phone_number = serializers.CharField(max_length=15)
    external_reference = serializers.CharField(max_length=100)
    source_system = serializers.ChoiceField(
        choices=['tixora', 'scott'],
    )

    def validate_phone_number(self, value):
        """
        Normalize and validate M-Pesa phone number format.
        Accepts: 07XXXXXXXX, 2547XXXXXXXX, +2547XXXXXXXX
        Returns: 2547XXXXXXXX (what Daraja expects)
        """
        # Strip whitespace and any dashes
        value = value.strip().replace('-', '').replace(' ', '')

        # Strip leading +
        if value.startswith('+'):
            value = value[1:]

        # Convert 07XXXXXXXX → 2547XXXXXXXX
        if value.startswith('0') and len(value) == 10:
            value = '254' + value[1:]

        # Validate final format
        if not value.startswith('254') or len(value) != 12:
            raise serializers.ValidationError(
                "Invalid phone number. Use format: 07XXXXXXXX or 2547XXXXXXXX"
            )

        if not value.isdigit():
            raise serializers.ValidationError(
                "Phone number must contain digits only."
            )

        return value

    def validate_external_reference(self, value):
        """Prevent empty or whitespace-only references."""
        if not value.strip():
            raise serializers.ValidationError(
                "external_reference cannot be blank."
            )
        return value.strip()

    def validate_amount(self, value):
        """M-Pesa only accepts whole shilling amounts."""
        from decimal import Decimal
        # Round to nearest whole number for M-Pesa compatibility
        if value != value.quantize(Decimal('1')):
            raise serializers.ValidationError(
                "M-Pesa only accepts whole shilling amounts. "
                f"Round {value} to {int(value)}."
            )
        return value


class PaymentAttemptSerializer(serializers.ModelSerializer):
    """Nested serializer — shown inside payment detail responses."""

    class Meta:
        model = PaymentAttempt
        fields = [
            'attempt_number',
            'status',
            'mpesa_checkout_request_id',
            'error_message',
            'created_at',
        ]
        # Never expose raw M-Pesa response payload to external systems
        # That's internal debugging data only


class PaymentSerializer(serializers.ModelSerializer):
    """
    Read serializer — what external systems receive when
    checking payment status or listing payments.
    """
    attempts = PaymentAttemptSerializer(many=True, read_only=True)
    reference = serializers.UUIDField(format='hex_verbose')

    class Meta:
        model = Payment
        fields = [
            'reference',
            'external_reference',
            'source_system',
            'amount',
            'phone_number',
            'status',
            'provider',
            'retry_count',       
            'next_retry_at',      
            'attempts',
            'created_at',
            'updated_at',
        ]


class PaymentSummarySerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for list views.
    No nested attempts — keeps list responses fast.
    """
    reference = serializers.UUIDField(format='hex_verbose')

    class Meta:
        model = Payment
        fields = [
            'reference',
            'external_reference',
            'source_system',
            'amount',
            'phone_number',
            'status',
            'provider',
            'created_at',
        ]