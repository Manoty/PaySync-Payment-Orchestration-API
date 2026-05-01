import logging
from rest_framework.views import APIView
from rest_framework import status as http_status
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from .health import HealthChecker
from rest_framework.decorators import api_view

from .models import Payment, PaymentAttempt, CallbackLog
from .serializers import (
    InitiatePaymentSerializer,
    PaymentSerializer,
    PaymentSummarySerializer,
)
from .utils import success_response, error_response
from .mpesa_service import MpesaService
from .callback_processor import CallbackProcessor
from .status_normalizer import StatusNormalizerFactory
from .retry_service import RetryService

logger = logging.getLogger(__name__)

class InitiatePaymentView(APIView):

    def post(self, request):
        serializer = InitiatePaymentSerializer(data=request.data)

        if not serializer.is_valid():
            return error_response(
                message="Invalid payment data.",
                errors=serializer.errors,
            )

        validated = serializer.validated_data

        # Idempotency
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

        payment = Payment.objects.create(
            amount=validated['amount'],
            phone_number=validated['phone_number'],
            external_reference=validated['external_reference'],
            source_system=validated['source_system'],
            status=Payment.Status.PENDING,
            provider=Payment.Provider.MPESA,
        )

        attempt = PaymentAttempt.objects.create(
            payment=payment,
            attempt_number=1,
        )

        mpesa = MpesaService()
        stk_result = mpesa.initiate_stk_push(payment, attempt)

        if stk_result["success"]:
            attempt.mpesa_checkout_request_id = stk_result["checkout_request_id"]
            attempt.response_payload = stk_result["response_payload"]
            attempt.save()

            return success_response(
                data=PaymentSerializer(payment).data,
                message="STK Push sent to customer phone.",
                status=http_status.HTTP_201_CREATED,
            )

        # --- FAILURE PATH (normalized + retry aware) ---
        normalizer = StatusNormalizerFactory.get('mpesa')
        normalized = normalizer.normalize_stk_initiation_failure(
            error_message=stk_result["error_message"]
        )

        attempt.status = PaymentAttempt.Status.FAILED
        attempt.response_payload = stk_result["response_payload"]
        attempt.error_message = normalized.reason
        attempt.save()

        retry_service = RetryService()

        if normalized.is_retryable:
            retry_service.schedule_retry(payment)
        else:
            retry_service.mark_permanently_failed(payment)

        return error_response(
            message=normalized.reason,
            status=http_status.HTTP_502_BAD_GATEWAY,
        )
        
class PaymentDetailView(APIView):

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

    def get(self, request):
        queryset = Payment.objects.prefetch_related('attempts').all()[:100]

        serializer = PaymentSummarySerializer(queryset, many=True)
        return success_response(
            data={
                "count": len(serializer.data),
                "payments": serializer.data,
            },
            message="Payments retrieved successfully.",
        )
        

class MpesaCallbackView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        ip_address = request.META.get('REMOTE_ADDR')

        callback_log = CallbackLog.objects.create(
            raw_payload=request.data,
            ip_address=ip_address,
            processed=False,
        )

        processor = CallbackProcessor()
        processor.process(callback_log)

        return Response(
            {"ResultCode": 0, "ResultDesc": "Accepted"},
            status=http_status.HTTP_200_OK,
        )
        

class PaymentStatusView(APIView):

    def get(self, request, reference):
        payment = get_object_or_404(Payment, reference=reference)

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

        if payment.status == Payment.Status.FAILED:
            latest_attempt = (
                payment.attempts
                .filter(status=PaymentAttempt.Status.FAILED)
                .order_by('-attempt_number')
                .first()
            )
            if latest_attempt:
                data["failure_reason"] = latest_attempt.error_message

        return success_response(
            data=data,
            message="Payment status retrieved.",
        )
        

class HealthCheckView(APIView):
    """
    GET /api/v1/health/

    Public endpoint — no API key required.
    Returns 200 if healthy, 503 if unhealthy.

    Used by:
    - Load balancers to determine if instance should receive traffic
    - Monitoring systems (UptimeRobot, Pingdom, etc.)
    - Your own peace of mind
    """
    authentication_classes = []
    permission_classes     = []

    def get(self, request):
        checker = HealthChecker()
        report  = checker.run_all_checks()

        http_status_code = (
            http_status.HTTP_200_OK
            if report['status'] == 'healthy'
            else http_status.HTTP_503_SERVICE_UNAVAILABLE
        )

        return Response(report, status=http_status_code)                                        