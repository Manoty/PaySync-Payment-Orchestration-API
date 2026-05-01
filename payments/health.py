import logging
import time
from django.db import connection, OperationalError
from django.conf import settings
from django.utils import timezone
from datetime import timedelta

logger = logging.getLogger('payments')


class HealthChecker:
    """
    Checks the health of every PaySync dependency.

    Used by:
    - Load balancers (is this instance alive?)
    - Monitoring systems (is the whole service healthy?)
    - Deployment pipelines (is the new version working?)
    - You, at 2am, wondering why payments stopped
    """

    def run_all_checks(self) -> dict:
        """
        Runs all health checks and returns a combined report.
        Overall status is 'healthy' only if ALL checks pass.
        """
        start_time = time.monotonic()

        checks = {
            "database":    self._check_database(),
            "mpesa_config": self._check_mpesa_config(),
            "payment_stats": self._check_recent_payment_stats(),
            "retry_queue":  self._check_retry_queue(),
        }

        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        # Overall healthy only if all critical checks pass
        # mpesa_config is critical — without it, all payments fail
        critical_checks = ['database', 'mpesa_config']
        overall_healthy = all(
            checks[k]['status'] == 'ok'
            for k in critical_checks
        )

        return {
            "status":         "healthy" if overall_healthy else "unhealthy",
            "timestamp":      timezone.now().isoformat(),
            "response_ms":    elapsed_ms,
            "version":        "1.0.0",
            "environment":    getattr(settings, 'MPESA_ENV', 'unknown'),
            "checks":         checks,
        }

    def _check_database(self) -> dict:
        """Verify PostgreSQL is reachable and responsive."""
        start = time.monotonic()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            elapsed = int((time.monotonic() - start) * 1000)
            return {
                "status":     "ok",
                "message":    "Database is reachable.",
                "latency_ms": elapsed,
            }
        except OperationalError as e:
            logger.error(
                "Database health check failed",
                extra={"event": "health_check_failed", "check": "database", "error": str(e)}
            )
            return {
                "status":  "error",
                "message": f"Database unreachable: {str(e)}",
            }

    def _check_mpesa_config(self) -> dict:
        """
        Verify M-Pesa credentials are configured.
        Does NOT make a live API call — just validates config presence.
        Live call would cost a token and be too slow for health checks.
        """
        required_settings = [
            'MPESA_CONSUMER_KEY',
            'MPESA_CONSUMER_SECRET',
            'MPESA_SHORTCODE',
            'MPESA_PASSKEY',
            'MPESA_CALLBACK_URL',
        ]

        missing = [
            key for key in required_settings
            if not getattr(settings, key, '').strip()
        ]

        if missing:
            logger.error(
                "M-Pesa configuration incomplete",
                extra={
                    "event":   "health_check_failed",
                    "check":   "mpesa_config",
                    "missing": missing,
                }
            )
            return {
                "status":  "error",
                "message": f"Missing required M-Pesa settings: {missing}",
            }

        callback_url = settings.MPESA_CALLBACK_URL
        if 'localhost' in callback_url or '127.0.0.1' in callback_url:
            return {
                "status":  "warning",
                "message": (
                    "M-Pesa callback URL points to localhost — "
                    "callbacks will not be received in production."
                ),
                "callback_url": callback_url,
            }

        return {
            "status":        "ok",
            "message":       "M-Pesa configuration present.",
            "environment":   settings.MPESA_ENV,
            "shortcode":     settings.MPESA_SHORTCODE,
            "callback_url":  callback_url,
        }

    def _check_recent_payment_stats(self) -> dict:
        """
        Checks payment success/failure rates over the last 30 minutes.
        Flags if failure rate is suspiciously high.
        """
        from payments.models import Payment

        window_start  = timezone.now() - timedelta(minutes=30)
        recent        = Payment.objects.filter(created_at__gte=window_start)
        total_count   = recent.count()
        success_count = recent.filter(status=Payment.Status.SUCCESS).count()
        failed_count  = recent.filter(status=Payment.Status.FAILED).count()
        pending_count = recent.filter(status=Payment.Status.PENDING).count()

        failure_rate = (
            (failed_count / total_count * 100)
            if total_count > 0 else 0
        )

        # Alert if failure rate > 50% with meaningful sample size
        HIGH_FAILURE_THRESHOLD = 50.0
        MIN_SAMPLE_SIZE        = 5

        if total_count >= MIN_SAMPLE_SIZE and failure_rate > HIGH_FAILURE_THRESHOLD:
            from payments.event_logger import PaymentEventLogger
            PaymentEventLogger.high_failure_rate(
                failed_count=failed_count,
                total_count=total_count,
                window_minutes=30,
            )
            status_val = "warning"
            message    = (
                f"High failure rate: {failure_rate:.1f}% in last 30 minutes. "
                f"Check M-Pesa status."
            )
        else:
            status_val = "ok"
            message    = f"Payment stats normal ({total_count} payments in last 30min)."

        return {
            "status":        status_val,
            "message":       message,
            "window_minutes": 30,
            "total":         total_count,
            "success":       success_count,
            "failed":        failed_count,
            "pending":       pending_count,
            "failure_rate":  f"{failure_rate:.1f}%",
        }

    def _check_retry_queue(self) -> dict:
        """
        Reports on payments waiting for retry.
        A large queue might indicate systematic failures.
        """
        from payments.models import Payment

        now = timezone.now()

        # Payments scheduled for retry
        scheduled = Payment.objects.filter(
            status=Payment.Status.PENDING,
            next_retry_at__isnull=False,
        ).count()

        # Overdue retries — scheduled time has passed but not processed
        # Indicates the retry scheduler might not be running
        overdue = Payment.objects.filter(
            status=Payment.Status.PENDING,
            next_retry_at__lt=now,
            is_processing=False,
        ).count()

        status_val = "ok"
        message    = f"{scheduled} payments in retry queue."

        if overdue > 0:
            status_val = "warning"
            message    = (
                f"{overdue} overdue retries detected. "
                f"Is the retry scheduler (Task Scheduler) running? "
                f"Run: python manage.py process_retries"
            )
            logger.warning(
                "Overdue retries detected",
                extra={
                    "event":   "overdue_retries",
                    "overdue": overdue,
                    "action":  "Check Windows Task Scheduler — PaySync_RetryPayments",
                }
            )

        return {
            "status":     status_val,
            "message":    message,
            "scheduled":  scheduled,
            "overdue":    overdue,
        }