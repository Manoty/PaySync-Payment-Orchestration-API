from django.core.management.base import BaseCommand
from payments.retry_service import RetryService
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Process all payments that are due for retry"

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be retried without actually doing it',
        )

    def handle(self, *args, **options):
        if options['dry_run']:
            from django.utils import timezone
            from payments.models import Payment

            due = Payment.objects.filter(
                status=Payment.Status.PENDING,
                next_retry_at__lte=timezone.now(),
                is_processing=False,
                next_retry_at__isnull=False,
            )
            self.stdout.write(f"Dry run — {due.count()} payment(s) due for retry:")
            for p in due:
                self.stdout.write(
                    f"  • {p.reference} | KES {p.amount} | "
                    f"retry #{p.retry_count + 1} | "
                    f"due: {p.next_retry_at}"
                )
            return

        self.stdout.write("Processing due retries...")
        service = RetryService()
        stats = service.process_due_retries()

        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {stats['processed']} processed | "
                f"{stats['succeeded']} STK sent | "
                f"{stats['failed']} failed | "
                f"{stats['errors']} errors"
            )
        )