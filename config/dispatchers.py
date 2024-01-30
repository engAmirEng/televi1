from aiogram import Dispatcher

from televi1.core.dispatchers import router as core_router

dp = Dispatcher()
dp.include_router(core_router)
