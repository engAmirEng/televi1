import asyncio
import logging
from enum import Enum
from typing import Optional, TypedDict, Union

from asgiref.sync import sync_to_async

import aiogram.exceptions
from aiogram import Bot, Router
from aiogram.filters import CommandStart, Filter
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, KeyboardButtonRequestChat, Message
from aiogram.utils.deep_linking import create_deep_link
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from django.http import QueryDict
from django.template.loader import render_to_string
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as __

from ...users.models import User
from .. import models
from ..models import TelegramUser

router = Router(name=__name__)


NEW_CONTENT_R = __("آپلود مطلب جدید")
END_R = __("اتمام")
CANCEL_R = __("لفو")
RESET_R = __("از اول")
REGISTER_NEW_BOT_R = __("ثبت ربات جدید")
BOT_LIST_R = __("ربات های شما")


class QueryPathName(str, Enum):
    UPLOADER_LINK = "uploader_link"


def query_magic_dispatcher(pathname: QueryPathName):
    if pathname == QueryPathName.UPLOADER_LINK:
        # `a`ction == `u`p`l`oadder`l`ink
        return aiogram.F.get("a") == "ull"
    raise NotImplementedError


def get_dispatch_query(bot_username: str, pathname: QueryPathName, **kwargs):
    qd = QueryDict(mutable=True)
    if pathname == QueryPathName.UPLOADER_LINK:
        qd.update({"a": "ull", "k": kwargs["key"]})
        res = qd.urlencode()
        return create_deep_link(username=bot_username, link_type="start", payload=res, encode=True)
    raise NotImplementedError


class MasterBotFilter(Filter):
    async def __call__(self, *args, bot_obj: models.TelegramBot, **kwargs) -> bool:
        return bot_obj.is_master


class OwnerBotFilter(Filter):
    async def __call__(
        self, update: Union[Message, CallbackQuery], user: TelegramUser, bot_obj: models.TelegramBot, **kwargs
    ) -> bool:
        assert update.from_user.id == user.user_tid
        added_by = await sync_to_async(bot_obj.added_by.get_real_instance)()
        if isinstance(added_by, TelegramUser):
            return added_by.user_tid == update.from_user.id
        if not bot_obj.is_master:
            logging.info(f"owner of {str(bot_obj)} is not of type TelegramUser")
        return False


class StartCommandQueryFilter(CommandStart):
    def __init__(self, command_magic: Optional[aiogram.MagicFilter] = None, query_magic: [aiogram.MagicFilter] = None):
        super().__init__(deep_link=True, deep_link_encoded=True, magic=command_magic)
        self.query_magic = query_magic

    async def __call__(self, message: Message, bot: Bot):
        result = await super().__call__(message=message, bot=bot)
        if not result:
            return result
        assert isinstance(result, dict)
        command: aiogram.filters.CommandObject = result["command"]
        if not command.args:
            return False
        command_query = QueryDict(command.args)
        result.update(command_query=command_query)
        if self.query_magic:
            command_query_magic_result = self.query_magic.resolve(command_query)
            if not command_query_magic_result:
                raise aiogram.filters.command.CommandException("Rejected via magic filter")
            if isinstance(command_query_magic_result, dict):
                result.update(command_query_magic_result)

        return result


MASTER_PATH_FILTERS = (MasterBotFilter(),)
SUB_OWNER_PATH_FILTERS = (~MasterBotFilter(), OwnerBotFilter())


class SimpleButtonName(str, Enum):
    NEW_CONTENT = "new_content"
    CONTENT_LIST = "content_list"
    REGISTER_NEW_BOT = "register_new_bot"
    BOT_LIST = "bot_list"


class SimpleButtonCallbackData(CallbackData, prefix="simplebutton"):
    button_name: str


@router.message(*MASTER_PATH_FILTERS, CommandStart())
@router.message(*MASTER_PATH_FILTERS, aiogram.F.text == CANCEL_R)
async def master_command_start_handler(
    message: Message, user: User, state: FSMContext, aiobot: Bot, bot_obj: models.TelegramBot
) -> None:
    await state.clear()
    have_any_bots = await models.TelegramBot.objects.filter(added_by=user).aexists()
    ikbuilder = InlineKeyboardBuilder()
    ikbuilder.button(
        text=str(REGISTER_NEW_BOT_R),
        callback_data=SimpleButtonCallbackData(button_name=SimpleButtonName.REGISTER_NEW_BOT),
    )
    if have_any_bots:
        ikbuilder.button(
            text=str(BOT_LIST_R), callback_data=SimpleButtonCallbackData(button_name=SimpleButtonName.BOT_LIST)
        )
    text = render_to_string("telegram_bot/start.thtml")

    await message.answer(text, reply_markup=ikbuilder.as_markup())


@router.message(*SUB_OWNER_PATH_FILTERS, CommandStart(magic=aiogram.F.args == None))
@router.message(*SUB_OWNER_PATH_FILTERS, aiogram.F.text == CANCEL_R)
async def sub_command_start_handler(
    message: Message, state: FSMContext, aiobot: Bot, bot_obj: models.TelegramBot, *args, **kwargs
) -> None:
    await state.clear()
    ikbuilder = InlineKeyboardBuilder()
    ikbuilder.button(
        text=str(NEW_CONTENT_R), callback_data=SimpleButtonCallbackData(button_name=SimpleButtonName.NEW_CONTENT)
    )
    ikbuilder.button(
        text=_("لبست مطالب"), callback_data=SimpleButtonCallbackData(button_name=SimpleButtonName.CONTENT_LIST)
    )
    text = render_to_string("telegram_bot/start.thtml")

    await message.answer(text, reply_markup=ikbuilder.as_markup())


class ContentAction(str, Enum):
    GET = "get"
    GET_LINK = "get_link"


class ContentCallbackData(CallbackData, prefix="content"):
    pk: int
    action: ContentAction


class BotAction(str, Enum):
    GET = "get"
    POWER_OFF = "power_off"
    POWER_ON = "power_on"


class BotCallbackData(CallbackData, prefix="content"):
    pk: int
    action: BotAction


@router.callback_query(
    *SUB_OWNER_PATH_FILTERS, SimpleButtonCallbackData.filter(aiogram.F.button_name == SimpleButtonName.CONTENT_LIST)
)
async def content_list_handler(
    query: CallbackQuery, user: TelegramUser, aiobot: Bot, bot_obj: models.TelegramBot
) -> None:
    contents_qs = models.TelegramUploader.objects.filter(created_by=user, tbot_id=user.tbot_id)
    ikbuilder = InlineKeyboardBuilder()
    async for i in contents_qs:
        ikbuilder.button(text=i.name, callback_data=ContentCallbackData(pk=i.pk, action=ContentAction.GET))
    if not await contents_qs.aexists():
        text = _("شما هنوز مطلبی اضافه نکرده اید.")
        ikbuilder.button(
            text=str(NEW_CONTENT_R), callback_data=SimpleButtonCallbackData(button_name=SimpleButtonName.NEW_CONTENT)
        )
    else:
        text = render_to_string("telegram_bot/content_list.thtml")
    await query.message.edit_text(text, reply_markup=ikbuilder.as_markup())


@router.callback_query(*SUB_OWNER_PATH_FILTERS, ContentCallbackData.filter(aiogram.F.action == ContentAction.GET))
async def content_detail_handler(
    query: CallbackQuery,
    callback_data: ContentCallbackData,
    user: TelegramUser,
    aiobot: Bot,
    bot_obj: models.TelegramBot,
) -> None:
    try:
        telegram_uploader_obj = await models.TelegramUploader.objects.filter(
            created_by=user, tbot_id=user.tbot_id
        ).aget(pk=callback_data.pk)
    except models.TelegramUploader.DoesNotExist:
        await query.answer(_("پیدا نشد"))
        return
    rkbuilder = InlineKeyboardBuilder()
    rkbuilder.button(
        text=_("کرفتن لینک"),
        callback_data=ContentCallbackData(pk=telegram_uploader_obj.pk, action=ContentAction.GET_LINK),
    )
    text = render_to_string("telegram_bot/content_detail.thtml")
    await query.message.edit_text(text, reply_markup=rkbuilder.as_markup())


@router.callback_query(*SUB_OWNER_PATH_FILTERS, ContentCallbackData.filter(aiogram.F.action == ContentAction.GET_LINK))
async def content_get_link_handler(
    query: CallbackQuery,
    callback_data: ContentCallbackData,
    user: TelegramUser,
    aiobot: Bot,
    bot_obj: models.TelegramBot,
) -> None:
    try:
        telegram_uploader_obj = await models.TelegramUploader.objects.filter(
            created_by=user, tbot_id=user.tbot_id
        ).aget(pk=callback_data.pk)
    except models.TelegramUploader.DoesNotExist:
        await query.answer(_("پیدا نشد"))
        return

    # TODO
    ulink = await telegram_uploader_obj.uploaderlinks.alast()
    if ulink is None:
        ulink = await models.UploaderLink.objects.new(telegram_uploader_obj)

    text = get_dispatch_query(bot_username=bot_obj.tusername, pathname=QueryPathName.UPLOADER_LINK, key=ulink.queryid)
    await query.message.reply(text)


@router.message(
    ~MasterBotFilter(), StartCommandQueryFilter(query_magic=query_magic_dispatcher(QueryPathName.UPLOADER_LINK))
)
async def uploader_link_handler(
    message: Message,
    state: FSMContext,
    aiobot: Bot,
    bot_obj: models.TelegramBot,
    command,
    command_query: QueryDict,
    *args,
    **kwargs,
) -> None:
    queryid = command_query.get("k")
    try:
        ulink: models.UploaderLink = (
            await models.UploaderLink.objects.filter(queryid=queryid).select_related("uploader").aget()
        )
    except models.UploaderLink.DoesNotExist:
        logging.error(f"{str(queryid)} not found")
        return
    if ulink.uploader.tbot_id != bot_obj.id:
        logging.error(f"{str(queryid)} is not for {str(bot_obj)}")
        return
    messages_qs = ulink.uploader.messages.all().select_related_all_entities()
    msq_tasks = []
    async for i in messages_qs:
        i: models.TelegramMessage
        send_method, aio_params = await i.to_aio_params()
        method = getattr(aiobot, send_method)
        msq_tasks.append(asyncio.create_task(method(chat_id=message.chat.id, **aio_params)))
    await asyncio.gather(*msq_tasks)


class NewBotSG(StatesGroup):
    token = State()


@router.callback_query(
    *MASTER_PATH_FILTERS, SimpleButtonCallbackData.filter(aiogram.F.button_name == SimpleButtonName.REGISTER_NEW_BOT)
)
async def new_bot_handler(
    query: CallbackQuery, user: User, state: FSMContext, aiobot: Bot, bot_obj: models.TelegramBot
) -> None:
    await state.set_state(NewBotSG.token)
    rkbuilder = ReplyKeyboardBuilder()
    rkbuilder.button(text=str(CANCEL_R))
    text = render_to_string("telegram_bot/new_bot.thtml")
    await query.message.answer(text, reply_markup=rkbuilder.as_markup())


@router.message(*MASTER_PATH_FILTERS, NewBotSG.token)
async def new_bot_token_handler(
    message: Message, user: User, state: FSMContext, aiobot: Bot, bot_obj: models.TelegramBot
) -> None:
    token = message.text
    rkbuilder = ReplyKeyboardBuilder()
    new_bot_obj, result = await models.TelegramBot.do_register(
        token=token, added_from_bot_obj=bot_obj, added_by_user_obj=user
    )
    if result == models.TelegramBot.RegisterResult.TOKEN_NOT_A_TOKEN:
        text = _("لطفا توکن را به درستی ارسال کنید.")
        rkbuilder.button(text=str(CANCEL_R))
    elif result == models.TelegramBot.RegisterResult.REVOKED_TOKEN:
        text = _("این توکن معتبر نیست")
        rkbuilder.button(text=str(CANCEL_R))
    elif result == models.TelegramBot.RegisterResult.DONE:
        await state.clear()
        text = _("ربات شما ساخته شد. حالا برای آپلود مطلب از ربات خود استفاده کنید، {0}").format(
            f"@{new_bot_obj.tusername}"
        )
    elif result == models.TelegramBot.RegisterResult.ALREADY_ADDED:
        text = _("این ربات قبلا اضافه شده، لطفا از قسمت ربات های من آن را مدیریت کنید")
    elif result == models.TelegramBot.RegisterResult.REVOKE_REQUIRED:
        text = render_to_string("telegram_bot/registering_bot/revoke_other.thtml")
    else:
        raise NotImplementedError
    await message.reply(text, reply_markup=rkbuilder.as_markup())


@router.callback_query(
    *MASTER_PATH_FILTERS, SimpleButtonCallbackData.filter(aiogram.F.button_name == SimpleButtonName.BOT_LIST)
)
async def bot_list_handler(
    query: CallbackQuery, user: User, state: FSMContext, aiobot: Bot, bot_obj: models.TelegramBot
) -> None:
    tbots_qs = models.TelegramBot.objects.filter(added_by=user)
    if not tbots_qs.aexists():
        text = _("شما رباتی اضافه نکرده اید")
        await query.message.edit_text(text=text)
        return
    ikbuilder = InlineKeyboardBuilder()
    async for i in tbots_qs:
        btn_text = i.title
        ikbuilder.button(text=btn_text, callback_data=BotCallbackData(pk=i.id, action=BotAction.GET))
    text = render_to_string("telegram_bot/bots_list.thtml")
    await query.message.edit_text(text, reply_markup=ikbuilder.as_markup())


@router.callback_query(*MASTER_PATH_FILTERS, BotCallbackData.filter(aiogram.F.action == BotAction.POWER_OFF))
@router.callback_query(*MASTER_PATH_FILTERS, BotCallbackData.filter(aiogram.F.action == BotAction.POWER_ON))
@router.callback_query(*MASTER_PATH_FILTERS, BotCallbackData.filter(aiogram.F.action == BotAction.GET))
async def bot_detail_handler(
    query: CallbackQuery, callback_data: BotCallbackData, user: User, aiobot: Bot, bot_obj: models.TelegramBot
) -> None:
    bot = await models.TelegramBot.objects.aget(pk=callback_data.pk, added_by=user)
    message_text = ""
    if callback_data.action in (BotAction.POWER_ON, BotAction.POWER_OFF):
        dest_status = callback_data.action == BotAction.POWER_ON
        result = await bot.change_power(status=dest_status)
        if result == models.TelegramBot.ChangePowerResult.ALREADY_THERE:
            message_text = _("ربات {0} از قبل {1} بود.").format(
                f"@{bot.tusername}", _("روشن") if dest_status else _("خاموش")
            )
        elif result == models.TelegramBot.ChangePowerResult.DONE:
            message_text = _("ربات {0} {1} شد.").format(f"@{bot.tusername}", _("روشن") if dest_status else _("خاموش"))
        else:
            raise NotImplementedError

    ikbuilder = InlineKeyboardBuilder()
    ikbuilder.button(
        text=_("روشن کردن") if bot.is_powered_off else _("خاموش کردن"),
        callback_data=BotCallbackData(
            pk=bot.id, action=BotAction.POWER_ON if bot.is_powered_off else BotAction.POWER_OFF
        ),
    )
    text = render_to_string("telegram_bot/bot_detail.thtml", {"bot": bot, "message_text": message_text})
    await query.message.edit_text(text, reply_markup=ikbuilder.as_markup())


class MustJoin(TypedDict):
    chat_id: int
    is_channel: bool


class NewContentSG(StatesGroup):
    name = State()
    messages = State()
    must_joins = State()


@router.callback_query(
    *SUB_OWNER_PATH_FILTERS, SimpleButtonCallbackData.filter(aiogram.F.button_name == SimpleButtonName.NEW_CONTENT)
)
async def new_content_handler(
    query: CallbackQuery, state: FSMContext, aiobot: Bot, bot_obj: models.TelegramBot
) -> None:
    rkbuilder = ReplyKeyboardBuilder()
    rkbuilder.button(text=str(CANCEL_R))
    text = render_to_string("telegram_bot/new_content.thtml")
    await state.set_state(NewContentSG.messages)
    await query.message.answer(text, reply_markup=rkbuilder.as_markup())


@router.message(*SUB_OWNER_PATH_FILTERS, NewContentSG.messages, aiogram.F.text == RESET_R)
async def reset_content_message_handler(
    message: Message, state: FSMContext, aiobot: Bot, bot_obj: models.TelegramBot
) -> None:
    await state.update_data(messages=None)
    rkbuilder = ReplyKeyboardBuilder()
    rkbuilder.button(text=str(CANCEL_R))
    text = render_to_string("telegram_bot/new_content.md")
    await message.answer(text, reply_markup=rkbuilder.as_markup())


@router.message(*SUB_OWNER_PATH_FILTERS, NewContentSG.messages, aiogram.F.text == END_R)
async def end_message_content_handler(
    message: Message, state: FSMContext, aiobot: Bot, bot_obj: models.TelegramBot
) -> None:
    data = await state.get_data()
    messages_up_to_now = data.get("messages") or []
    if len(messages_up_to_now) == 0:
        await aiobot.send_message(message.chat.id, "هنوز ک چیزی اضافه نکردی")
        return
    rkbuilder = ReplyKeyboardBuilder()
    rkbuilder.button(
        text=_("انتخاب کانال"),
        request_chat=KeyboardButtonRequestChat(request_id=58008, chat_is_channel=True, bot_is_member=True),
    )
    rkbuilder.button(
        text=_("انتخاب گروه"),
        request_chat=KeyboardButtonRequestChat(request_id=8008, chat_is_channel=False, bot_is_member=True),
    )
    rkbuilder.button(text=str(CANCEL_R))
    rkbuilder.button(text=str(END_R))
    await state.set_state(NewContentSG.must_joins)
    text = render_to_string("telegram_bot/declare_must_joins.thtml")
    await message.answer(text, reply_markup=rkbuilder.as_markup())


@router.message(*SUB_OWNER_PATH_FILTERS, NewContentSG.messages)
async def new_content_message_handler(
    message: Message, user: User, state: FSMContext, aiobot: Bot, bot_obj: models.TelegramBot
) -> None:
    data = await state.get_data()
    tmessage_ids_up_to_now = data.get("messages") or []
    telegram_message_obj = await models.TelegramMessage.objects.new_from_aio_for_uploader(
        tmessage=message, sent_by=user, bot=bot_obj
    )
    tmessage_ids_up_to_now.append(telegram_message_obj.id)
    await state.update_data(messages=tmessage_ids_up_to_now)
    messages_count = len(tmessage_ids_up_to_now)
    rkbuilder = ReplyKeyboardBuilder()
    rkbuilder.button(text=str(CANCEL_R))
    rkbuilder.button(text=str(RESET_R))
    rkbuilder.button(text=str(END_R))
    text = render_to_string("telegram_bot/keep_adding_content.thtml", {"messages_count": messages_count})
    await message.reply(text, reply_markup=rkbuilder.as_markup())


@router.message(*SUB_OWNER_PATH_FILTERS, NewContentSG.must_joins, aiogram.F.text == RESET_R)
async def reset_content_must_join_handler(
    message: Message, state: FSMContext, aiobot: Bot, bot_obj: models.TelegramBot
) -> None:
    await state.update_data(must_joins=None)
    rkbuilder = ReplyKeyboardBuilder()
    rkbuilder.button(text=str(CANCEL_R))
    rkbuilder.button(text=str(END_R))
    text = render_to_string("telegram_bot/declare_must_joins.md")
    await message.answer(text, reply_markup=rkbuilder.as_markup())


@router.message(*SUB_OWNER_PATH_FILTERS, NewContentSG.must_joins, aiogram.F.text == END_R)
async def end_content_must_join_handler(
    message: Message, user: User, state: FSMContext, aiobot: Bot, bot_obj: models.TelegramBot
) -> None:
    await state.set_state(NewContentSG.name)
    text = _("یک نام وارد کنید:")
    await message.answer(text)


@router.message(
    *SUB_OWNER_PATH_FILTERS, NewContentSG.must_joins, aiogram.F.content_type == aiogram.enums.ContentType.CHAT_SHARED
)
async def new_content_must_joins_handler(
    message: Message, state: FSMContext, aiobot: Bot, bot_obj: models.TelegramBot
) -> None:
    data = await state.get_data()
    must_joins_up_to_now: list[MustJoin] = data.get("must_joins") or []
    must_joins_up_to_now.append(
        {"chat_id": message.chat_shared.chat_id, "is_channel": message.chat_shared.request_id == 58008}
    )
    await state.update_data(must_joins=must_joins_up_to_now)

    rkbuilder = ReplyKeyboardBuilder()
    rkbuilder.button(text=str(CANCEL_R))
    rkbuilder.button(text=str(RESET_R))
    rkbuilder.button(text=str(END_R))
    rkbuilder.button(
        text=_("انتخاب کانال"),
        request_chat=KeyboardButtonRequestChat(request_id=58008, chat_is_channel=True, bot_is_member=True),
    )
    rkbuilder.button(
        text=_("انتخاب گروه"),
        request_chat=KeyboardButtonRequestChat(request_id=8008, chat_is_channel=False, bot_is_member=True),
    )
    text = render_to_string(
        "telegram_bot/keep_adding_must_joins.thtml", {"must_joins_count": len(must_joins_up_to_now)}
    )
    await message.reply(text, reply_markup=rkbuilder.as_markup())


@router.message(*SUB_OWNER_PATH_FILTERS, NewContentSG.name)
async def new_content_name_handler(
    message: Message, user: User, state: FSMContext, aiobot: Bot, bot_obj: models.TelegramBot
) -> None:
    await state.update_data(name=message.text)
    data = await state.get_data()
    tmessage_ids_up_to_now = data.get("messages") or []
    must_joins_up_to_now: list[MustJoin] = data.get("must_joins") or []
    name = data["name"]
    uploader_obj = await sync_to_async(models.TelegramUploader.objects.from_wizard)(
        name=name, tmessage_ids=tmessage_ids_up_to_now, must_joins=must_joins_up_to_now, created_by=user
    )
    await state.clear()

    text = render_to_string(
        "telegram_bot/content_successfully_added.thtml", {"messages_count": len(tmessage_ids_up_to_now), "name": name}
    )
    await message.answer(text)
