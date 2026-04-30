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
                extra={"errors": serializer.errors, "ip": self._get_ip(request)}
            )
            return error_response(
                message="Invalid payment data.",
                errors=serializer.errors,
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        validated = serializer.validated_data

        # ── Idempotency check ────────────────────────────────────────────────
        # If the same external_reference + source_system already has a
        # PENDING or SUCCESS payment, don't create a duplicate.
        existing = Payment.objects.filter(
            external_reference=validated['external_reference'],
            source_system=validated['source_system'],
            status__in=[Payment.Status.PENDING, Payment.Status.SUCCESS],
        ).first()

        if existing:
            logger.info(
                f"Duplicate payment request blocked: "
                f"{validated['source_system']} / {validated['external_reference']}"
            )
            return success_response(
                data=PaymentSerializer(existing).data,
                message="Payment already exists for this reference.",
                status=http_status.HTTP_200_OK,
            )

        # ── Create Payment ───────────────────────────────────────────────────
        payment = Payment.objects.create(
            amount=validated['amount'],
            phone_number=validated['phone_number'],
            external_reference=validated['external_reference'],
            source_system=validated['source_system'],
            status=Payment.Status.PENDING,
            provider=Payment.Provider.MPESA,
        )

        # ── Create first PaymentAttempt ──────────────────────────────────────
        # attempt_number=1 because this is the first try
        PaymentAttempt.objects.create(
            payment=payment,
            attempt_number=1,
            status=PaymentAttempt.Status.INITIATED,
        )

        logger.info(
            f"Payment initiated: {payment.reference} | "
            f"{payment.source_system} | KES {payment.amount}"
        )

        # Phase 4: STK Push will be triggered here
        # mpesa_service.initiate_stk_push(payment)

        return success_response(
            data=PaymentSerializer(payment).data,
            message="Payment initiated successfully. Awaiting M-Pesa confirmation.",
            status=http_status.HTTP_201_CREATED,
        )

    def _get_ip(self, request):
        """Extract real IP, accounting for reverse proxies."""
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