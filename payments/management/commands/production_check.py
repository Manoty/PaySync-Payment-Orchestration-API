"""
Pre-deployment production readiness check.
Run this before every deployment and before going live.
Exits with code 1 if any critical check fails.
"""

import sys
import os
import django
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Verify PaySync is ready for production deployment"

    def handle(self, *args, **options):
        from django.conf import settings

        checks   = []
        failures = []
        warnings = []

        # ── Critical checks — deployment should STOP if any fail ──────────────

        self._check(
            checks, failures,
            name="SECRET_KEY set",
            passed=bool(getattr(settings, 'SECRET_KEY', '')),
            critical=True,
            fix="Set SECRET_KEY in your .env file.",
        )

        self._check(
            checks, failures,
            name="DEBUG is False",
            passed=not settings.DEBUG,
            critical=True,
            fix="Set DEBUG=False in production.",
        )

        self._check(
            checks, failures,
            name="ALLOWED_HOSTS configured",
            passed=bool(settings.ALLOWED_HOSTS),
            critical=True,
            fix="Set ALLOWED_HOSTS in your .env file.",
        )

        self._check(
            checks, failures,
            name="Database credentials set",
            passed=all([
                os.getenv('DB_NAME'),
                os.getenv('DB_USER'),
                os.getenv('DB_PASSWORD'),
            ]),
            critical=True,
            fix="Set DB_NAME, DB_USER, DB_PASSWORD in .env.",
        )

        # ── M-Pesa config ─────────────────────────────────────────────────────

        mpesa_keys = [
            'MPESA_CONSUMER_KEY', 'MPESA_CONSUMER_SECRET',
            'MPESA_SHORTCODE', 'MPESA_PASSKEY', 'MPESA_CALLBACK_URL',
        ]
        missing_mpesa = [k for k in mpesa_keys if not os.getenv(k)]
        self._check(
            checks, failures,
            name="All M-Pesa settings present",
            passed=not missing_mpesa,
            critical=True,
            fix=f"Set in .env: {missing_mpesa}",
        )

        callback_url = os.getenv('MPESA_CALLBACK_URL', '')
        self._check(
            checks, failures,
            name="Callback URL is HTTPS",
            passed=callback_url.startswith('https://'),
            critical=True,
            fix="MPESA_CALLBACK_URL must use HTTPS in production.",
        )

        self._check(
            checks, failures,
            name="Callback URL not localhost",
            passed='localhost' not in callback_url and '127.0.0.1' not in callback_url,
            critical=True,
            fix="MPESA_CALLBACK_URL must be a public URL, not localhost.",
        )

        self._check(
            checks, failures,
            name="MPESA_ENV is 'production'",
            passed=os.getenv('MPESA_ENV') == 'production',
            critical=True,
            fix="Set MPESA_ENV=production in .env.",
        )

        # ── Database connectivity ──────────────────────────────────────────────
        try:
            from django.db import connection
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            db_ok = True
        except Exception as e:
            db_ok = False

        self._check(
            checks, failures,
            name="Database is reachable",
            passed=db_ok,
            critical=True,
            fix="Check DB_HOST, DB_PORT, DB_USER, DB_PASSWORD.",
        )

        # ── Migrations applied ────────────────────────────────────────────────
        try:
            from django.db.migrations.executor import MigrationExecutor
            executor = MigrationExecutor(connection)
            plan     = executor.migration_plan(executor.loader.graph.leaf_nodes())
            migrations_ok = len(plan) == 0
        except Exception:
            migrations_ok = False

        self._check(
            checks, failures,
            name="All migrations applied",
            passed=migrations_ok,
            critical=True,
            fix="Run: python manage.py migrate",
        )

        # ── API clients registered ────────────────────────────────────────────
        try:
            from authentication.models import APIClient
            client_count = APIClient.objects.filter(
                status=APIClient.Status.ACTIVE
            ).count()
            has_clients = client_count > 0
        except Exception:
            has_clients = False
            client_count = 0

        self._check(
            checks, failures,
            name=f"API clients registered ({client_count} active)",
            passed=has_clients,
            critical=True,
            fix="Run: python manage.py manage_api_clients create --name 'Tixora' --source-system tixora",
        )

        # ── CORS ─────────────────────────────────────────────────────────────
        cors_origins = getattr(settings, 'CORS_ALLOWED_ORIGINS', [])
        cors_all     = getattr(settings, 'CORS_ALLOW_ALL_ORIGINS', False)

        self._check(
            checks, warnings,
            name="CORS_ALLOW_ALL_ORIGINS is False",
            passed=not cors_all,
            critical=False,
            fix="Set CORS_ALLOWED_ORIGINS instead of allowing all origins.",
        )

        self._check(
            checks, warnings,
            name=f"CORS origins configured ({len(cors_origins)})",
            passed=bool(cors_origins),
            critical=False,
            fix="Set CORS_ALLOWED_ORIGINS in .env.",
        )

        # ── Security settings ─────────────────────────────────────────────────
        self._check(
            checks, warnings,
            name="SECURE_SSL_REDIRECT enabled",
            passed=getattr(settings, 'SECURE_SSL_REDIRECT', False),
            critical=False,
            fix="Add SECURE_SSL_REDIRECT=True to production settings.",
        )

        self._check(
            checks, warnings,
            name="HSTS enabled",
            passed=getattr(settings, 'SECURE_HSTS_SECONDS', 0) > 0,
            critical=False,
            fix="Add SECURE_HSTS_SECONDS=31536000 to production settings.",
        )

        # ── Logs directory ────────────────────────────────────────────────────
        from pathlib import Path
        log_dir = Path(settings.BASE_DIR) / 'logs'
        self._check(
            checks, warnings,
            name="logs/ directory exists and is writable",
            passed=log_dir.exists() and os.access(log_dir, os.W_OK),
            critical=False,
            fix="Run: mkdir logs",
        )

        # ── Print report ──────────────────────────────────────────────────────
        self.stdout.write(f"\n{'='*60}")
        self.stdout.write("PaySync Production Readiness Report")
        self.stdout.write(f"{'='*60}\n")

        for check in checks:
            symbol = "✅" if check['passed'] else ("🔴" if check['critical'] else "⚠️ ")
            self.stdout.write(f"{symbol}  {check['name']}")
            if not check['passed'] and check.get('fix'):
                self.stdout.write(f"     → Fix: {check['fix']}")

        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(
            f"Total: {len(checks)} checks | "
            f"Passed: {sum(1 for c in checks if c['passed'])} | "
            f"Failed: {len(failures)} | "
            f"Warnings: {len(warnings)}"
        )

        if failures:
            self.stdout.write(self.style.ERROR(
                f"\n🔴 {len(failures)} critical issue(s) must be resolved before deployment.\n"
            ))
            sys.exit(1)
        elif warnings:
            self.stdout.write(self.style.WARNING(
                f"\n⚠️  {len(warnings)} warning(s). Review before going live.\n"
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                "\n✅ All checks passed. PaySync is production-ready.\n"
            ))

    def _check(self, checks, failures_or_warnings, name, passed, critical, fix=None):
        entry = {"name": name, "passed": passed, "critical": critical, "fix": fix}
        checks.append(entry)
        if not passed:
            failures_or_warnings.append(entry)