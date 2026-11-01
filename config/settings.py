import os
from pathlib import Path
from prettyconf import config

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config("SECRET_KEY")
DEBUG = config("DEBUG", default=False, cast=config.boolean)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=lambda v: [s.strip() for s in v.split(',')])

# Chaves Fernet para os dados sensíveis (credenciais SSH). A primeira cifra;
# todas decifram. Rotação: adicione a nova no início, rode
# `manage.py rotate_encryption_keys` e então remova a antiga.
ENCRYPTION_KEYS = config(
    "ENCRYPTION_KEYS",
    default=config("ENCRYPTION_KEY", default=""),
    cast=lambda v: [k.strip() for k in v.split(",") if k.strip()],
)

# Timeouts (segundos) das consultas SSH aos servidores de log
SSH_CONNECT_TIMEOUT = config("SSH_CONNECT_TIMEOUT", default=10, cast=int)
SSH_COMMAND_TIMEOUT = config("SSH_COMMAND_TIMEOUT", default=120, cast=int)

# Timeout (segundos) de conexão e de consulta aos bancos do RADIUS
SUBSCRIBER_DB_TIMEOUT = config("SUBSCRIBER_DB_TIMEOUT", default=15, cast=int)

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'servers:list'
LOGOUT_REDIRECT_URL = 'login'

INSTALLED_APPS = [
    # my apps
    'apps.core.apps.CoreConfig',
    'apps.organizations.apps.OrganizationsConfig',
    'apps.servers.apps.ServersConfig',
    'apps.audit.apps.AuditConfig',
    'apps.subscribers.apps.SubscribersConfig',
    'apps.cases.apps.CasesConfig',
    # django apps
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'apps.organizations.context_processors.organization',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# Segurança em produção (DEBUG=False atrás de HTTPS)
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = 'same-origin'
    CSRF_TRUSTED_ORIGINS = config(
        'CSRF_TRUSTED_ORIGINS', default='',
        cast=lambda v: [s.strip() for s in v.split(',') if s.strip()],
    )

SESSION_COOKIE_AGE = config('SESSION_COOKIE_AGE', default=8 * 60 * 60, cast=int)
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
X_FRAME_OPTIONS = 'DENY'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}


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


LANGUAGE_CODE = 'pt-br'
TIME_ZONE = 'America/Fortaleza'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'static')

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'templates/static'),
]


LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,

    "formatters": {
        "verbose": {
            "format": "[{asctime}] [{levelname}] {name} | {message}",
            "style": "{",
        },
        "simple": {
            "format": "[{levelname}] {message}",
            "style": "{",
        },
    },

    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": os.path.join(LOG_DIR, "app.log"),
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "verbose",
            "level": "ERROR",
        },
    },

    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": True,
        },

        "": {
            "handlers": ["console", "file"],
            "level": "INFO",
        },
    },
}

