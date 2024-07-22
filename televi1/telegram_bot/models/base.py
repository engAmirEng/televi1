from __future__ import annotations

import random
import string
from enum import Enum

from asgiref.sync import sync_to_async
from wonderwords import RandomWord

import aiogram
import aiogram.exceptions
import aiogram.utils.token
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from django.conf import settings
from django.db import models
from django.db.models import UniqueConstraint
from django.utils import timezone
from django.utils.translation import gettext as _

from televi1.users.models import User, UserManager
from televi1.utils.models import TimeStampedModel

from .. import tasks


class TelegramBotManager(models.Manager):
    async def register(
        self, token: str, tid: int, tbot_name: str, tusername: str, added_from: TelegramBot, added_by: User
    ):
        session = AiohttpSession(proxy=settings.TELEGRAM_PROXY)
        aiobot = aiogram.Bot(token, session=session)
        obj: TelegramBot = self.model()
        obj.tid = tid
        obj.title = tbot_name
        obj.tusername = tusername
        obj.api_token = aiobot.token
        obj.secret_token = self.model.generate_secret_token()
        obj.url_specifier = self.model.generate_url_specifier()
        obj.domain_name = (
            self.model.generate_sub_domain_name() + "." + random.choice(settings.TELEGRAM_WEBHOOK_FLYING_DOMAINS)
        )
        obj.is_master = False
        obj.added_by = added_by
        obj.added_from = added_from

        await obj.asave()
        return obj


class TelegramBot(TimeStampedModel, models.Model):
    tid = models.BigIntegerField()
    tusername = models.CharField(max_length=254)
    title = models.CharField(max_length=63)
    api_token = models.CharField(max_length=127)
    secret_token = models.CharField(max_length=255)
    url_specifier = models.CharField(max_length=255, unique=True, db_index=True)
    domain_name = models.CharField(max_length=255)
    is_master = models.BooleanField()
    added_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="telegrambots_addedby")
    added_from = models.ForeignKey(
        "self", on_delete=models.CASCADE, related_name="telegrambots_addedfrom", null=True, blank=True
    )
    webhook_synced_at = models.DateTimeField(null=True, blank=True)
    is_revoked = models.BooleanField(default=False)
    is_powered_off = models.BooleanField(default=False)

    objects = TelegramBotManager()

    @property
    def webhook_url(self):
        return f"{self.domain_name}/{settings.TELEGRAM_WEBHOOK_URL_PREFIX}/{self.url_specifier}/"

    @property
    def is_active(self):
        return self.webhook_synced_at and not self.is_revoked and not self.is_powered_off

    class ChangePowerResult(str, Enum):
        ALREADY_THERE = "already_there"
        DONE = "done"

    async def change_power(self, status: bool):
        if self.is_powered_off == (not status):
            return self.ChangePowerResult.ALREADY_THERE
        self.is_powered_off = not status
        await self.asave()
        return self.ChangePowerResult.DONE

    def get_aiobot(self) -> aiogram.Bot:
        return self.new_aiobot(self.api_token)

    class RegisterResult(str, Enum):
        DONE = "done"
        TOKEN_NOT_A_TOKEN = "token_not_a_token"
        REVOKED_TOKEN = "revoked_token"
        REVOKE_REQUIRED = "revoke_required"
        ALREADY_ADDED = "added_already"

    @classmethod
    async def do_register(
        cls, token: str, added_from_bot_obj: TelegramBot, added_by_user_obj: User
    ) -> (TelegramBot | None, RegisterResult):
        try:
            aiogram.utils.token.validate_token(token)
        except aiogram.utils.token.TokenValidationError:
            return None, cls.RegisterResult.TOKEN_NOT_A_TOKEN

        new_aiobot = cls.new_aiobot(token)
        try:
            new_aiobot_user = await new_aiobot.get_me()
        except aiogram.exceptions.TelegramUnauthorizedError:
            return None, cls.RegisterResult.REVOKED_TOKEN
        is_revoke_token_required, revoked_count = await cls.handle_perv_same_bots(
            added_by_user_obj=added_by_user_obj, tid=new_aiobot_user.id, api_token=token
        )
        if is_revoke_token_required:
            return None, cls.RegisterResult.REVOKE_REQUIRED
        user_same_bots_qs = cls.objects.filter(added_by=added_by_user_obj, tid=new_aiobot_user.id)
        if already_added_bot_obj := await user_same_bots_qs.afirst():
            return already_added_bot_obj, cls.RegisterResult.ALREADY_ADDED
        bot_name = await new_aiobot.get_my_name()
        new_bot_obj = await cls.objects.register(
            token=token,
            tid=new_aiobot_user.id,
            tbot_name=bot_name.name,
            tusername=new_aiobot_user.username,
            added_from=added_from_bot_obj,
            added_by=added_by_user_obj,
        )
        await new_bot_obj.sync_webhook()
        return new_bot_obj, cls.RegisterResult.DONE

    async def sync_webhook(self):
        webhook_url = self.webhook_url
        aiobot = self.get_aiobot()
        success = await aiobot.set_webhook(webhook_url, secret_token=self.secret_token)
        self.webhook_synced_at = timezone.now()
        await self.asave()
        assert success

    @classmethod
    async def handle_perv_same_bots(cls, added_by_user_obj: User, tid: int, api_token: str) -> (bool, int):
        """
        call this after you fully asserted that the api_token is valid
        returns: tuple[is_revoke_token_required, revoked_count]
        """

        same_active_bots_qs = cls.objects.filter(tid=tid, is_revoked=False).exclude(added_by=added_by_user_obj)
        if await same_active_bots_qs.aexists():
            if await same_active_bots_qs.filter(api_token=api_token).aexists():
                return True, 0
            count = await same_active_bots_qs.acount()
            if count > 50:
                raise Exception("cannot revoke more than 50 bots")
            async for i in same_active_bots_qs:
                await i.revoke(notify_the_owner=True)
            return False, count
        return False, 0

    async def revoke(self, notify_the_owner: bool):
        self.is_revoked = True
        await self.asave()
        if notify_the_owner:
            tasks.send_message.delay(tuser_id=self.added_by_id, message=str(_("ربات شما معلق شد")))

    @staticmethod
    def generate_secret_token():
        length = random.randint(50, 255)
        allowed_characters = string.ascii_letters + string.digits + "-" + "_"
        secret_token = "".join(random.choice(allowed_characters) for _ in range(length))
        return secret_token

    @staticmethod
    def generate_url_specifier():
        r = RandomWord()
        slash_parts_count = random.randint(1, 4)
        slash_parts = []
        for i in range(slash_parts_count):
            part_count = random.randint(1, 4)
            part = "-".join(r.random_words(amount=part_count, word_max_length=10))
            slash_parts.append(part)
        return "/".join(slash_parts)

    @staticmethod
    def generate_sub_domain_name():
        # TODO
        return "quiet-mangos-shop"

        r = RandomWord()
        part_count = random.randint(1, 4)
        sub_domain_name = "-".join(r.random_words(amount=part_count, word_max_length=10))
        return sub_domain_name

    @staticmethod
    def new_aiobot(token: str) -> aiogram.Bot:
        session = AiohttpSession(proxy=settings.TELEGRAM_PROXY)
        return aiogram.Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML), session=session)


class TelegramUserManager(UserManager):
    async def auto_new_from_user_tevent(self, tbot: TelegramBot, tuser: aiogram.types.User):
        username = await self.make_username(base=tuser.username)
        tuser_obj = await sync_to_async(self.create_user)(username=username, user_tid=tuser.id, tbot=tbot)
        return tuser_obj


class TelegramUser(User, models.Model):
    # user = models.OneToOneField(User, related_name="telegramuserprofile", on_delete=models.CASCADE)
    user_tid = models.BigIntegerField(db_comment="user id in telegram")
    tbot = models.ForeignKey(TelegramBot, related_name="telegramuserprofiles", on_delete=models.CASCADE)

    objects = TelegramUserManager()

    class Meta:
        constraints = [UniqueConstraint(fields=("user_tid", "tbot"), name="unique_tuser_tbot")]
