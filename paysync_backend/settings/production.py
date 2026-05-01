"""
Production settings.
Hardened security, structured logging, strict validation.
All secrets MUST come from environment variables — never from this file.
"""

from .base import *
import os

DEBUG = False

# ─── Hosts ─────────────────────────────────────────────────────────────────────
_allowed = os.getenv('ALLOWED_HOSTS', '')
if not _allowed:
    raise RuntimeError("ALLOWED_HOSTS must be set in production.")
ALLOWED_HOSTS = [h.strip() for h in _allowed.split(',')]

# ─── HTTPS enforcement ─────────────────────────────────────────────────────────
SECURE_SSL_REDIRECT               = True
SECURE_HSTS_SECONDS               = 31536000    # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS    = True
SECURE_HSTS_PRELOAD               = True
SECURE_PROXY_SSL_HEADER           = ('HTTP_X_FORWARDED_PROTO', 'https')
SESSION_COOKIE_SECURE             = True
CSRF_COOKIE_SECURE                = True
SECURE_BROWSER_XSS_FILTER         = True
SECURE_CONTENT_TYPE_NOSNIFF       = True
X_FRAME_OPTIONS                   = 'DENY'

# ─── CORS — locked to specific origins ────────────────────────────────────────
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS   = [
    origin.strip()
    for origin in os.getenv('CORS_ALLOWED_ORIGINS', '').split(',')
    if origin.strip()
]
CORS_ALLOW_HEADERS = [
    'content-type',
    'x-api-key',
    'accept',
    'authorization',
]
CORS_ALLOW_METHODS = [
    'GET',
    'POST',
    'OPTIONS',
]

# ─── Database — production hardening ──────────────────────────────────────────
DATABASES['default'].update({
    'CONN_MAX_AGE': int(os.getenv('DB_CONN_MAX_AGE', 300)),
    'OPTIONS': {
        'connect_timeout':      5,
        'application_name':     'paysync_backend',
        'options':              '-c statement_timeout=30000',  # 30s query timeout
    },
})

# ─── Caching ───────────────────────────────────────────────────────────────────
# In production, use Redis or Memcached for session/cache
# For now, database cache is safe for PaySync's access pattern
CACHES = {
    'default': {
        'BACKEND':  'django.core.cache.backends.db.DatabaseCache',
        'LOCATION': 'paysync_cache_table',
    }
}

# ─── Logging — JSON, file-based, minimal console noise ────────────────────────
_LOG_DIR = BASE_DIR / 'logs'
_LOG_DIR.mkdir(exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'json': {
            '()': 'paysync_backend.log_formatter.StructuredJSONFormatter',
        },
    },
    'handlers': {
        'console': {
            'class':     'logging.StreamHandler',
            'formatter': 'json',
            'stream':    'ext://sys.stdout',
        },
        'file_general': {
            'class':       'logging.handlers.RotatingFileHandler',
            'filename':    _LOG_DIR / 'paysync.log',
            'maxBytes':    10 * 1024 * 1024,
            'backupCount': 10,
            'formatter':   'json',
            'encoding':    'utf-8',
        },
        'file_payments': {
            'class':       'logging.handlers.RotatingFileHandler',
            'filename':    _LOG_DIR / 'payments.log',
            'maxBytes':    10 * 1024 * 1024,
            'backupCount': 20,
            'formatter':   'json',
            'encoding':    'utf-8',
        },
        'file_errors': {
            'class':       'logging.handlers.RotatingFileHandler',
            'filename':    _LOG_DIR / 'errors.log',
            'maxBytes':    5 * 1024 * 1024,
            'backupCount': 20,
            'formatter':   'json',
            'level':       'ERROR',
            'encoding':    'utf-8',
        },
    },
    'loggers': {
        'payments': {
            'handlers':  ['console', 'file_payments', 'file_errors'],
            'level':     'INFO',
            'propagate': False,
        },
        'authentication': {
            'handlers':  ['console', 'file_general', 'file_errors'],
            'level':     'INFO',
            'propagate': False,
        },
        'django': {
            'handlers':  ['console', 'file_general'],
            'level':     'WARNING',
            'propagate': False,
        },
        'django.security': {
            'handlers':  ['file_errors'],
            'level':     'ERROR',
            'propagate': False,
        },
        '': {
            'handlers':  ['console', 'file_general'],
            'level':     'WARNING',
        },
    },
}