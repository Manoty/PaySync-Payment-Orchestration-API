import logging
from datetime import timedelta
from django.utils import timezone
from django.db import transaction

from .models import Payment, PaymentAttempt
from .mpesa_service import MpesaService, MpesaError

logger = logging.getLogger(__name__)


# ── Retry Schedule ────────────────────────────────────────────────────────────
# retry_count → minutes to wait before next attempt
# Attempt 1 failed → wait 2 min  → Attempt 2
# Attempt 2 failed → wait 5 min  → Attempt 3
# Attempt 3 failed → wait 10 min → Attempt 4 (final)
RETRY_DELAY_MINUTES = {
    1: 2,
    2: 5,
    3: 10,
}

# Result codes that should NEVER be retried
PERMANENT_FAILURE_CODES = {1032, 1037, 2001, 1001}


class RetryService:
    """
    Handles scheduling and executing payment retries.

    Two responsibilities:
    1. schedule_retry(payment) — called after a failed attempt
       Decides IF and WHEN to retry. Updates next_retry_at.

    2. process_due_retries() — called by a periodic job
       Finds payments due for retry and executes them.
    """

    def schedule_retry(self, payment, failed_result_code=None):
        """
        Called immediately after a failed payment attempt.

        Decides:
        - Is this failure retryable?
        - Have we exceeded max attempts?
        - When should the next attempt be?

        Args:
            payment: Payment instance
            failed_result_code: M-Pesa ResultCode from callback (int or None)

        Returns:
            (scheduled: bool, reason: str)
        """

        # ── Check: permanent failure code ────────────────────────────────────
        if failed_result_code in PERMANENT_FAILURE_CODES:
            reason = (
                f"ResultCode {failed_result_code} is a permanent failure — "
                f"not scheduling retry."
            )
            logger.info(f"[{payment.reference}] {reason}")
            self._mark_permanently_failed(payment)
            return False, reason

        # ── Check: max retries reached ────────────────────────────────────────
        if payment.retry_count >= payment.MAX_RETRY_ATTEMPTS:
            reason = (
                f"Max retry attempts ({payment.MAX_RETRY_ATTEMPTS}) reached — "
                f"marking permanently failed."
            )
            logger.warning(f"[{payment.reference}] {reason}")
            self._mark_permanently_failed(payment)
            return False, reason

        # ── Schedule next retry ───────────────────────────────────────────────
        # retry_count tells us which attempt just failed
        # Use that to look up the delay for the NEXT attempt
        current_attempt = payment.retry_count + 1  # attempts start at 1
        delay_minutes = RETRY_DELAY_MINUTES.get(current_attempt, 10)
        next_retry_at = timezone.now() + timedelta(minutes=delay_minutes)

        payment.status        = Payment.Status.PENDING
        payment.next_retry_at = next_retry_at
        payment.retry_count   = payment.retry_count + 1
        payment.is_processing = False
        payment.save(update_fields=[
            'status', 'next_retry_at', 'retry_count',
            'is_processing', 'updated_at'
        ])

        reason = (
            f"Retry {payment.retry_count}/{payment.MAX_RETRY_ATTEMPTS} "
            f"scheduled for {next_retry_at.strftime('%Y-%m-%d %H:%M:%S')} "
            f"(in {delay_minutes} min)."
        )
        logger.info(f"[{payment.reference}] {reason}")
        return True, reason

    def process_due_retries(self):
        """
        Finds all payments due for retry and attempts them.

        Designed to be called every minute by a scheduled job.
        Uses select_for_update() to prevent concurrent workers
        from picking up the same payment.

        Returns:
            dict with counts: processed, succeeded, failed, errors
        """
        now = timezone.now()
        stats = {"processed": 0, "succeeded": 0, "failed": 0, "errors": 0}

        # ── Find due payments ─────────────────────────────────────────────────
        # status=pending ensures we don't retry already-successful payments
        # next_retry_at__lte=now means the wait window has passed
        # is_processing=False prevents duplicate concurrent execution
        due_payments = Payment.objects.filter(
            status=Payment.Status.PENDING,
            next_retry_at__lte=now,
            is_processing=False,
            next_retry_at__isnull=False,
        ).order_by('next_retry_at')

        count = due_payments.count()
        if count == 0:
            logger.debug("No payments due for retry.")
            return stats

        logger.info(f"Found {count} payment(s) due for retry.")

        for payment in due_payments:
            try:
                result = self._execute_retry(payment)
                stats["processed"] += 1
                if result:
                    stats["succeeded"] += 1
                else:
                    stats["failed"] += 1
            except Exception as e:
                stats["errors"] += 1
                logger.error(
                    f"Unexpected error retrying payment {payment.reference}: {e}",
                    exc_info=True,
                )

        logger.info(
            f"Retry run complete: {stats['processed']} processed, "
            f"{stats['succeeded']} succeeded, "
            f"{stats['failed']} failed, "
            f"{stats['errors']} errors."
        )
        return stats

    def _execute_retry(self, payment):
        """
        Executes a single retry attempt for one payment.

        Uses a transaction + select_for_update to lock the payment row
        so concurrent workers can't double-process it.

        Returns True if STK Push was accepted, False otherwise.
        """
        with transaction.atomic():
            # Lock this row for the duration of this block
            # If another worker already grabbed it, this will wait
            # until the lock releases, then see is_processing=True and skip
            locked_payment = (
                Payment.objects
                .select_for_update(skip_locked=True)
                .filter(
                    id=payment.id,
                    status=Payment.Status.PENDING,
                    is_processing=False,
                )
                .first()
            )

            if not locked_payment:
                logger.info(
                    f"Payment {payment.reference} already being processed "
                    f"or status changed — skipping."
                )
                return False

            # Claim this payment for processing
            locked_payment.is_processing = True
            locked_payment.next_retry_at = None
            locked_payment.save(update_fields=['is_processing', 'next_retry_at'])

        # ── Outside transaction: do the STK Push ─────────────────────────────
        # We don't hold the DB lock during the HTTP call to Daraja
        # (that could take 30 seconds — holding a lock that long is wrong)
        attempt_number = (
            PaymentAttempt.objects
            .filter(payment=locked_payment)
            .count()
        ) + 1

        attempt = PaymentAttempt.objects.create(
            payment=locked_payment,
            attempt_number=attempt_number,
            status=PaymentAttempt.Status.INITIATED,
        )

        logger.info(
            f"Executing retry | reference={locked_payment.reference} | "
            f"attempt={attempt_number} | retry_count={locked_payment.retry_count}"
        )

        mpesa = MpesaService()
        stk_result = mpesa.initiate_stk_push(locked_payment, attempt)

        if stk_result["success"]:
            attempt.mpesa_checkout_request_id = stk_result["checkout_request_id"]
            attempt.response_payload          = stk_result["response_payload"]
            attempt.status                    = PaymentAttempt.Status.INITIATED
            attempt.save(update_fields=[
                'mpesa_checkout_request_id', 'response_payload', 'status'
            ])

            # Release processing lock — callback will update final status
            locked_payment.is_processing = False
            locked_payment.save(update_fields=['is_processing'])

            logger.info(
                f"Retry STK Push accepted | reference={locked_payment.reference} | "
                f"checkout_id={stk_result['checkout_request_id']}"
            )
            return True

        else:
            # STK Push itself failed — schedule another retry or give up
            attempt.status        = PaymentAttempt.Status.FAILED
            attempt.response_payload = stk_result["response_payload"]
            attempt.error_message = stk_result["error_message"]
            attempt.save(update_fields=['status', 'response_payload', 'error_message'])

            locked_payment.is_processing = False
            locked_payment.save(update_fields=['is_processing'])

            logger.warning(
                f"Retry STK Push failed | reference={locked_payment.reference} | "
                f"reason={stk_result['error_message']}"
            )

            # Schedule another retry or give up permanently
            self.schedule_retry(locked_payment)
            return False

    def _mark_permanently_failed(self, payment):
        """Mark payment as permanently failed — no more retries."""
        payment.status        = Payment.Status.FAILED
        payment.is_processing = False
        payment.next_retry_at = None
        payment.save(update_fields=[
            'status', 'is_processing', 'next_retry_at', 'updated_at'
        ])
        logger.warning(
            f"Payment {payment.reference} permanently FAILED after "
            f"{payment.retry_count} retry attempt(s)."
        )