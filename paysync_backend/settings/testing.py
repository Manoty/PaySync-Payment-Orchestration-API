"""
Test settings — fast, isolated, no external calls.
"""
from .base import *

DEBUG = True

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME':   BASE_DIR / 'test_db.sqlite3',
    }
}

# Disable logging noise during tests
LOGGING = {
    'version': 1,
    'disable_existing_loggers': True,
    'handlers': {'null': {'class': 'logging.NullHandler'}},
    'root': {'handlers': ['null']},
}

MPESA_ENV             = 'sandbox'
MPESA_CONSUMER_KEY    = 'test_consumer_key'
MPESA_CONSUMER_SECRET = 'test_consumer_secret'
MPESA_SHORTCODE       = '174379'
MPESA_PASSKEY         = 'test_passkey'
MPESA_CALLBACK_URL    = 'https://test.example.com/callback/'

CORS_ALLOW_ALL_ORIGINS = True