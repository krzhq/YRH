import asyncio
import logging
import os
from pathlib import Path
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeDefault, MenuButtonCommands
from dotenv import load_dotenv
from app.database.store import Store
from app.handlers.bot import router
from app.handlers.discovery import router as discovery_router
from app.handlers.analytics import router as analytics_router
from app.services.notifications import NotificationDispatcher
from app.database.mvp_migration import migrate_mvp
from app.database.discovery_migration import migrate
from app.database.release_migration import migrate_release
from app.database.statistics_migration import migrate_statistics
from app.services.quiz_storage import QuizStorage
from aiogram.fsm.storage.memory import SimpleEventIsolation

async def configure_menu(bot):
    await bot.set_my_commands([BotCommand(command='account', description='Аккаунт'), BotCommand(command='finish', description='Завершить'), BotCommand(command='help', description='Помощь'), BotCommand(command='start', description='Главная')], scope=BotCommandScopeDefault())
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())

async def main():
    load_dotenv(Path(__file__).with_name('.env'))
    token = os.getenv('BOT_TOKEN', '')
    password = os.getenv('ADMIN_INITIAL_PASSWORD', '')
    if not token or token == 'replace_with_botfather_token':
        raise ValueError('Set BOT_TOKEN in .env')
    store = Store(Path(__file__).with_name('perfect_restaurant.db'))
    await store.initialize(password)
    await asyncio.to_thread(migrate, store.path)
    await asyncio.to_thread(migrate_mvp, store.path)
    await asyncio.to_thread(migrate_release, store.path)
    await asyncio.to_thread(migrate_statistics, store.path)
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    notifications = NotificationDispatcher(store, bot)
    dp = Dispatcher(storage=QuizStorage(store), events_isolation=SimpleEventIsolation())
    dp.include_router(discovery_router)
    dp.include_router(analytics_router)
    dp.include_router(router)
    task = asyncio.create_task(notifications.run())
    try:
        await configure_menu(bot)
        await dp.start_polling(bot, store=store, notifications=notifications)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await bot.session.close()

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())

