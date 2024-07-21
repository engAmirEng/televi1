from __future__ import annotations

from asgiref.sync import async_to_sync, sync_to_async
from polymorphic.models import PolymorphicModel

import aiogram
import aiogram.exceptions
import aiogram.utils.token
from django.db import models, transaction
from django.db.models import CheckConstraint, Q, UniqueConstraint

from televi1.users.models import User
from televi1.utils.models import TimeStampedModel

from . import TelegramBot


class TelegramMessageEntity(TimeStampedModel, models.Model):
    class Type(models.TextChoices):
        MENTION = "mention"
        HASHTAG = "hashtag"
        CACHTAG = "cashtag"
        BOT_COMMAND = "bot_command"
        URL = "url"
        EMAIL = "email"
        PHONE_NUMBER = "phone_number"
        BOLD = "bold"
        ITALIC = "italic"
        UNDERLINE = "underline"
        STRIKETHROUGH = "strikethrough"
        SPOILER = "spoiler"
        BLOCKQUOTE = "blockquote"
        EXPANDABLE_BLOCKQUOTE = "expandable_blockquote"
        CODE = "code"
        PRE = "pre"
        TEXT_LINK = "text_link"
        TEXT_MENTION = "text_mention"
        CUSTOM_EMOJI = "custom_emoji"

    type = models.CharField(max_length=31, choices=Type.choices)
    offset = models.IntegerField()
    length = models.IntegerField()

    telegram_message_text = models.ForeignKey(
        "TelegramMessage", on_delete=models.CASCADE, related_name="text_entities", null=True, blank=True
    )
    telegram_message_caption = models.ForeignKey(
        "TelegramMessage", on_delete=models.CASCADE, related_name="caption_entities", null=True, blank=True
    )

    class Meta:
        constraints = [
            CheckConstraint(
                check=Q(telegram_message_text__isnull=True, telegram_message_caption__isnull=False)
                | Q(telegram_message_text__isnull=False, telegram_message_caption__isnull=True),
                name="either_text_or_caption_entity",
            )
        ]

    @classmethod
    async def from_aio(
        cls, tmessage_entity: aiogram.types.MessageEntity, telegram_message: TelegramMessage, is_caption: bool
    ):
        obj = cls()
        if is_caption:
            obj.telegram_message_caption = telegram_message
        else:
            obj.telegram_message_text = telegram_message
        obj.type = tmessage_entity.type
        obj.offset = tmessage_entity.offset
        obj.length = tmessage_entity.length
        await obj.asave()
        return obj

    def to_aio(self):
        return aiogram.types.MessageEntity(type=self.type, offset=self.offset, length=self.length)


class TelegramMessageQuerySet(models.QuerySet):
    def select_related_all_entities(self):
        return self.select_related("video", "document")


class TelegramMessageManager(models.Manager):
    def get_queryset(self):
        return TelegramMessageQuerySet(model=self.model, using=self._db, hints=self._hints)

    async def new_from_aio_for_uploader(self, tmessage: aiogram.types.Message, sent_by: User, bot: TelegramBot):
        obj = await sync_to_async(self.model.from_aio)(tmessage=tmessage, sent_by=sent_by, bot=bot)
        return obj


class TelegramMessage(TimeStampedModel, models.Model):
    class ContentType(models.TextChoices):
        TEXT = "text"
        AUDIO = "audio"
        DOCUMENT = "document"
        PHOTO = "photo"
        VIDEO = "video"
        VOICE = "voice"

    tid = models.IntegerField(unique=True, db_comment="id of message in telegram server")
    bot = models.ForeignKey("TelegramBot", on_delete=models.CASCADE, related_name="telegrammessages")
    sent_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="telegrammessages_sentby")
    content_type = models.CharField(max_length=255, choices=ContentType.choices)
    text = models.TextField(null=True, blank=True)
    caption = models.TextField(null=True, blank=True)
    audio = models.ForeignKey(
        "TelegramAudio", on_delete=models.CASCADE, related_name="telegrammessages", null=True, blank=True
    )
    document = models.ForeignKey(
        "TelegramDocument", on_delete=models.CASCADE, related_name="telegrammessages", null=True, blank=True
    )
    photo = models.ManyToManyField("TelegramPhotoSize", related_name="telegrammessages")
    video = models.ForeignKey(
        "TelegramVideo", on_delete=models.CASCADE, related_name="telegrammessages", null=True, blank=True
    )
    voice = models.ForeignKey(
        "TelegramVoice", on_delete=models.CASCADE, related_name="telegrammessages", null=True, blank=True
    )
    media_group_id = models.CharField(max_length=254, null=True, blank=True)

    objects = TelegramMessageManager()

    @classmethod
    @transaction.atomic
    def from_aio(cls, tmessage: aiogram.types.Message, sent_by: User, bot: TelegramBot):
        obj = cls.objects.filter(tid=tmessage.message_id).first()
        if obj:
            return obj
        obj = cls()
        obj.tid = tmessage.message_id
        obj.bot = bot
        obj.sent_by = sent_by
        obj.content_type = tmessage.content_type
        obj.text = tmessage.text
        obj.caption = tmessage.caption

        if tmessage.audio:
            obj.audio = async_to_sync(TelegramAudio.from_aio)(taudio=tmessage.audio, bot=bot)
        if tmessage.document:
            obj.document = async_to_sync(TelegramDocument.from_aio)(tdocument=tmessage.document, bot=bot)
        if tmessage.video:
            obj.video = async_to_sync(TelegramVideo.from_aio)(tvideo=tmessage.video, bot=bot)
        if tmessage.voice:
            obj.voice = async_to_sync(TelegramVoice.from_aio)(tvoice=tmessage.voice, bot=bot)
        obj.save()
        if tmessage.photo:
            for tphoto in tmessage.photo:
                obj.photo.add(async_to_sync(TelegramPhotoSize.from_aio)(tphoto_size=tphoto, bot=bot))
        if tmessage.entities is not None:
            for i in tmessage.entities:
                async_to_sync(TelegramMessageEntity.from_aio)(
                    tmessage_entity=i, telegram_message=obj, is_caption=False
                )
        if tmessage.caption_entities is not None:
            for i in tmessage.caption_entities:
                async_to_sync(TelegramMessageEntity.from_aio)(tmessage_entity=i, telegram_message=obj, is_caption=True)

        return obj

    async def to_aio_params(self) -> tuple[str, dict]:
        if self.media_group_id:
            method_name = aiogram.Bot.send_media_group.__name__
        elif self.content_type == self.ContentType.PHOTO:
            method_name = aiogram.Bot.send_photo.__name__
            biggest = await self.photo.order_by("-file_size").afirst()
            kw = {
                "photo": biggest.file_id,
                "caption": self.caption,
                "caption_entities": [i.to_aio() async for i in self.caption_entities.all()],
                "parse_mode": None,
            }
        elif self.content_type == self.ContentType.VIDEO:
            method_name = aiogram.Bot.send_video.__name__
            kw = {
                "video": self.video.file_id,
                "caption": self.caption,
                "caption_entities": [i.to_aio() async for i in self.caption_entities.all()],
                "parse_mode": None,
            }
        elif self.content_type == self.ContentType.DOCUMENT:
            method_name = aiogram.Bot.send_document.__name__
            kw = {
                "document": self.document.file_id,
                "caption": self.caption,
                "caption_entities": [i.to_aio() async for i in self.caption_entities.all()],
                "parse_mode": None,
            }
        else:
            raise NotImplementedError
        return method_name, kw


class TelegramFile(TimeStampedModel, PolymorphicModel, models.Model):
    bot = models.ForeignKey(TelegramBot, on_delete=models.CASCADE, related_name="telegram_files")
    file_id = models.CharField(max_length=255)
    file_unique_id = models.CharField(max_length=255)
    file_size = models.BigIntegerField(null=True, blank=True)

    class Meta:
        constraints = [UniqueConstraint(fields=("file_id", "file_unique_id"), name="unique_file")]


class TelegramAudio(TelegramFile):
    duration = models.IntegerField()
    performer = models.CharField(max_length=255, null=True, blank=True)
    title = models.CharField(max_length=255, null=True, blank=True)
    file_name = models.CharField(max_length=255, null=True, blank=True)
    mime_type = models.CharField(max_length=255, null=True, blank=True)
    thumbnail = models.ForeignKey(
        "TelegramPhotoSize", on_delete=models.CASCADE, related_name="telegramaudio", null=True, blank=True
    )

    @classmethod
    async def from_aio(cls, taudio: aiogram.types.Audio, bot: TelegramBot):
        obj = await cls.objects.filter(file_id=taudio.file_id).afirst()
        if obj:
            return obj
        obj = cls()
        obj.bot = bot
        obj.file_id = taudio.file_id
        obj.file_unique_id = taudio.file_unique_id
        obj.file_size = taudio.file_size
        obj.performer = taudio.performer
        obj.title = taudio.title
        obj.file_name = taudio.file_name
        obj.mime_type = taudio.mime_type
        obj.thumbnail = await TelegramPhotoSize.from_aio(tphoto_size=taudio.thumbnail)
        await obj.asave()
        return obj


class TelegramVoice(TelegramFile):
    duration = models.IntegerField()
    mime_type = models.CharField(max_length=255, null=True, blank=True)

    @classmethod
    async def from_aio(cls, tvoice: aiogram.types.Voice, bot: TelegramBot):
        obj = await cls.objects.filter(file_id=tvoice.file_id).afirst()
        if obj:
            return obj
        obj = cls()
        obj.bot = bot
        obj.file_id = tvoice.file_id
        obj.file_unique_id = tvoice.file_unique_id
        obj.file_size = tvoice.file_size
        obj.duration = tvoice.duration
        obj.mime_type = tvoice.mime_type
        await obj.asave()
        return obj


class TelegramPhotoSize(TelegramFile):
    width = models.IntegerField()
    height = models.IntegerField()

    @classmethod
    async def from_aio(cls, tphoto_size: aiogram.types.PhotoSize, bot: TelegramBot):
        obj = await cls.objects.filter(file_id=tphoto_size.file_id).afirst()
        if obj:
            return obj
        obj = cls()
        obj.bot = bot
        obj.file_id = tphoto_size.file_id
        obj.file_unique_id = tphoto_size.file_unique_id
        obj.file_size = tphoto_size.file_size
        obj.width = tphoto_size.width
        obj.height = tphoto_size.height
        await obj.asave()
        return obj


class TelegramDocument(TelegramFile):
    file_name = models.CharField(max_length=255, null=True, blank=True)
    mime_type = models.CharField(max_length=255, null=True, blank=True)

    thumbnail = models.ForeignKey(
        "TelegramPhotoSize", on_delete=models.CASCADE, related_name="telegramdocument", null=True, blank=True
    )

    @classmethod
    async def from_aio(cls, tdocument: aiogram.types.Document, bot: TelegramBot):
        obj = await cls.objects.filter(file_id=tdocument.file_id).afirst()
        if obj:
            return obj
        obj = cls()
        obj.bot = bot
        obj.file_id = tdocument.file_id
        obj.file_unique_id = tdocument.file_unique_id
        obj.file_size = tdocument.file_size
        obj.file_name = tdocument.file_name
        obj.mime_type = tdocument.mime_type
        obj.thumbnail = await TelegramPhotoSize.from_aio(tphoto_size=tdocument.thumbnail, bot=bot)
        await obj.asave()
        return obj


class TelegramVideo(TelegramFile):
    width = models.IntegerField()
    height = models.IntegerField()
    duration = models.IntegerField()
    file_name = models.CharField(max_length=255, null=True, blank=True)
    mime_type = models.CharField(max_length=255, null=True, blank=True)
    thumbnail = models.ForeignKey(
        "TelegramPhotoSize", on_delete=models.CASCADE, related_name="telegramvideo", null=True, blank=True
    )

    @classmethod
    async def from_aio(cls, tvideo: aiogram.types.Video, bot: TelegramBot):
        obj = await cls.objects.filter(file_id=tvideo.file_id).afirst()
        if obj:
            return obj
        obj = cls()
        obj.bot = bot
        obj.file_id = tvideo.file_id
        obj.file_unique_id = tvideo.file_unique_id
        obj.file_size = tvideo.file_size
        obj.width = tvideo.width
        obj.height = tvideo.height
        obj.duration = tvideo.duration
        obj.file_name = tvideo.file_name
        obj.mime_type = tvideo.mime_type
        obj.thumbnail = await TelegramPhotoSize.from_aio(tphoto_size=tvideo.thumbnail, bot=bot)
        await obj.asave()
        return obj
