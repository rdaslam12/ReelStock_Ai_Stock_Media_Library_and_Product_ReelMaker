
from pathlib import Path
import os
from dotenv import load_dotenv
BASE_DIR = Path(__file__).resolve().parent.parent

# -----------------------------------------------------------------------------
# Load environment variables early
#
# We want to read values from a .env file if present before we define any
# project-level settings that depend on them (e.g. HF_API_TOKEN). In the
# previous version of this file, `load_dotenv()` was invoked *after* reading
# environment variables, which meant any variables defined in `.env` were not
# available when defaults like HF_API_TOKEN were computed. This resulted in
# missing API tokens and fallback behaviour (e.g. only gradient backgrounds
# instead of AI-generated scenes). To fix this, call load_dotenv() here at the
# very start. It will populate os.environ from the `.env` file if it exists.
load_dotenv(BASE_DIR / ".env", override=True)

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-reelstock-demo-key-change-in-prod')

DEBUG = True

ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
    'core.apps.CoreConfig',
    'libraryapp',
    'studio',
    'moderation',
    'wallet.apps.WalletConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'moderation.middleware.AdminSessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'allauth.account.middleware.AccountMiddleware',
    'core.middleware.ProfileCompletionMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'reelstock.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'wallet.context_processors.wallet_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'reelstock.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Dhaka'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'
SITE_ID = int(os.environ.get('DJANGO_SITE_ID', '1'))
CUSTOM_ADMIN_SESSION_COOKIE_NAME = 'reelstock_admin_sessionid'
CUSTOM_ADMIN_SESSION_COOKIE_PATH = '/admin-panel/'

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

ACCOUNT_LOGIN_METHODS = {'email', 'username'}
ACCOUNT_SIGNUP_FIELDS = ['email*', 'password1*', 'password2*']
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_EMAIL_VERIFICATION = os.environ.get('ACCOUNT_EMAIL_VERIFICATION', 'optional')
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_QUERY_EMAIL = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True
SOCIALACCOUNT_LOGIN_ON_GET = True
SOCIALACCOUNT_STORE_TOKENS = False
SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'SCOPE': ['profile', 'email'],
        'AUTH_PARAMS': {'access_type': 'online'},
    },
}

# HuggingFace image generation
HF_API_TOKEN = os.environ.get('HF_API_TOKEN', '').strip()
HF_IMAGE_MODEL = os.environ.get('HF_IMAGE_MODEL', 'black-forest-labs/FLUX.1-schnell').strip()
HF_IMAGE_TIMEOUT = int(os.environ.get('HF_IMAGE_TIMEOUT', '60'))
#HF VIDEO
# We already loaded the environment file at the top of this module. Avoid
# re-loading it here to prevent unexpected overrides. The following block
# previously redefined BASE_DIR and invoked load_dotenv() again. It has been
# removed for clarity.
# HF text-to-video
TEXT_VIDEO_MODEL = os.environ.get('TEXT_VIDEO_MODEL', 'ali-vilab/text-to-video-ms-1.7b')
TEXT_VIDEO_API = os.environ.get('TEXT_VIDEO_API', 'huggingface')
TEXT_VIDEO_TIMEOUT = int(os.environ.get('TEXT_VIDEO_TIMEOUT', '120'))

# Fal.ai video generation
FAL_API_KEY = os.environ.get('FAL_API_KEY', '').strip()

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

EMAIL_BACKEND = os.environ.get(
    'DJANGO_EMAIL_BACKEND',
    'django.core.mail.backends.console.EmailBackend',
)
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '587'))
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'true').lower() in ('1', 'true', 'yes', 'on')
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.environ.get(
    'DEFAULT_FROM_EMAIL',
    EMAIL_HOST_USER or 'ReelStock Admin <noreply@reelstock.local>',
)
ADMIN_CONTACT_EMAIL = os.environ.get('ADMIN_CONTACT_EMAIL', EMAIL_HOST_USER or 'admin@reelstock.local')

REELMAKER_LOG_LEVEL = os.environ.get('REELMAKER_LOG_LEVEL', 'INFO').upper()

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'loggers': {
        'studio.services.scene_generator': {
            'handlers': ['console'],
            'level': REELMAKER_LOG_LEVEL,
            'propagate': False,
        },
        'studio.services.variation_generator': {
            'handlers': ['console'],
            'level': REELMAKER_LOG_LEVEL,
            'propagate': False,
        },
        'studio.services.reel_pipeline': {
            'handlers': ['console'],
            'level': REELMAKER_LOG_LEVEL,
            'propagate': False,
        },
        'studio.views': {
            'handlers': ['console'],
            'level': REELMAKER_LOG_LEVEL,
            'propagate': False,
        },
        'libraryapp.views': {
            'handlers': ['console'],
            'level': REELMAKER_LOG_LEVEL,
            'propagate': False,
        },
    },
}
