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

from .models import Payment, PaymentAttempt, CallbackLog
from .callback_processor import CallbackProcessor
from .status_normalizer import StatusNormalizerFactory


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
            # Normalize the initiation failure
            normalizer = StatusNormalizerFactory.get('mpesa')
            normalized = normalizer.normalize_stk_initiation_failure(
                error_message=stk_result["error_message"]
            )

            attempt.status           = PaymentAttempt.Status.FAILED
            attempt.response_payload = stk_result["response_payload"]
            attempt.error_message    = normalized.reason
            attempt.save(update_fields=['status', 'response_payload', 'error_message'])

            # Schedule retry or permanently fail based on normalizer decision
            from .retry_service import RetryService
            retry_service = RetryService()

            if normalized.is_retryable:
                retry_service.schedule_retry(payment)
            else:
                retry_service._mark_permanently_failed(payment)

            logger.error(
                f"STK Push initiation failed | reference={payment.reference} | "
                f"retryable={normalized.is_retryable} | reason={normalized.reason}"
            )

            return error_response(
                message=normalized.reason,
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
        
        
class MpesaCallbackView(APIView):
    """
    POST /api/v1/payments/callback/

    Receives payment results from M-Pesa Daraja.

    CRITICAL RULES for this endpoint:
    1. Always return HTTP 200 — non-200 makes M-Pesa retry indefinitely
    2. Write raw payload to DB FIRST before any processing
    3. Never trust the payload — validate structure before using it
    4. Process must be idempotent — safe to call multiple times
    """

    # M-Pesa posts to this endpoint — Django's CSRF must not block it
    # We'll add IP-based security in Phase 9 instead
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        # ── Step 1: Write raw payload immediately ────────────────────────────
        # Do this BEFORE anything else. If we crash after this line,
        # we still have the data and can reprocess.
        ip_address = self._get_ip(request)

        callback_log = CallbackLog.objects.create(
            raw_payload=request.data,
            ip_address=ip_address,
            processed=False,
        )

        logger.info(
            f"Callback received | CallbackLog.id={callback_log.id} | "
            f"ip={ip_address}"
        )

        # ── Step 2: Process the callback ─────────────────────────────────────
        processor = CallbackProcessor()
        success, message = processor.process(callback_log)

        if success:
            logger.info(f"Callback processed successfully: {message}")
        else:
            logger.error(f"Callback processing failed: {message}")

        # ── Step 3: Always return 200 to M-Pesa ──────────────────────────────
        # Even if processing failed internally, we return 200.
        # Why? If we return 4xx/5xx, M-Pesa will retry the same callback
        # repeatedly — creating more noise. We've stored it safely in
        # CallbackLog and can reprocess it manually or via a scheduled job.
        return Response(
            {"ResultCode": 0, "ResultDesc": "Accepted"},
            status=http_status.HTTP_200_OK,
        )

    def _get_ip(self, request):
        forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if forwarded_for:
            return forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR')   
    
class PaymentStatusView(APIView):
    """
    GET /api/v1/payments/<reference>/status/

    Minimal status check — the most called endpoint in the system.
    Returns only what external systems need to act on:
    - What is the status?
    - Why did it fail (if failed)?
    - Is a retry coming?

    Designed to be called in a polling loop by Tixora/Scott
    while waiting for M-Pesa confirmation.
    """

    def get(self, request, reference):
        payment = get_object_or_404(Payment, reference=reference)

        # Build a minimal, flat response — no nested attempts
        data = {
            "reference": str(payment.reference),
            "external_reference": payment.external_reference,
            "source_system": payment.source_system,
            "status": payment.status,
            "amount": str(payment.amount),
            "retry_count": payment.retry_count,
            "next_retry_at": (
                payment.next_retry_at.isoformat()
                if payment.next_retry_at else None
            ),
        }

        # Include failure reason from latest attempt if failed
        if payment.status == Payment.Status.FAILED:
            latest_attempt = (
                payment.attempts
                .filter(status=PaymentAttempt.Status.FAILED)
                .order_by('-attempt_number')
                .first()
            )
            if latest_attempt:
                data["failure_reason"] = latest_attempt.error_message

        # Include a consumer-friendly status message
        data["message"] = self._status_message(payment)

        return success_response(
            data=data,
            message="Payment status retrieved.",
        )

    def _status_message(self, payment):
        """
        Human-readable status message for the consumer system.
        No M-Pesa codes, no technical jargon.
        """
        messages = {
            Payment.Status.PENDING: (
                "Payment is pending. Waiting for customer to complete M-Pesa prompt."
                if not payment.next_retry_at
                else f"Previous attempt failed. Retry scheduled."
            ),
            Payment.Status.SUCCESS: "Payment completed successfully.",
            Payment.Status.FAILED:  "Payment failed. No further retries will be made.",
        }
        return messages.get(payment.status, "Unknown status.")         