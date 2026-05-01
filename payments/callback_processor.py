# Updated payments/callback_processor.py

import logging
from django.db import transaction
from .models import Payment, PaymentAttempt, CallbackLog
from .retry_service import RetryService
from .status_normalizer import StatusNormalizerFactory

logger = logging.getLogger(__name__)


class CallbackProcessor:
    """
    Handles raw M-Pesa callbacks.
    Uses StatusNormalizerFactory to translate provider codes —
    never interprets result codes directly.
    """

    def process(self, callback_log):
        if callback_log.processed:
            logger.info(f"CallbackLog {callback_log.id} already processed — skipping.")
            return True, "Already processed."

        try:
            with transaction.atomic():
                return self._process_inner(callback_log)
        except Exception as e:
            error_msg = f"Callback processing error: {str(e)}"
            logger.error(
                f"Failed to process CallbackLog {callback_log.id}: {str(e)}",
                exc_info=True,
            )
            callback_log.processing_error = error_msg
            callback_log.save(update_fields=['processing_error'])
            return False, error_msg

    def _process_inner(self, callback_log):
        raw = callback_log.raw_payload

        # ── Parse callback structure ──────────────────────────────────────────
        try:
            stk_callback = raw['Body']['stkCallback']
        except (KeyError, TypeError):
            msg = "Malformed callback — missing Body.stkCallback"
            logger.error(msg)
            callback_log.processing_error = msg
            callback_log.save(update_fields=['processing_error'])
            return False, msg

        checkout_request_id = stk_callback.get('CheckoutRequestID')
        result_code         = stk_callback.get('ResultCode')
        result_desc         = stk_callback.get('ResultDesc', '')

        if checkout_request_id is None or result_code is None:
            msg = "Malformed callback — missing CheckoutRequestID or ResultCode"
            logger.error(msg)
            callback_log.processing_error = msg
            callback_log.save(update_fields=['processing_error'])
            return False, msg

        callback_log.checkout_request_id = checkout_request_id
        callback_log.save(update_fields=['checkout_request_id'])

        # ── Find matching PaymentAttempt ──────────────────────────────────────
        try:
            attempt = PaymentAttempt.objects.select_related('payment').get(
                mpesa_checkout_request_id=checkout_request_id
            )
        except PaymentAttempt.DoesNotExist:
            msg = f"No PaymentAttempt for CheckoutRequestID={checkout_request_id}"
            logger.error(msg)
            callback_log.processing_error = msg
            callback_log.save(update_fields=['processing_error'])
            return False, msg

        payment = attempt.payment

        callback_log.payment_attempt = attempt
        callback_log.save(update_fields=['payment_attempt'])

        # ── Normalize status — no raw codes beyond this point ─────────────────
        normalizer = StatusNormalizerFactory.get(payment.provider)
        normalized = normalizer.normalize_callback_result(
            result_code=int(result_code),
            result_desc=result_desc,
        )

        logger.info(
            f"Normalized status | reference={payment.reference} | "
            f"provider_code={result_code} → paysync_status={normalized.status} | "
            f"retryable={normalized.is_retryable} | reason={normalized.reason}"
        )

        # ── Apply normalized outcome ──────────────────────────────────────────
        if normalized.status == 'success':
            return self._apply_success(
                callback_log, attempt, payment, stk_callback, normalized
            )
        else:
            return self._apply_failure(
                callback_log, attempt, payment, normalized
            )

    def _apply_success(self, callback_log, attempt, payment, stk_callback, normalized):
        """Apply a normalized success outcome."""
        metadata        = self._extract_metadata(stk_callback)
        mpesa_receipt   = metadata.get('MpesaReceiptNumber')
        transaction_date = metadata.get('TransactionDate')
        amount_paid     = metadata.get('Amount')

        logger.info(
            f"Applying SUCCESS | reference={payment.reference} | "
            f"receipt={mpesa_receipt} | amount={amount_paid}"
        )

        attempt.status = PaymentAttempt.Status.SUCCESS
        attempt.response_payload = {
            **(attempt.response_payload or {}),
            "callback": stk_callback,
            "normalized_status": normalized.status,
            "normalized_reason": normalized.reason,
            "mpesa_receipt": mpesa_receipt,
            "transaction_date": str(transaction_date),
            "amount_confirmed": str(amount_paid),
        }
        attempt.save(update_fields=['status', 'response_payload'])

        payment.status = Payment.Status.SUCCESS
        payment.save(update_fields=['status', 'updated_at'])

        callback_log.processed = True
        callback_log.save(update_fields=['processed'])

        return True, f"Payment {payment.reference} → SUCCESS."

    def _apply_failure(self, callback_log, attempt, payment, normalized):
        """Apply a normalized failure outcome and schedule retry if appropriate."""
        logger.warning(
            f"Applying FAILURE | reference={payment.reference} | "
            f"permanent={normalized.is_permanent} | reason={normalized.reason}"
        )

        attempt.status = PaymentAttempt.Status.FAILED
        attempt.error_message = (
            f"[{normalized.provider_code}] {normalized.reason}"
        )
        attempt.response_payload = {
            **(attempt.response_payload or {}),
            "normalized_status": normalized.status,
            "normalized_reason": normalized.reason,
            "is_retryable": normalized.is_retryable,
            "provider_code": normalized.provider_code,
        }
        attempt.save(update_fields=['status', 'error_message', 'response_payload'])

        callback_log.processed = True
        callback_log.save(update_fields=['processed'])

        # ── Retry decision driven by normalizer — no codes here ───────────────
        retry_service = RetryService()
        if normalized.is_retryable:
            scheduled, reason = retry_service.schedule_retry(
                payment,
                failed_result_code=normalized.provider_code,
            )
        else:
            # Permanent — bypass schedule_retry, fail immediately
            retry_service._mark_permanently_failed(payment)
            scheduled = False
            reason = normalized.reason

        logger.info(
            f"Post-failure | reference={payment.reference} | "
            f"retry_scheduled={scheduled} | reason={reason}"
        )

        return True, f"Attempt FAILED. Retry: {scheduled}. {reason}"

    def _extract_metadata(self, stk_callback):
        result = {}
        try:
            items = stk_callback['CallbackMetadata']['Item']
            for item in items:
                name = item.get('Name')
                value = item.get('Value')
                if name:
                    result[name] = value
        except (KeyError, TypeError):
            logger.warning("Could not extract CallbackMetadata.")
        return result