import aiogram
from config.celery_app import app

from televi1.utils.celery import async_task


@async_task(app)
async def send_message(tuser_id: int, message: str):
    from televi1.telegram_bot.models import TelegramUser

    user = await TelegramUser.objects.aget(id=tuser_id)
    aiobot: aiogram.Bot = user.telegramuserprofile.tbot.get_aiobot()
    await aiobot.send_message(chat_id=user.user_tid, text=message)
