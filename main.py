import asyncio
import os

from aiogram import Dispatcher

from config import API_ID, API_HASH
from db.models import create_tables
from handlers import handlers_admin_post, handlers_export, handlers_admin_digest
from bot import bot
from typing import NoReturn

from logger import logger
from userbot.TGClient import client, create_client


async def main() -> None:
    """
    Основная функция запуска бота

    Эта функция:
    1. Инициализирует таблицы в базе данных
    2. Настраивает логирование
    3. Регистрирует обработчики сообщений
    4. Запускает бота в режиме long-polling

    Шаги выполнения:
    1. Создание таблиц БД (если не существуют)
    2. Настройка уровня логирования (INFO)
    3. Инициализация диспетчера
    4. Регистрация роутеров (пользовательские и административные обработчики)
    5. Удаление ожидающих апдейтов
    6. Запуск опроса серверов Telegram

    Обработка ошибок:
        Ловит и логирует все исключения во время работы
    """
    try:
        # Инициализация таблиц в базе данных
        await create_tables()
        has_session_file = os.path.exists('anon.session')

        if has_session_file:
            logger.info("Обнаружен файл сессии anon.session. Пытаемся подключить Telethon...")
            try:
                # Создаем клиент с сохраненными учетными данными
                created_client = create_client(API_ID, API_HASH)
                await created_client.connect()

                if await created_client.is_user_authorized():
                    logger.info("Telethon успешно подключен при старте")
                else:
                    logger.warning("Файл сессии есть, но пользователь не авторизован")
                    await created_client.disconnect()
            except Exception as e:
                logger.error(f"Ошибка при подключении Telethon: {e}")
        else:
            logger.info("Файл сессии не найден или отсутствуют учетные данные")

        # Создание диспетчера для обработки событий
        dp: Dispatcher = Dispatcher()

        # Регистрация роутеров
        dp.include_router(handlers_admin_post.post_router)
        dp.include_router(handlers_admin_digest.digest_router)
        dp.include_router(handlers_export.export_router)
        logger.info("Роутеры успешно зарегистрированы")

        # Удаление вебхука для очистки ожидающих обновлений
        logger.info("Ожидающие обновления очищены")

        current_client = client()
        if current_client and not current_client.is_connected():
            try:
                await current_client.connect()
                logger.info('Telethon client reconnected.')
            except Exception as e:
                logger.error(f"Ошибка переподключения: {e}")
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Ожидающие обновления очищены")
        # Запуск бота в режиме long-polling
        logger.info("Запуск бота в режиме long-polling...")
        await dp.start_polling(bot)


    except Exception as e:
        logger.exception(f"Критическая ошибка: {str(e)}")
        raise


def run_app() -> NoReturn:
    """
    Точка входа для запуска приложения

    Эта функция:
    1. Запускает асинхронную main функцию
    2. Обрабатывает KeyboardInterrupt (Ctrl+C) для корректного завершения
    3. Гарантирует закрытие ресурсов при завершении работы

    Особенности:
        - Использует asyncio.run для запуска асинхронного приложения
        - Перехватывает прерывание с клавиатуры для чистого выхода
        - Логирует сообщение о завершении работы
    """
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Работа бота принудительно завершена пользователем")
    finally:
        logger.info("Приложение завершило работу")


# Точка входа при запуске скрипта
if __name__ == '__main__':
    run_app()
