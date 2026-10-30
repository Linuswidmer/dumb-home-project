from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()
# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent
# Everything written at runtime (database, uploads, collected static files) lives
# outside the repo, so a git pull never touches it. See apps/pong/run.sh.
DATA_DIR = Path(os.environ.get("PONG_DATA_DIR", BASE_DIR / "data"))

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
DEBUG = os.environ.get("DJANGO_DEBUG", "False") == "True"
ALLOWED_HOSTS = os.environ.get('DJANGO_ALLOWED_HOSTS', '').split() + os.environ.get('LOCAL_IP', '').split()

CSRF_TRUSTED_ORIGINS = os.environ.get('CSRF_TRUSTED_ORIGINS', '').split() + os.environ.get('LOCAL_IP_CSRF', '').split()

# Application definition

INSTALLED_APPS = [
    'channels',
    'daphne',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'userManagement',
	'pong_online',
    'django.contrib.sites',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'provider',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # serves /static/ (nginx did that before)
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'allauth.account.middleware.AccountMiddleware',
#    'userManagement.middleware.UpdateUserActivityMiddleware'
]

ROOT_URLCONF = 'app_server.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'app_server/templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'userManagement.context_processors.export_vars',
            ],
        },
    },
]

WSGI_APPLICATION = 'app_server.wsgi.application'
ASGI_APPLICATION = 'app_server.routing.application'

# Database
# https://docs.djangoproject.com/en/5.0/ref/settings/#databases

# SQLite instead of Postgres: one small home server, no separate database process.
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': DATA_DIR / 'pong.sqlite3',
        'OPTIONS': {'timeout': 20},  # wait for a concurrent write instead of failing
    }
}

# Channels: in-memory instead of Redis. Fine as long as everything runs in one
# daphne process, which run.sh makes sure of — only the consumers use it.
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    },
}

AUTHENTICATION_BACKENDS = (
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
)
# Password validation
# https://docs.djangoproject.com/en/5.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]

# Internationalization
# https://docs.djangoproject.com/en/5.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'Europe/Berlin'

USE_I18N = True

USE_TZ = True

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.0/howto/static-files/

STATIC_URL = 'static/'
STATIC_ROOT = DATA_DIR / 'static'

# Default primary key field type
# https://docs.djangoproject.com/en/5.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGOUT_REDIRECT_URL = 'userManagement:index'

LOGIN_REDIRECT_URL = 'userManagement:display_lobby'
ACCOUNT_REDIRECT_URL = 'userManagement:index'
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
# Only ever served over HTTPS (daphne terminates TLS itself, see run.sh).
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SITE_ID = 1
MEDIA_ROOT = DATA_DIR / 'media'  # seeded from apps/pong/media by run.sh
MEDIA_URL = '/media/'

OAUTH_SERVER_BASEURL = 'https://api.intra.42.fr'
SOCIALACCOUNT_LOGIN_ON_GET = True #remove the middle screen "You are about to sign in using a third-party"
OAUTH_CLIENT_ID = os.environ.get("OAUTH_CLIENT_ID")
OAUTH_CALLBACK_URL = os.environ.get("OAUTH_CALLBACK_URL")