from pathlib import Path
import os

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BASE_DIR.parent
load_dotenv(ROOT_DIR / '.env')

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'dev-only-change-me')
DEBUG = os.getenv('DEBUG', '1').lower() in {'1', 'true', 'yes'}
ALLOWED_HOSTS = [x.strip() for x in os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',') if x.strip()]
CSRF_TRUSTED_ORIGINS = [x.strip() for x in os.getenv('CSRF_TRUSTED_ORIGINS', '').split(',') if x.strip()]

INSTALLED_APPS = [
    'django.contrib.admin', 'django.contrib.auth', 'django.contrib.contenttypes',
    'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles',
    'rest_framework', 'rest_framework.authtoken', 'learning',
]
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [ROOT_DIR / 'frontend' / 'dist', BASE_DIR / 'templates'],
    'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
    ]},
}]
WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

DATABASES = {
    'default': dj_database_url.config(
        default=f"sqlite:///{os.getenv('SQLITE_PATH', BASE_DIR / 'db.sqlite3')}",
        conn_max_age=60,
        conn_health_checks=True,
    )
}
if DATABASES['default']['ENGINE'] == 'django.db.backends.sqlite3':
    # Gunicorn and the durable bulk worker are separate processes. A longer busy
    # timeout lets short writes queue instead of surfacing avoidable lock errors.
    DATABASES['default'].setdefault('OPTIONS', {})['timeout'] = int(os.getenv('SQLITE_BUSY_TIMEOUT_SECONDS', '30'))
    DATABASES['default']['CONN_MAX_AGE'] = 0
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
LANGUAGE_CODE = 'en-us'
TIME_ZONE = os.getenv('TIME_ZONE', 'Europe/Amsterdam')
USE_I18N = True
USE_TZ = True
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
FRONTEND_DIST = ROOT_DIR / 'frontend' / 'dist'
if (FRONTEND_DIST / 'assets').exists():
    STATICFILES_DIRS = [FRONTEND_DIST]
else:
    STATICFILES_DIRS = []
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ['rest_framework.authentication.TokenAuthentication'],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated'],
    'EXCEPTION_HANDLER': 'learning.exceptions.api_exception_handler',
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 100,
}
TOKEN_ENCRYPTION_KEY = os.getenv('TOKEN_ENCRYPTION_KEY', '')
ALLOW_SERVER_LLM_TOKENS = os.getenv('ALLOW_SERVER_LLM_TOKENS', '0').lower() in {'1', 'true', 'yes'}
LLM_REQUEST_TIMEOUT_SECONDS = int(os.getenv('LLM_REQUEST_TIMEOUT_SECONDS', '90'))
LLM_RETRY_ATTEMPTS = int(os.getenv('LLM_RETRY_ATTEMPTS', '2'))
LLM_RETRY_BACKOFF_SECONDS = float(os.getenv('LLM_RETRY_BACKOFF_SECONDS', '1.0'))
JUDGE_HEDGE_DELAY_SECONDS = float(os.getenv('JUDGE_HEDGE_DELAY_SECONDS', '3.0'))
# Judge answers are ~100 tokens; a stalled provider must fail fast so the Study
# page never blocks a worker (or the user) for minutes.
JUDGE_REQUEST_TIMEOUT_SECONDS = int(os.getenv('JUDGE_REQUEST_TIMEOUT_SECONDS', '30'))
# Hard ceilings for one API call end to end. Both stay below the gunicorn
# worker timeout so a slow provider produces a clean error, not a 502.
JUDGE_TOTAL_DEADLINE_SECONDS = int(os.getenv('JUDGE_TOTAL_DEADLINE_SECONDS', '40'))
GENERATION_TOTAL_DEADLINE_SECONDS = int(os.getenv('GENERATION_TOTAL_DEADLINE_SECONDS', '170'))
BULK_ITEM_ATTEMPTS = int(os.getenv('BULK_ITEM_ATTEMPTS', '3'))
BULK_MAX_ROUNDS = int(os.getenv('BULK_MAX_ROUNDS', '5'))
BULK_TARGET_SUCCESS_RATIO = float(os.getenv('BULK_TARGET_SUCCESS_RATIO', '0.99'))
BULK_WORKER_POLL_SECONDS = float(os.getenv('BULK_WORKER_POLL_SECONDS', '1.0'))
BULK_STALE_AFTER_SECONDS = int(os.getenv('BULK_STALE_AFTER_SECONDS', '30'))
BULK_SESSION_TIMEOUT_SECONDS = float(os.getenv('BULK_SESSION_TIMEOUT_SECONDS', str(31 * 60)))
MEDIA_ROOT = Path(os.getenv('MEDIA_ROOT', BASE_DIR / 'media'))
TTS_VOICE = os.getenv('TTS_VOICE', 'en-US-AriaNeural')
TTS_RATE = os.getenv('TTS_RATE', '-5%')
TTS_TIMEOUT_SECONDS = int(os.getenv('TTS_TIMEOUT_SECONDS', '25'))
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

# Browser-side hardening. Nginx terminates HTTPS and forwards X-Forwarded-Proto.
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
X_FRAME_OPTIONS = 'DENY'
SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', '0'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = os.getenv('SECURE_HSTS_INCLUDE_SUBDOMAINS', '0').lower() in {'1', 'true', 'yes'}
SECURE_HSTS_PRELOAD = os.getenv('SECURE_HSTS_PRELOAD', '0').lower() in {'1', 'true', 'yes'}
