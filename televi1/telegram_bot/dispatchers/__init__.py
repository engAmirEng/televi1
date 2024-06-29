from aiogram import Dispatcher

from .base import router as base_router

dp = Dispatcher()
dp.include_router(base_router)
