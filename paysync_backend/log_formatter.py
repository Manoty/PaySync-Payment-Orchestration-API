import json
import logging
import traceback
from datetime import datetime, timezone


class StructuredJSONFormatter(logging.Formatter):
    """
    Formats every log record as a single JSON object per line.

    Why JSON logs?
    - Every field is queryable (grep, jq, log aggregators)
    - No parsing regex needed — structure is guaranteed
    - Log aggregators (Datadog, Papertrail, CloudWatch) ingest natively
    - Consistent shape regardless of which module logged the message

    Output shape:
    {
        "timestamp":  "2024-01-15T10:30:01.123Z",
        "level":      "ERROR",
        "logger":     "payments.mpesa_service",
        "message":    "STK Push failed",
        "event":      "stk_push_failed",
        "reference":  "a3f9c2d1-...",
        "amount":     500,
        "error":      "Connection timeout",
        "exc_info":   "Traceback (most recent call last)..."
    }
    """

    # Fields that exist on every LogRecord — we separate these
    # from the user-supplied `extra` fields
    STANDARD_FIELDS = {
        'args', 'asctime', 'created', 'exc_info', 'exc_text',
        'filename', 'funcName', 'levelname', 'levelno', 'lineno',
        'message', 'module', 'msecs', 'msg', 'name', 'pathname',
        'process', 'processName', 'relativeCreated', 'stack_info',
        'thread', 'threadName', 'taskName',
    }

    def format(self, record: logging.LogRecord) -> str:
        # Base fields — always present
        log_entry = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).strftime('%Y-%m-%dT%H:%M:%S.') +
            f"{int(record.msecs):03d}Z",
            "level":   record.levelname,
            "logger":  record.name,
            "message": record.getMessage(),
            "module":  record.module,
            "function": record.funcName,
            "line":    record.lineno,
        }

        # Merge any extra= fields the caller passed
        for key, value in record.__dict__.items():
            if key not in self.STANDARD_FIELDS and not key.startswith('_'):
                log_entry[key] = value

        # Exception details — full traceback as a string
        if record.exc_info:
            log_entry["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            log_entry["stack_info"] = self.formatStack(record.stack_info)

        return json.dumps(log_entry, default=str)


class HumanReadableFormatter(logging.Formatter):
    """
    Used for console output during development.
    Coloured, readable, not JSON.
    Switches automatically based on DEBUG setting.
    """

    COLOURS = {
        'DEBUG':    '\033[36m',   # Cyan
        'INFO':     '\033[32m',   # Green
        'WARNING':  '\033[33m',   # Yellow
        'ERROR':    '\033[31m',   # Red
        'CRITICAL': '\033[35m',   # Magenta
    }
    RESET = '\033[0m'

    def format(self, record: logging.LogRecord) -> str:
        colour = self.COLOURS.get(record.levelname, '')
        reset  = self.RESET

        # Extract extra fields for display
        extras = {
            k: v for k, v in record.__dict__.items()
            if k not in StructuredJSONFormatter.STANDARD_FIELDS
            and not k.startswith('_')
        }

        base = (
            f"{colour}[{self.formatTime(record, '%H:%M:%S')}] "
            f"[{record.levelname}] "
            f"[{record.name}]{reset} "
            f"{record.getMessage()}"
        )

        if extras:
            extras_str = " | ".join(f"{k}={v}" for k, v in extras.items())
            base += f"\n    {extras_str}"

        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)

        return base