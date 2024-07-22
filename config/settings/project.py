from environ import environ

from ._setup import env

# Project's apps stuff...
# ------------------------------------------------------------------------------
# graphql
# ------------------------------------------------------------------------------
# show graphiql panel or not
GRAPHIQL = env.bool("GRAPHIQL", False)

# telegram_bot
# ------------------------------------------------------------------------------
TELEGRAM_WEBHOOK_URL_PREFIX = env.str("TELEGRAM_WEBHOOK_URL_PREFIX", "telegram-webhook")
TELEGRAM_PROXY = env.url("TELEGRAM_PROXY", default=None)
if TELEGRAM_PROXY:
    TELEGRAM_PROXY = environ.urlunparse(TELEGRAM_PROXY)

TELEGRAM_MIDDLEWARE = [
    "televi1.telegram_bot.t_middleware.AuthenticationMiddleware",
    "televi1.telegram_bot.t_middleware.CommonMiddleware",
]
TELEGRAM_WEBHOOK_FLYING_DOMAINS = env.list("TELEGRAM_WEBHOOK_FLYING_DOMAINS")
TELEGRAM_PREFER_REPLY_TO_WEBHOOK = env.bool("TELEGRAM_PREFER_REPLY_TO_WEBHOOK")
