"""
Validates that all required environment variables are set.
Run before starting the server: python validate_env.py
Exit code 0 = OK, exit code 1 = missing variables.
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()

REQUIRED = {
    'development': [
        'SECRET_KEY', 'DB_NAME', 'DB_USER', 'DB_PASSWORD',
        'MPESA_CONSUMER_KEY', 'MPESA_CONSUMER_SECRET',
        'MPESA_SHORTCODE', 'MPESA_PASSKEY', 'MPESA_CALLBACK_URL',
    ],
    'production': [
        'SECRET_KEY', 'DB_NAME', 'DB_USER', 'DB_PASSWORD',
        'DB_HOST', 'ALLOWED_HOSTS',
        'MPESA_CONSUMER_KEY', 'MPESA_CONSUMER_SECRET',
        'MPESA_SHORTCODE', 'MPESA_PASSKEY', 'MPESA_CALLBACK_URL',
        'CORS_ALLOWED_ORIGINS',
    ],
}

env      = os.getenv('DJANGO_ENV', 'development')
required = REQUIRED.get(env, REQUIRED['development'])
missing  = [key for key in required if not os.getenv(key, '').strip()]

if missing:
    print(f"\n❌ Missing required environment variables for '{env}':")
    for key in missing:
        print(f"   - {key}")
    print(f"\nAdd these to your .env file and try again.\n")
    sys.exit(1)

print(f"✅ All required environment variables present for '{env}'.")
sys.exit(0)