import logging
from django.db import transaction
from .models import Payment, PaymentAttempt, CallbackLog

logger = logging.getLogger(__name__)


class CallbackProcessor:
    """
    Handles everything that happens after a raw M-Pesa callback
    has been written to CallbackLog.

    Separated from the view so it can be:
    - Tested independently
    - Called from a retry job (Phase 6)
    - Called manually to replay failed callbacks
    """

    # M-Pesa result codes
    SUCCESS_CODE = 0

    # These codes mean the customer actively cancelled or has
    # a real problem — don't retry, fail permanently
    PERMANENT_FAILURE_CODES = {
        1032: "Request cancelled by user",
        1037: "DS timeout — user cannot be reached",
        2001: "Wrong PIN entered",
        1001: "Insufficient funds",
    }

    def process(self, callback_log):
        """
        Main entry point. Takes a CallbackLog instance.
        Returns (success: bool, message: str).

        Uses a database transaction so partial updates
        never leave the DB in an inconsistent state.
        """
        if callback_log.processed:
            logger.info(
                f"CallbackLog {callback_log.id} already processed — skipping."
            )
            return True, "Already processed."

        try:
            with transaction.atomic():
                return self._process_inner(callback_log)

        except Exception as e:
            # Record the error but don't re-raise
            # The view should still return 200 to M-Pesa
            # (returning non-200 makes M-Pesa retry endlessly)
            error_msg = f"Callback processing error: {str(e)}"
            logger.error(
                f"Failed to process CallbackLog {callback_log.id}: {str(e)}",
                exc_info=True,
            )
            callback_log.processing_error = error_msg
            callback_log.save(update_fields=['processing_error'])
            return False, error_msg

    def _process_inner(self, callback_log):
        """Core processing logic — runs inside a transaction."""

        raw = callback_log.raw_payload

        # ── Parse M-Pesa callback structure ──────────────────────────────────
        # M-Pesa wraps everything in Body > stkCallback
        try:
            stk_callback = raw['Body']['stkCallback']
        except (KeyError, TypeError):
            msg = "Malformed callback — missing Body.stkCallback"
            logger.error(msg)
            callback_log.processing_error = msg
            callback_log.save(update_fields=['processing_error'])
            return False, msg

        checkout_request_id = stk_callback.get('CheckoutRequestID')
        result_code = stk_callback.get('ResultCode')
        result_desc = stk_callback.get('ResultDesc', '')

        if checkout_request_id is None or result_code is None:
            msg = "Malformed callback — missing CheckoutRequestID or ResultCode"
            logger.error(msg)
            callback_log.processing_error = msg
            callback_log.save(update_fields=['processing_error'])
            return False, msg

        # ── Update CallbackLog with parsed fields ─────────────────────────────
        callback_log.checkout_request_id = checkout_request_id
        callback_log.save(update_fields=['checkout_request_id'])

        # ── Find matching PaymentAttempt ──────────────────────────────────────
        try:
            attempt = PaymentAttempt.objects.select_related('payment').get(
                mpesa_checkout_request_id=checkout_request_id
            )
        except PaymentAttempt.DoesNotExist:
            msg = (
                f"No PaymentAttempt found for "
                f"CheckoutRequestID={checkout_request_id}"
            )
            logger.error(msg)
            callback_log.processing_error = msg
            callback_log.save(update_fields=['processing_error'])
            return False, msg

        payment = attempt.payment

        # ── Link CallbackLog to the attempt ───────────────────────────────────
        callback_log.payment_attempt = attempt
        callback_log.save(update_fields=['payment_attempt'])

        # ── Determine outcome ─────────────────────────────────────────────────
        result_code = int(result_code)

        if result_code == self.SUCCESS_CODE:
            return self._handle_success(callback_log, attempt, payment, stk_callback)
        else:
            return self._handle_failure(
                callback_log, attempt, payment, result_code, result_desc
            )

    def _handle_success(self, callback_log, attempt, payment, stk_callback):
        """Payment confirmed by customer. Update records to success."""

        # Extract metadata from CallbackMetadata items list
        metadata = self._extract_metadata(stk_callback)

        mpesa_receipt = metadata.get('MpesaReceiptNumber')
        transaction_date = metadata.get('TransactionDate')
        amount_paid = metadata.get('Amount')

        logger.info(
            f"Payment SUCCESS | reference={payment.reference} | "
            f"receipt={mpesa_receipt} | amount={amount_paid}"
        )

        # Update attempt
        attempt.status = PaymentAttempt.Status.SUCCESS
        attempt.response_payload = {
            **( attempt.response_payload or {} ),
            "callback": stk_callback,
            "mpesa_receipt": mpesa_receipt,
            "transaction_date": str(transaction_date),
            "amount_confirmed": str(amount_paid),
        }
        attempt.save(update_fields=['status', 'response_payload'])

        # Update payment
        payment.status = Payment.Status.SUCCESS
        payment.save(update_fields=['status', 'updated_at'])

        # Mark callback as processed
        callback_log.processed = True
        callback_log.save(update_fields=['processed'])

        return True, f"Payment {payment.reference} marked SUCCESS."

    def _handle_failure(self, callback_log, attempt, payment, result_code, result_desc):
        """Payment failed or was cancelled. Determine if permanent."""

        is_permanent = result_code in self.PERMANENT_FAILURE_CODES
        failure_reason = self.PERMANENT_FAILURE_CODES.get(
            result_code, result_desc
        )

        logger.warning(
            f"Payment FAILED | reference={payment.reference} | "
            f"code={result_code} | reason={failure_reason} | "
            f"permanent={is_permanent}"
        )

        # Update attempt
        attempt.status = PaymentAttempt.Status.FAILED
        attempt.error_message = f"[{result_code}] {failure_reason}"
        attempt.save(update_fields=['status', 'error_message'])

        # Only mark payment as permanently failed for non-retryable errors
        # For retryable errors, Phase 6 retry logic will re-open the payment
        if is_permanent:
            payment.status = Payment.Status.FAILED
            payment.save(update_fields=['status', 'updated_at'])
            logger.info(
                f"Payment {payment.reference} marked FAILED permanently — "
                f"code {result_code} is not retryable."
            )
        else:
            # Keep payment PENDING — retry logic will pick it up
            logger.info(
                f"Payment {payment.reference} attempt failed — "
                f"kept PENDING for retry (code {result_code})."
            )

        # Mark callback processed regardless
        callback_log.processed = True
        callback_log.save(update_fields=['processed'])

        return True, (
            f"Payment {payment.reference} attempt FAILED. "
            f"Permanent: {is_permanent}"
        )

    def _extract_metadata(self, stk_callback):
        """
        M-Pesa success callbacks bury metadata in a list of name/value dicts:
        
        "CallbackMetadata": {
            "Item": [
                {"Name": "Amount", "Value": 1.0},
                {"Name": "MpesaReceiptNumber", "Value": "PH7..."},
                ...
            ]
        }
        
        This flattens that into a clean dict: {"Amount": 1.0, ...}
        """
        result = {}
        try:
            items = stk_callback['CallbackMetadata']['Item']
            for item in items:
                name = item.get('Name')
                value = item.get('Value')
                if name:
                    result[name] = value
        except (KeyError, TypeError):
            logger.warning("Could not extract CallbackMetadata — may be a failure callback.")
        return result