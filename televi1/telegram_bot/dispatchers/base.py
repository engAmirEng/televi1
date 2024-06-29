import logging

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

router = Router(name=__name__)


@router.message(CommandStart())
async def command_start_handler(message: Message) -> None:
    await message.answer("hello world")
    logging.info("hello world")
