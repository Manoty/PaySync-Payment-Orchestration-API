"""
Quick log analysis without needing an external tool.
Reads logs/payments.log and surfaces key metrics.
"""
import json
from pathlib import Path
from collections import Counter, defaultdict
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = "Analyze PaySync payment logs and surface key metrics"

    def add_arguments(self, parser):
        parser.add_argument(
            '--lines',
            type=int,
            default=1000,
            help='Number of recent log lines to analyze (default: 1000)',
        )
        parser.add_argument(
            '--event',
            type=str,
            help='Filter to specific event type (e.g. stk_push_failed)',
        )

    def handle(self, *args, **options):
        log_path = Path(settings.BASE_DIR) / 'logs' / 'payments.log'

        if not log_path.exists():
            self.stderr.write("No payments.log found. Run some payments first.")
            return

        lines  = self._read_last_n_lines(log_path, options['lines'])
        events = self._parse_log_lines(lines)

        if options['event']:
            events = [e for e in events if e.get('event') == options['event']]
            self.stdout.write(f"\nShowing events of type: {options['event']}")

        self._print_report(events, options['lines'])

    def _read_last_n_lines(self, path, n):
        with open(path, 'r', encoding='utf-8') as f:
            return f.readlines()[-n:]

    def _parse_log_lines(self, lines):
        events = []
        for line in lines:
            try:
                events.append(json.loads(line.strip()))
            except json.JSONDecodeError:
                continue
        return events

    def _print_report(self, events, line_count):
        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"PaySync Log Analysis ({len(events)} events)")
        self.stdout.write(f"{'='*60}")

        # ── Event type breakdown ───────────────────────────────────────────────
        event_counts = Counter(e.get('event', 'unknown') for e in events)
        self.stdout.write("\n📊 Event Types:")
        for event_type, count in event_counts.most_common(15):
            bar = '█' * min(count, 40)
            self.stdout.write(f"  {event_type:<35} {bar} {count}")

        # ── Error rate ─────────────────────────────────────────────────────────
        error_events = [e for e in events if e.get('level') in ('ERROR', 'CRITICAL')]
        self.stdout.write(
            f"\n🔴 Errors/Criticals: {len(error_events)} of {len(events)} "
            f"({len(error_events)/len(events)*100:.1f}% error rate)"
            if events else "\n🔴 No events."
        )

        # ── Failed payments breakdown ──────────────────────────────────────────
        failures = [e for e in events if e.get('event') == 'payment_failed']
        if failures:
            failure_reasons = Counter(e.get('result_code') for e in failures)
            self.stdout.write(f"\n❌ Failure Result Codes:")
            for code, count in failure_reasons.most_common():
                self.stdout.write(f"  Code {code}: {count} occurrences")

        # ── Source system breakdown ────────────────────────────────────────────
        source_counts = Counter(
            e.get('source_system') for e in events
            if e.get('source_system')
        )
        if source_counts:
            self.stdout.write(f"\n🏢 By Source System:")
            for system, count in source_counts.most_common():
                self.stdout.write(f"  {system}: {count} events")

        # ── Critical alerts ────────────────────────────────────────────────────
        criticals = [e for e in events if e.get('level') == 'CRITICAL']
        if criticals:
            self.stdout.write(
                self.style.ERROR(f"\n🚨 CRITICAL ALERTS ({len(criticals)}):")
            )
            for c in criticals[-5:]:   # Show last 5
                self.stdout.write(
                    self.style.ERROR(
                        f"  [{c.get('timestamp', '?')}] "
                        f"{c.get('message', '?')} | "
                        f"event={c.get('event', '?')}"
                    )
                )

        self.stdout.write(f"\n{'='*60}\n")