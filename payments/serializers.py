from rest_framework import serializers
from .validators import (
    validate_and_normalize_phone,
    validate_payment_amount,
    validate_external_reference,
)


class InitiatePaymentSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=1,
        max_value=150000,
    )
    phone_number = serializers.CharField(max_length=15)
    external_reference = serializers.CharField(max_length=100)
    source_system = serializers.ChoiceField(
        choices=['tixora', 'scott'],
    )

    def validate_phone_number(self, value):
        return validate_and_normalize_phone(value)

    def validate_amount(self, value):
        return validate_payment_amount(value)

    def validate_external_reference(self, value):
        return validate_external_reference(value)

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