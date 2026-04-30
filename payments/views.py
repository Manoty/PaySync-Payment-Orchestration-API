import logging
from rest_framework.views import APIView
from rest_framework import status as http_status
from django.shortcuts import get_object_or_404
from django.db import IntegrityError

from .models import Payment, PaymentAttempt
from .serializers import (
    InitiatePaymentSerializer,
    PaymentSerializer,
    PaymentSummarySerializer,
)
from .utils import success_response, error_response

from .mpesa_service import MpesaService, MpesaError

logger = logging.getLogger(__name__)


class InitiatePaymentView(APIView):
    """
    POST /api/v1/payments/initiate/

    Accepts a payment request from an external system.
    Creates a Payment record and a first PaymentAttempt.
    
    In Phase 4, this will trigger an actual STK Push.
    For now, it validates and stores — proving the API contract works.
    """


    def post(self, request):
        serializer = InitiatePaymentSerializer(data=request.data)

        if not serializer.is_valid():
            logger.warning(
                "Invalid payment initiation request",
                extra={"errors": serializer.errors}
            )
            return error_response(
                message="Invalid payment data.",
                errors=serializer.errors,
            )

        validated = serializer.validated_data

        # ── Idempotency check ────────────────────────────────────────────────
        existing = Payment.objects.filter(
            external_reference=validated['external_reference'],
            source_system=validated['source_system'],
            status__in=[Payment.Status.PENDING, Payment.Status.SUCCESS],
        ).first()

        if existing:
            return success_response(
                data=PaymentSerializer(existing).data,
                message="Payment already exists for this reference.",
            )

        # ── Create Payment record ────────────────────────────────────────────
        payment = Payment.objects.create(
            amount=validated['amount'],
            phone_number=validated['phone_number'],
            external_reference=validated['external_reference'],
            source_system=validated['source_system'],
            status=Payment.Status.PENDING,
            provider=Payment.Provider.MPESA,
        )

        # ── Create first PaymentAttempt ──────────────────────────────────────
        attempt = PaymentAttempt.objects.create(
            payment=payment,
            attempt_number=1,
            status=PaymentAttempt.Status.INITIATED,
        )

        # ── Trigger STK Push ─────────────────────────────────────────────────
        mpesa = MpesaService()
        stk_result = mpesa.initiate_stk_push(payment, attempt)

        if stk_result["success"]:
            # Store M-Pesa's CheckoutRequestID — we need this to match
            # the incoming callback to this specific attempt
            attempt.mpesa_checkout_request_id = stk_result["checkout_request_id"]
            attempt.response_payload = stk_result["response_payload"]
            attempt.status = PaymentAttempt.Status.INITIATED
            attempt.save()

            logger.info(
                f"STK Push sent | reference={payment.reference} | "
                f"checkout_id={stk_result['checkout_request_id']}"
            )

            return success_response(
                data=PaymentSerializer(payment).data,
                message=(
                    "STK Push sent. Customer should receive a prompt on "
                    "their phone to enter M-Pesa PIN."
                ),
                status=http_status.HTTP_201_CREATED,
            )

        else:
            # STK Push failed — mark attempt as failed
            # Payment stays PENDING — retry logic in Phase 6 will handle it
            attempt.status = PaymentAttempt.Status.FAILED
            attempt.response_payload = stk_result["response_payload"]
            attempt.error_message = stk_result["error_message"]
            attempt.save()

            # Mark payment failed immediately (retry will re-open it)
            payment.status = Payment.Status.FAILED
            payment.save()

            logger.error(
                f"STK Push failed | reference={payment.reference} | "
                f"reason={stk_result['error_message']}"
            )

            return error_response(
                message=f"Failed to initiate M-Pesa payment: {stk_result['error_message']}",
                status=http_status.HTTP_502_BAD_GATEWAY,
            )

    def _get_ip(self, request):
        forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if forwarded_for:
            return forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR')


class PaymentDetailView(APIView):
    """
    GET /api/v1/payments/<reference>/

    Returns full payment status including all attempts.
    This is what Tixora/Scott poll to check if payment succeeded.
    """

    def get(self, request, reference):
        payment = get_object_or_404(
            Payment.objects.prefetch_related('attempts'),
            reference=reference,
        )
        return success_response(
            data=PaymentSerializer(payment).data,
            message="Payment retrieved successfully.",
        )


class PaymentListView(APIView):
    """
    GET /api/v1/payments/

    Lists payments with optional filters.
    Supports: ?source_system=tixora&status=success&external_reference=ORDER_123

    Used by dashboards, reconciliation scripts, and debugging.
    """

    def get(self, request):
        queryset = Payment.objects.prefetch_related('attempts').all()

        # ── Optional filters ─────────────────────────────────────────────────
        source_system = request.query_params.get('source_system')
        status_filter = request.query_params.get('status')
        external_reference = request.query_params.get('external_reference')
        phone_number = request.query_params.get('phone_number')

        if source_system:
            queryset = queryset.filter(source_system=source_system)

        if status_filter:
            valid_statuses = [s.value for s in Payment.Status]
            if status_filter not in valid_statuses:
                return error_response(
                    message=f"Invalid status filter. Choose from: {valid_statuses}",
                )
            queryset = queryset.filter(status=status_filter)

        if external_reference:
            queryset = queryset.filter(external_reference=external_reference)

        if phone_number:
            queryset = queryset.filter(phone_number=phone_number)

        # ── Pagination (manual, simple) ──────────────────────────────────────
        # DRF pagination classes add complexity — for now, cap at 100
        # and add cursor-based pagination in a later phase if needed
        queryset = queryset[:100]

        serializer = PaymentSummarySerializer(queryset, many=True)
        return success_response(
            data={
                "count": len(serializer.data),
                "payments": serializer.data,
            },
            message="Payments retrieved successfully.",
        )