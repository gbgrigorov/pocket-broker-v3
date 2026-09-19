# -*- coding: utf-8 -*-
"""Django settings for Varna Market.

One PostgreSQL database holds the whole market: offers crawled from vetted
agency websites, the units and projects they collapse into, and the buyer
profiles matched against them.

The supply half of this app is vendored from ~/Dev/broker-crm, which solved
multi-agency ingest, identity and dedupe for one Burgas brokerage. See
sourcing/vendor/UPSTREAM.md for what was taken and how divergence is tracked.
"""
from pathlib import Path

from . import env

BASE_DIR = Path(__file__).resolve().parent.parent
env.load(BASE_DIR / '.env')

SECRET_KEY = env.get('DJANGO_SECRET_KEY', 'insecure-dev-key-do-not-use-in-production')
DEBUG = env.get('DJANGO_DEBUG', True, bool)
ALLOWED_HOSTS = [h.strip() for h in env.get('DJANGO_ALLOWED_HOSTS', '127.0.0.1,localhost').split(',') if h.strip()]

# In development the Vue app is served by Vite on its own port and proxies
# /api back here, so the browser's Origin header names Vite, not Django.
CSRF_TRUSTED_ORIGINS = [
    origin.strip() for origin in env.get(
        'DJANGO_CSRF_ORIGINS',
        'http://localhost:5173,http://127.0.0.1:5173,'
        'http://localhost:5174,http://127.0.0.1:5174',
    ).split(',') if origin.strip()
]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.postgres',
    'django.contrib.humanize',
    'sourcing',
    'market',
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
WSGI_APPLICATION = 'config.wsgi.application'

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'],
    'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
    ]},
}]

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': env.get('DB_NAME', 'varna_market'),
        'USER': env.get('DB_USER', 'gabe'),
        'PASSWORD': env.get('DB_PASSWORD', ''),
        'HOST': env.get('DB_HOST', '127.0.0.1'),
        'PORT': env.get('DB_PORT', '5432'),
        'CONN_MAX_AGE': 60,
    }
}
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Buyers are Bulgarian; so is the interface. Data is stored canonically
# (English keys, EUR) regardless of the interface language.
LANGUAGE_CODE = 'bg'
TIME_ZONE = 'Europe/Sofia'
USE_I18N = True
USE_TZ = True
# Bulgarian convention groups thousands with a space: 149 000 €, never 149,000.
USE_THOUSAND_SEPARATOR = True
THOUSAND_SEPARATOR = ' '
NUMBER_GROUPING = 3

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
# The built Vue app (phase 8). Absent until then, and Django warns about a
# missing entry, so it is listed only once it exists.
STATICFILES_DIRS = [d for d in [BASE_DIR / 'frontend' / 'dist'] if d.exists()]

MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'data'

LOGIN_URL = '/admin/login/'
LOGIN_REDIRECT_URL = '/admin/'

# ---------------------------------------------------------------- project ----

DATA_DIR = BASE_DIR / 'data'
RAW_DIR = DATA_DIR / 'raw'
IMAGES_DIR = DATA_DIR / 'images'
RUNS_DIR = DATA_DIR / 'runs'

# EUR is canonical. Agencies still quote BGN often enough to matter.
BGN_PER_EUR = 1.95583

# The city this instance covers. Varna is the experiment; the schema is
# national, so this is a setting and not an assumption baked into queries.
MARKET_CITY = env.get('MARKET_CITY', 'Варна')

CRAWL_USER_AGENT = env.get(
    'CRAWL_USER_AGENT',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')
CRAWL_TIMEOUT = env.get('CRAWL_TIMEOUT', 90, int)

# What the crawler calls itself. Honest, and contactable: a webmaster who wants
# us to stop must be able to find out who we are and reach us in one step. That
# matters more here than usual, because we do not stop at robots.txt -- see
# docs/CRAWL-POLICY.md -- so the complaint channel is the real safety valve.
CRAWL_USER_AGENT_BOT = env.get(
    'CRAWL_USER_AGENT_BOT',
    'VarnaMarketBot/0.1 (+https://github.com/gbgrigorov/varna-market; '
    'contact: gabriel.spmn@gmail.com)')

# robots.txt is recorded on every probe either way; this decides whether it
# also stops us. Off by decision, not by oversight: these agencies publish
# their catalogues publicly and we have no relationship with them yet, and
# without the data there is no product to bring them. The sequence is
# deliberate -- aggregate first, then approach them for a direct feed.
#
# What that does NOT license, and what the crawler still refuses to do:
# no logins, no paywalls, no CAPTCHA solving, no credential reuse. A blocked
# host is recorded and skipped, never worked around. See docs/CRAWL-POLICY.md.
CRAWL_RESPECT_ROBOTS = env.get('CRAWL_RESPECT_ROBOTS', False, bool)

# One worker per host, spaced. Politeness here is self-interest rather than
# courtesy: a banned IP yields zero data, which is the outcome we are trying
# to avoid. Concurrency is across hosts, never within one.
CRAWL_WORKERS = env.get('CRAWL_WORKERS', 4, int)
CRAWL_HOST_DELAY = env.get('CRAWL_HOST_DELAY', 2.0, float)
# Consecutive 429/503 responses from one host before that host is abandoned
# for the rest of the run.
CRAWL_BACKOFF_LIMIT = env.get('CRAWL_BACKOFF_LIMIT', 3, int)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {'plain': {'format': '%(asctime)s %(levelname)-7s %(name)s  %(message)s',
                             'datefmt': '%H:%M:%S'}},
    'handlers': {'console': {'class': 'logging.StreamHandler', 'formatter': 'plain'}},
    'root': {'handlers': ['console'], 'level': 'INFO'},
    'loggers': {'django.db.backends': {'level': 'WARNING'}},
}
