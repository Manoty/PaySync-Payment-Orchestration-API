"""
Settings loader.
Reads DJANGO_ENV from environment and imports the correct settings module.
Defaults to development so local setup works without extra config.
"""

import os

env = os.getenv('DJANGO_ENV', 'development').lower()

if env == 'production':
    from .production import *
elif env == 'testing':
    from .testing import *
else:
    from .development import *