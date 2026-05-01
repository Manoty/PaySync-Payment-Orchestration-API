from rest_framework import serializers
from .models import Payment, PaymentAttempt


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

    # ✅ Inline validation (replaces validators.py)

    def validate_phone_number(self, value):
        value = value.strip().replace("+", "")

        if value.startswith("07"):
            value = "254" + value[1:]

        if not value.startswith("254") or len(value) != 12:
            raise serializers.ValidationError(
                "Phone number must be in format 2547XXXXXXXX"
            )

        return value

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Amount must be greater than 0.")
        return value

    def validate_external_reference(self, value):
        if len(value) < 5:
            raise serializers.ValidationError(
                "External reference too short."
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