"""
Base settings — shared across ALL environments.
Never import this directly. Import development.py or production.py.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.getenv('SECRET_KEY')
if not SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY environment variable is not set. "
        "Generate one with: python -c \"import secrets; print(secrets.token_hex(50))\""
    )

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'payments',
    'authentication',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',          # ← CORS (installed below)
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'paysync_backend.middleware.RequestLoggingMiddleware',  # ← custom (built below)
]

ROOT_URLCONF = 'paysync_backend.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'paysync_backend.wsgi.application'

# ─── Database ──────────────────────────────────────────────────────────────────
DATABASES = {
    'default': {
        'ENGINE':   'django.db.backends.postgresql',
        'NAME':     os.getenv('DB_NAME'),
        'USER':     os.getenv('DB_USER'),
        'PASSWORD': os.getenv('DB_PASSWORD'),
        'HOST':     os.getenv('DB_HOST', 'localhost'),
        'PORT':     os.getenv('DB_PORT', '5432'),
        'OPTIONS': {
            # Wait max 5 seconds to acquire a DB connection
            # Prevents hung requests if DB is slow to respond
            'connect_timeout': 5,
        },
        'CONN_MAX_AGE': int(os.getenv('DB_CONN_MAX_AGE', 60)),
        # CONN_MAX_AGE=60 means Django reuses DB connections for 60 seconds
        # instead of opening a new one per request. Reduces connection overhead
        # significantly under load. Set to 0 to disable pooling.
    }
}

# ─── REST Framework ────────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    'DEFAULT_PARSER_CLASSES': [
        'rest_framework.parsers.JSONParser',
    ],
    'EXCEPTION_HANDLER': 'paysync_backend.error_handlers.paysync_exception_handler',
    # Global timeout for DRF views — prevents runaway requests
    'DEFAULT_THROTTLE_RATES': {
        'anon': '20/min',   # Unauthenticated (health check, etc.)
    },
}

# ─── Internationalization ──────────────────────────────────────────────────────
LANGUAGE_CODE = 'en-us'
TIME_ZONE     = 'Africa/Nairobi'
USE_I18N      = True
USE_TZ        = True

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
STATIC_URL         = '/static/'
STATIC_ROOT        = BASE_DIR / 'staticfiles'

# ─── M-Pesa ────────────────────────────────────────────────────────────────────
MPESA_CONSUMER_KEY    = os.getenv('MPESA_CONSUMER_KEY', '')
MPESA_CONSUMER_SECRET = os.getenv('MPESA_CONSUMER_SECRET', '')
MPESA_SHORTCODE       = os.getenv('MPESA_SHORTCODE', '')
MPESA_PASSKEY         = os.getenv('MPESA_PASSKEY', '')
MPESA_CALLBACK_URL    = os.getenv('MPESA_CALLBACK_URL', '')
MPESA_ENV             = os.getenv('MPESA_ENV', 'sandbox')

# ─── HTTP timeouts for external calls ─────────────────────────────────────────
# Applied everywhere we call requests.get/post to Daraja
# Without these, a slow Daraja response holds your worker thread forever
MPESA_REQUEST_TIMEOUT = int(os.getenv('MPESA_REQUEST_TIMEOUT', 30))
MPESA_TOKEN_TIMEOUT   = int(os.getenv('MPESA_TOKEN_TIMEOUT', 15))

# ─── Retry configuration ───────────────────────────────────────────────────────
PAYMENT_MAX_RETRIES       = int(os.getenv('PAYMENT_MAX_RETRIES', 3))
PAYMENT_RETRY_DELAYS      = [2, 5, 10]   # minutes between each retry attempt

# ─── Security ──────────────────────────────────────────────────────────────────
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv('CSRF_TRUSTED_ORIGINS', '').split(',')
    if origin.strip()
]