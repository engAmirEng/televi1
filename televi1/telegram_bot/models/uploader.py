from __future__ import annotations

import random
import string
from typing import TYPE_CHECKING

from django.contrib.postgres.fields import ArrayField
from django.db import models, transaction

if TYPE_CHECKING:
    from televi1.telegram_bot.dispatchers.base import MustJoin

from televi1.users.models import User
from televi1.utils.models import TimeStampedModel

from . import TelegramMessage, TelegramUser


class TelegramUploaderMessage(TimeStampedModel, models.Model):
    message = models.ForeignKey("TelegramMessage", on_delete=models.CASCADE, related_name="+")
    uploader = models.ForeignKey("TelegramUploader", on_delete=models.CASCADE, related_name="+")
    order = models.IntegerField()


class TelegramUploaderManager(models.Manager):
    @transaction.atomic
    def from_wizard(self, name: str, tmessage_ids: list[int], must_joins: list[MustJoin], created_by: TelegramUser):
        tmessage_qs = TelegramMessage.objects.filter(id__in=tmessage_ids)
        obj = self.model()
        obj.name = name

        obj.must_join_chat_ids = [i["chat_id"] for i in must_joins]
        obj.created_by = created_by
        obj.tbot_id = created_by.tbot_id
        obj.save()

        for i, tmessage_id in enumerate(tmessage_ids):
            tmessage_obj = [i for i in tmessage_qs if i.id == tmessage_id][0]
            tum_obj = TelegramUploaderMessage()
            tum_obj.message = tmessage_obj
            tum_obj.uploader = obj
            tum_obj.order = i
            tum_obj.save()
        return obj


class TelegramUploader(TimeStampedModel, models.Model):
    name = models.CharField(max_length=127)
    tbot = models.ForeignKey("TelegramBot", on_delete=models.CASCADE, related_name="uploaders")
    messages = models.ManyToManyField(
        "TelegramMessage",
        through=TelegramUploaderMessage,
        through_fields=("uploader", "message"),
        related_name="telegramuploaders",
    )
    must_join_chat_ids = ArrayField(base_field=models.BigIntegerField(), size=10)
    created_by = models.ForeignKey(User, related_name="telegramuploaders_createdby", on_delete=models.CASCADE)

    objects = TelegramUploaderManager()


class UploaderLinkManager(models.Manager):
    async def new(self, uploader: TelegramUploader):
        obj = self.model()
        obj.uploader = uploader
        while True:
            queryid = self.model.generate_queryid()
            is_unique = not await self.filter(queryid=queryid).aexists()
            if is_unique:
                break
        obj.queryid = queryid
        await obj.asave()
        return obj


class UploaderLink(TimeStampedModel, models.Model):
    uploader = models.ForeignKey(TelegramUploader, on_delete=models.CASCADE, related_name="uploaderlinks")
    queryid = models.CharField(max_length=31, db_index=True)

    objects = UploaderLinkManager()

    @staticmethod
    def generate_queryid():
        length = random.randint(20, 32)
        allowed_characters = string.ascii_letters + string.digits + "-" + "_"
        queryid = "".join(random.choice(allowed_characters) for _ in range(length))
        return queryid
