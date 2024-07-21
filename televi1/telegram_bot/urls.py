from django.conf import settings
from django.urls import re_path

from televi1.telegram_bot import dispatchers
from televi1.telegram_bot.webhook import get_webhook_view
from televi1.utils.decorators import csrf_exempt

urlpatterns = [
    re_path(
        rf"^{settings.TELEGRAM_WEBHOOK_URL_PREFIX}/(?P<url_specifier>.+)/$",
        csrf_exempt(get_webhook_view(dispatchers.dp)),
    ),
]
