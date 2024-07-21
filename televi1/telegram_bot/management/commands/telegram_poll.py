import asyncio

from django.core.management import BaseCommand

from ... import dispatchers, models


class Command(BaseCommand):
    help = "Starts telegram bot polling"

    def handle(self, *args, **options):
        first_10_telegram_bots = list(models.TelegramBot.objects.all()[:10])

        async def main() -> None:
            polling_tasks = []
            for i in first_10_telegram_bots:
                bot = i.get_aiobot()
                kw = {"aiobot": bot, "bot_obj": i}
                polling_task = dispatchers.dp.start_polling(bot, **kw)
                polling_tasks.append(polling_task)

            await asyncio.gather(*polling_tasks)

        asyncio.run(main())
