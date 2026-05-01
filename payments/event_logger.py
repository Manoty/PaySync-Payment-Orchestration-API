"""
Structured event logger for all payment lifecycle events.

Every meaningful state change in a payment's life is logged
as a discrete event with full context.

Why a separate module?
- Consistent field names across all payment events
- Easy to forward to external systems (Datadog, Mixpanel)
- Searchable: find all events for a single payment reference
- Auditable: reconstruct exactly what happened and when
"""

import logging
from decimal import Decimal

logger = logging.getLogger('payments')


class PaymentEventLogger:
    """
    Logs payment lifecycle events with consistent structure.
    Every method corresponds to one meaningful payment event.
    """

    @staticmethod
    def _base_context(payment) -> dict:
        """Fields present on every payment event."""
        return {
            "reference":          str(payment.reference),
            "external_reference": payment.external_reference,
            "source_system":      payment.source_system,
            "amount":             float(payment.amount),
            "phone_number":       payment.phone_number,
            "provider":           payment.provider,
            "status":             payment.status,
            "retry_count":        payment.retry_count,
        }

    # ── Initiation events ──────────────────────────────────────────────────────

    @classmethod
    def payment_created(cls, payment):
        logger.info(
            "Payment created",
            extra={
                **cls._base_context(payment),
                "event": "payment_created",
            }
        )

    @classmethod
    def stk_push_sent(cls, payment, attempt, checkout_request_id: str):
        logger.info(
            "STK Push sent to customer",
            extra={
                **cls._base_context(payment),
                "event":               "stk_push_sent",
                "attempt_number":      attempt.attempt_number,
                "checkout_request_id": checkout_request_id,
            }
        )

    @classmethod
    def stk_push_failed(cls, payment, attempt, error_message: str):
        logger.error(
            "STK Push initiation failed",
            extra={
                **cls._base_context(payment),
                "event":          "stk_push_failed",
                "attempt_number": attempt.attempt_number,
                "error_message":  error_message,
            }
        )

    @classmethod
    def duplicate_payment_blocked(cls, payment, source_system: str, external_ref: str):
        logger.info(
            "Duplicate payment request blocked",
            extra={
                **cls._base_context(payment),
                "event":              "duplicate_blocked",
                "requested_source":   source_system,
                "requested_ext_ref":  external_ref,
            }
        )

    # ── Callback events ────────────────────────────────────────────────────────

    @classmethod
    def callback_received(cls, callback_log):
        logger.info(
            "M-Pesa callback received",
            extra={
                "event":               "callback_received",
                "callback_log_id":     callback_log.id,
                "ip_address":          callback_log.ip_address,
                "checkout_request_id": callback_log.checkout_request_id,
            }
        )

    @classmethod
    def callback_duplicate(cls, callback_log):
        logger.info(
            "Duplicate callback ignored",
            extra={
                "event":               "callback_duplicate",
                "callback_log_id":     callback_log.id,
                "checkout_request_id": callback_log.checkout_request_id,
            }
        )

    @classmethod
    def callback_unmatched(cls, checkout_request_id: str, ip: str):
        logger.error(
            "Callback received with no matching PaymentAttempt",
            extra={
                "event":               "callback_unmatched",
                "checkout_request_id": checkout_request_id,
                "ip_address":          ip,
            }
        )

    @classmethod
    def callback_malformed(cls, callback_log_id: int, reason: str):
        logger.error(
            "Malformed callback payload",
            extra={
                "event":           "callback_malformed",
                "callback_log_id": callback_log_id,
                "reason":          reason,
            }
        )

    # ── Status change events ───────────────────────────────────────────────────

    @classmethod
    def payment_succeeded(cls, payment, mpesa_receipt: str, amount_confirmed):
        logger.info(
            "Payment confirmed successful",
            extra={
                **cls._base_context(payment),
                "event":            "payment_succeeded",
                "mpesa_receipt":    mpesa_receipt,
                "amount_confirmed": float(amount_confirmed) if amount_confirmed else None,
            }
        )

    @classmethod
    def payment_failed(cls, payment, result_code: int, reason: str, is_permanent: bool):
        level = 'error' if is_permanent else 'warning'
        getattr(logger, level)(
            "Payment attempt failed",
            extra={
                **cls._base_context(payment),
                "event":        "payment_failed",
                "result_code":  result_code,
                "reason":       reason,
                "is_permanent": is_permanent,
            }
        )

    @classmethod
    def payment_permanently_failed(cls, payment):
        logger.error(
            "Payment permanently failed — all retries exhausted",
            extra={
                **cls._base_context(payment),
                "event":       "payment_permanently_failed",
                "retry_count": payment.retry_count,
            }
        )

    # ── Retry events ───────────────────────────────────────────────────────────

    @classmethod
    def retry_scheduled(cls, payment, next_retry_at, delay_minutes: int):
        logger.info(
            "Payment retry scheduled",
            extra={
                **cls._base_context(payment),
                "event":         "retry_scheduled",
                "next_retry_at": str(next_retry_at),
                "delay_minutes": delay_minutes,
            }
        )

    @classmethod
    def retry_executing(cls, payment, attempt_number: int):
        logger.info(
            "Executing payment retry",
            extra={
                **cls._base_context(payment),
                "event":          "retry_executing",
                "attempt_number": attempt_number,
            }
        )

    # ── Security events ────────────────────────────────────────────────────────

    @classmethod
    def invalid_api_key(cls, ip_address: str):
        logger.warning(
            "Invalid API key attempt",
            extra={
                "event":      "invalid_api_key",
                "ip_address": ip_address,
            }
        )

    @classmethod
    def rate_limit_exceeded(cls, client_name: str, source_system: str,
                             count: int, limit: int):
        logger.warning(
            "Rate limit exceeded",
            extra={
                "event":         "rate_limit_exceeded",
                "client_name":   client_name,
                "source_system": source_system,
                "request_count": count,
                "limit":         limit,
            }
        )

    @classmethod
    def suspicious_callback_ip(cls, ip_address: str):
        logger.warning(
            "Callback from unrecognised IP address",
            extra={
                "event":      "suspicious_callback_ip",
                "ip_address": ip_address,
            }
        )

    @classmethod
    def source_system_mismatch(cls, client_system: str, requested_system: str,
                                ip_address: str):
        logger.warning(
            "source_system mismatch — possible misconfiguration or abuse",
            extra={
                "event":              "source_system_mismatch",
                "client_system":      client_system,
                "requested_system":   requested_system,
                "ip_address":         ip_address,
            }
        )

    # ── Critical alerts ────────────────────────────────────────────────────────

    @classmethod
    def mpesa_config_error(cls, error_message: str):
        """
        CRITICAL — Daraja credentials are wrong.
        All STK Pushes will fail until this is fixed.
        """
        logger.critical(
            "M-Pesa configuration error — ALL payments will fail",
            extra={
                "event":         "mpesa_config_error",
                "error_message": error_message,
                "action":        "Check MPESA_CONSUMER_KEY, MPESA_CONSUMER_SECRET, MPESA_PASSKEY",
            }
        )

    @classmethod
    def high_failure_rate(cls, failed_count: int, total_count: int,
                           window_minutes: int):
        """
        CRITICAL — Too many payments failing in a short window.
        Possible M-Pesa outage or Daraja configuration issue.
        """
        rate = (failed_count / total_count * 100) if total_count else 0
        logger.critical(
            "High payment failure rate detected",
            extra={
                "event":          "high_failure_rate",
                "failed_count":   failed_count,
                "total_count":    total_count,
                "failure_rate":   f"{rate:.1f}%",
                "window_minutes": window_minutes,
                "action":         "Check M-Pesa status at status.safaricom.co.ke",
            }
        )