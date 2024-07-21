from collections.abc import Awaitable, Callable
from typing import Any

import aiogram
from aiogram import BaseMiddleware
from django.contrib.auth.models import AnonymousUser
from django.utils.translation import gettext as _

from televi1.users.models import User

from . import models
from .models import TelegramUser


class CommonMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[aiogram.types.TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: aiogram.types.TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        event_chat: aiogram.types.Chat = data["event_chat"]
        event_from_user: aiogram.types.User = data["event_from_user"]
        bot_obj: models.TelegramBot = data["bot_obj"]
        aiobot: aiogram.Bot = data["aiobot"]
        if bot_obj.is_powered_off:
            owner_tuser_r = await bot_obj.added_by
            assert isinstance(owner_tuser_r, TelegramUser)
            if owner_tuser_r == event_from_user.id:
                base_bot = await models.TelegramBot.objects.aget(id=bot_obj.added_from_id)
                text = _("ربات شما خاموش است، از طریق {0} فعال نمایید").format(f"@{base_bot.tusername}")
                await aiobot.send_message(chat_id=event_chat.id, text=text)
            return
        return await handler(event, data)


class AuthenticationMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[aiogram.types.TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: aiogram.types.TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        event_chat: aiogram.types.Chat = data["event_chat"]
        event_from_user: aiogram.types.User = data["event_from_user"]
        bot_obj: models.TelegramBot = data["bot_obj"]
        tuser = None
        try:
            tuser = (
                await TelegramUser.objects.filter(user_tid=event_from_user.id, tbot_id=bot_obj.id)
                .select_related("tbot")
                .aget()
            )
        except User.DoesNotExist:
            if event_chat.type == "private":
                tuser = await models.TelegramUser.objects.auto_new_from_user_tevent(
                    tbot=bot_obj, tuser=event_from_user
                )

        data.update(user=tuser or AnonymousUser())
        return await handler(event, data)
