import json
import secrets

from asgiref.sync import sync_to_async

from aiogram import Dispatcher
from aiogram.types import InputFile, Update
from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404
from rest_framework import status

from televi1.utils.decorators import require_http_methods

from . import models


def get_webhook_view(dp: Dispatcher):
    @require_http_methods(["POST"])
    async def webhook_view(request, url_specifier: str):
        telegram_bot_obj: models.TelegramBot = await sync_to_async(get_object_or_404)(
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
        method = await dp.feed_webhook_update(bot=bot, update=update, **kw)
        data = {}
        if method is not None:
            if not settings.TELEGRAM_PREFER_REPLY_TO_WEBHOOK:
                await method
            else:
                method_name = method.__api_method__
                data["method"] = method_name

                files: dict[str, InputFile] = {}
                for key, value in method.model_dump(warnings=False).items():
                    value = bot.session.prepare_value(value, bot=bot, files=files, _dumps_json=False)
                    if not value:
                        continue
                    data[key] = value
                for key, value in files.items():
                    raise NotImplementedError
                    # async_gen = value.read(bot)
                    # chunks = []
                    # async for chunk in async_gen:
                    #     chunks.append(chunk)
                    # data[key] = b''.join(chunks)

        return HttpResponse(json.dumps(data), status=status.HTTP_200_OK, headers={"Content-Type": "application/json"})

    return webhook_view
