"""
Development settings.
Fast iteration, verbose errors, relaxed security.
Never use in production.
"""

from .base import *

DEBUG        = True
ALLOWED_HOSTS = ['localhost', '127.0.0.1', '0.0.0.0', '*.ngrok.io']

# ─── CORS — allow all in dev ───────────────────────────────────────────────────
CORS_ALLOW_ALL_ORIGINS = True

# ─── Email — print to console instead of sending ──────────────────────────────
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# ─── Logging — verbose, human-readable ────────────────────────────────────────
_LOG_DIR = BASE_DIR / 'logs'
_LOG_DIR.mkdir(exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'human': {
            '()': 'paysync_backend.log_formatter.HumanReadableFormatter',
        },
        'json': {
            '()': 'paysync_backend.log_formatter.StructuredJSONFormatter',
        },
    },
    'handlers': {
        'console': {
            'class':     'logging.StreamHandler',
            'formatter': 'human',
        },
        'file_payments': {
            'class':       'logging.handlers.RotatingFileHandler',
            'filename':    _LOG_DIR / 'payments.log',
            'maxBytes':    10 * 1024 * 1024,
            'backupCount': 5,
            'formatter':   'json',
            'encoding':    'utf-8',
        },
        'file_errors': {
            'class':       'logging.handlers.RotatingFileHandler',
            'filename':    _LOG_DIR / 'errors.log',
            'maxBytes':    5 * 1024 * 1024,
            'backupCount': 5,
            'formatter':   'json',
            'level':       'ERROR',
            'encoding':    'utf-8',
        },
    },
    'loggers': {
        'payments':       {'handlers': ['console', 'file_payments', 'file_errors'], 'level': 'DEBUG', 'propagate': False},
        'authentication': {'handlers': ['console', 'file_errors'],                  'level': 'DEBUG', 'propagate': False},
        'django':         {'handlers': ['console'],                                 'level': 'INFO',  'propagate': False},
        '':               {'handlers': ['console'],                                 'level': 'WARNING'},
    },
}

# ─── Django Debug Toolbar (optional) ──────────────────────────────────────────
# Uncomment if you install django-debug-toolbar
# INSTALLED_APPS += ['debug_toolbar']
# MIDDLEWARE.insert(0, 'debug_toolbar.middleware.DebugToolbarMiddleware')
# INTERNAL_IPS = ['127.0.0.1']