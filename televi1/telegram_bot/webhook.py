import json
import secrets

from asgiref.sync import sync_to_async

from aiogram import Dispatcher
from aiogram.types import Update
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404
from rest_framework import status

from televi1.utils.decorators import require_http_methods

from . import models


def get_webhook_view(dp: Dispatcher):
    @require_http_methods(["POST"])
    async def webhook_view(request, url_specifier: str):
        telegram_bot_obj = await sync_to_async(get_object_or_404)(
            models.TelegramBot.objects.filter(url_specifier=url_specifier).select_related("added_by")
        )
        request_secret_token = request.headers.get("x-telegram-bot-api-secret-token")

        if request_secret_token is None or not secrets.compare_digest(
            request_secret_token, telegram_bot_obj.secret_token
        ):
            return HttpResponseForbidden()

        bot = telegram_bot_obj.get_aiobot()

        update = Update.model_validate(json.loads(request.body), context={})
        kw = {"aiobot": bot, "bot_obj": telegram_bot_obj}
        await dp.feed_webhook_update(bot=bot, update=update, **kw)
        return HttpResponse(status=status.HTTP_200_OK)

    return webhook_view
