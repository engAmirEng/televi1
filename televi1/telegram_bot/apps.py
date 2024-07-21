from django.apps import AppConfig
from django.conf import settings
from django.utils.module_loading import import_string


class UsersConfig(AppConfig):
    name = "televi1.telegram_bot"

    def ready(self):
        from . import dispatchers

        for middleware_path in settings.TELEGRAM_MIDDLEWARE:
            Middleware = import_string(middleware_path)
            dispatchers.dp.update.middleware(Middleware())
