import datetime
from datetime import timedelta

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, KeyboardButton, \
    ReplyKeyboardMarkup, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select

from ai_gen import post_digest
from config import ADMIN_IDS, CHANEL_ID
from db.digests import save_digest, get_digest_by_hash, update_digest_edit_text, mark_digest_published
from db.models import Session, Post
from logger import logger
from bot import bot
from aiogram.exceptions import TelegramBadRequest
import html

digest_router = Router()


class DigestStates(StatesGroup):
    """Состояния для редактирования дайджеста"""
    waiting_digest_edit = State()


# Хранилище для временных дайджестов (в реальном проекте лучше использовать Redis или БД)
_digest_storage = {}


def _create_digest_keyboard(digest_hash: str, parse_mode: str = "HTML") -> InlineKeyboardMarkup:
    """Создать клавиатуру для дайджеста"""
    markup_emoji = "✅" if parse_mode == "HTML" else "❌"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{markup_emoji} Разметка",
                    callback_data=f"toggle_digest_parse:{digest_hash}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Редактировать",
                    callback_data=f"edit_digest:{digest_hash}"
                ),
                InlineKeyboardButton(
                    text="📢 Опубликовать",
                    callback_data=f"publish_digest:{digest_hash}"
                )
            ]
        ]
    )
    return keyboard


@digest_router.callback_query(F.data == "do_digest")
async def do_digest_callback(callback: CallbackQuery):
    """Обработчик формирования дайджеста"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("🚫 Доступ запрещен", show_alert=True)
        return

    try:
        await callback.answer("🔄 Проверяем посты для дайджеста...", show_alert=False)

        # Получаем текущее время и время 24 часа назад
        now = datetime.datetime.now()
        time_24h_ago = now - timedelta(hours=24)

        # Получаем посты за последние 24 часа с digest=True
        async with Session() as session:
            stmt = select(Post).where(
                Post.digest == True,
                Post.received_at >= time_24h_ago
            ).order_by(Post.received_at.desc())

            result = await session.execute(stmt)
            digest_posts = result.scalars().all()

        # Проверяем, есть ли посты
        if not digest_posts:
            await callback.answer("❌ Нет постов за последние 24 часа, добавленных в дайджест", show_alert=True)
            return

        # Отправляем сообщение о начале генерации
        processing_msg = await callback.message.answer("🔄 Генерация дайджеста...")

        # Формируем список сообщений для AI
        messages_to_ai = []
        post_ids = []
        for post in digest_posts:
            if post.text:  # Проверяем, есть ли текст
                messages_to_ai.append({
                    "role": "user",
                    "content": post.text
                })
                post_ids.append(post.id)

        # Генерируем дайджест
        digest_text = await post_digest(messages_to_ai)

        # Проверяем на ошибку генерации
        if "Ошибка при генерации текста" in digest_text:
            await processing_msg.edit_text(f"❌ {digest_text}")
            return

        # Сохраняем дайджест в базу
        digest = await save_digest(
            digest_text=digest_text,
            post_ids=post_ids
        )

        await processing_msg.edit_text(
            f"{digest_text}",
            parse_mode="HTML",
            reply_markup=_create_digest_keyboard(digest.digest_hash)
        )

        logger.info(
            f"Дайджест сгенерирован администратором {callback.from_user.id}. Использовано постов: {len(digest_posts)}")

    except Exception as e:
        logger.error(f"Ошибка в do_digest_callback: {e}")
        try:
            await callback.answer(f"❌ Ошибка: {str(e)[:100]}", show_alert=True)
        except:
            await callback.message.answer(f"❌ Ошибка при формировании дайджеста: {str(e)[:100]}")


# Обновим функцию toggle_digest_parse_callback
@digest_router.callback_query(F.data.startswith("toggle_digest_parse:"))
async def toggle_digest_parse_callback(callback: CallbackQuery):
    """Обработчик переключения разметки для дайджеста"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("🚫 Доступ запрещен", show_alert=True)
        return

    try:
        # Парсим callback_data
        data_parts = callback.data.split(":")
        if len(data_parts) != 2:
            await callback.answer("❌ Ошибка формата", show_alert=True)
            return

        _, digest_hash = data_parts

        # Получаем дайджест из базы
        digest = await get_digest_by_hash(digest_hash)
        if not digest:
            await callback.answer("❌ Дайджест не найден в базе данных", show_alert=True)
            return

        # Используем отредактированный текст, если он есть, иначе сгенерированный
        text = digest.edit_text if digest.edit_text else digest.text

        # Получаем текущий режим разметки из кнопки
        current_parse_mode = "HTML"
        if callback.message.reply_markup:
            for row in callback.message.reply_markup.inline_keyboard:
                for button in row:
                    if button.text and "Разметка" in button.text:
                        if "✅" in button.text:
                            current_parse_mode = "HTML"
                        elif "❌" in button.text:
                            current_parse_mode = None
                        break

        # Определяем новый режим парсинга
        new_parse_mode = None if current_parse_mode == "HTML" else "HTML"

        # Обновляем сообщение с новым режимом парсинга
        try:
            await callback.message.edit_text(
                text=text,
                parse_mode=new_parse_mode,
                reply_markup=_create_digest_keyboard(digest_hash, new_parse_mode)
            )
            await callback.answer(f"Разметка {'включена' if new_parse_mode == 'HTML' else 'отключена'}!")
        except TelegramBadRequest as e:
            if "message is not modified" in str(e).lower():
                await callback.answer("Сообщение не изменено", show_alert=False)
            elif "can't parse entities" in str(e).lower():
                try:
                    # Пробуем отправить без разметки
                    await callback.message.edit_text(
                        text=html.escape(text),
                        parse_mode=None,
                        reply_markup=_create_digest_keyboard(digest_hash)
                    )
                    await callback.answer("⚠️ Автоматически отключена HTML разметка из-за ошибки", show_alert=True)
                except Exception as fallback_error:
                    await callback.answer(f"❌ Ошибка: {str(fallback_error)[:100]}", show_alert=True)
            else:
                await callback.answer(f"❌ Ошибка редактирования: {str(e)[:100]}", show_alert=True)
                logger.error(f"Ошибка редактирования дайджеста: {e}")

    except Exception as e:
        logger.error(f"Ошибка в toggle_digest_parse_callback: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)



@digest_router.callback_query(F.data.startswith("edit_digest:"))
async def edit_digest_callback(callback: CallbackQuery, state: FSMContext):
    """Обработчик начала редактирования дайджеста"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("🚫 Доступ запрещен", show_alert=True)
        return

    try:
        # Парсим callback_data
        data_parts = callback.data.split(":")
        if len(data_parts) != 2:
            await callback.answer("❌ Ошибка формата", show_alert=True)
            return

        _, digest_hash = data_parts

        # Получаем дайджест из базы
        digest = await get_digest_by_hash(digest_hash)
        if not digest:
            await callback.answer("❌ Дайджест не найден в базе данных", show_alert=True)
            return

        # Используем отредактированный текст, если он есть, иначе сгенерированный
        text = digest.edit_text if digest.edit_text else digest.text

        # Сохраняем данные в состоянии
        await state.update_data(
            digest_hash=digest_hash,
            original_digest=text,
            chat_id=callback.from_user.id
        )

        # Отправляем сообщение с просьбой отредактировать
        await callback.message.answer(
            "Скопируйте дайджест без разметки и отредактируйте его, результат отправьте мне:\n\n"
            f"{text}",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="Отмена")]],
                resize_keyboard=True
            ),
            parse_mode=None
        )

        # Устанавливаем состояние ожидания отредактированного текста
        await state.set_state(DigestStates.waiting_digest_edit)
        await callback.answer("✏️ Готов к редактированию. Отправьте исправленный дайджест.", show_alert=False)

    except Exception as e:
        logger.error(f"Ошибка в edit_digest_callback: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


# Обновим функцию process_edited_digest
@digest_router.message(DigestStates.waiting_digest_edit, F.text)
async def process_edited_digest(message: Message, state: FSMContext):
    """Обработчик получения отредактированного дайджеста - отправляет новое сообщение"""
    if message.from_user.id not in ADMIN_IDS:
        return

    # Проверяем отмену
    if message.text == "Отмена":
        await state.clear()
        await message.answer("Редактирование дайджеста отменено")
        return

    try:
        # Получаем данные из состояния
        data = await state.get_data()
        digest_hash = data.get('digest_hash')
        chat_id = data.get('chat_id')

        if not digest_hash:
            await message.answer("❌ Ошибка: не найдены данные дайджеста")
            await state.clear()
            return

        # Обновляем дайджест в базе данных
        success = await update_digest_edit_text(digest_hash, message.text)
        if not success:
            await message.answer("❌ Ошибка при сохранении отредактированного дайджеста")
            await state.clear()
            return

        # Отправляем новое сообщение с отредактированным дайджестом и кнопками (аналогично постам)
        await message.answer(
            "✅ Дайджест успешно отредактирован и сохранен!",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="Ок")]],
                resize_keyboard=True,
                one_time_keyboard=True
            )
        )

        # Отправляем новое сообщение с отредактированным дайджестом и кнопками управления
        await bot.send_message(
            chat_id=chat_id,
            text=f"📋 <b>Отредактированный дайджест:</b>\n\n{message.text}",
            parse_mode=None,  # по умолчанию без разметки
            reply_markup=_create_digest_keyboard(digest_hash)
        )

        await state.clear()

    except Exception as e:
        logger.error(f"Ошибка в process_edited_digest: {e}")
        await message.answer("❌ Произошла ошибка при сохранении")
        await state.clear()


# Обновим функцию publish_digest_callback
@digest_router.callback_query(F.data.startswith("publish_digest:"))
async def publish_digest_callback(callback: CallbackQuery, state: FSMContext):
    """Обработчик публикации дайджеста с подтверждением"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("🚫 Доступ запрещен", show_alert=True)
        return

    try:
        # Парсим callback_data
        data_parts = callback.data.split(":")
        if len(data_parts) != 2:
            await callback.answer("❌ Ошибка формата", show_alert=True)
            return

        _, digest_hash = data_parts

        # Получаем дайджест из базы
        digest = await get_digest_by_hash(digest_hash)
        if not digest:
            await callback.answer("❌ Дайджест не найден в базе данных", show_alert=True)
            return

        # Используем отредактированный текст, если он есть, иначе сгенерированный
        text = digest.edit_text if digest.edit_text else digest.text

        # Сохраняем данные в состоянии для подтверждения
        await state.update_data(
            digest_hash=digest_hash,
            digest_text=text,
            chat_id=callback.from_user.id,
            message_id=callback.message.message_id
        )

        # Определяем текущий режим парсинга из кнопки
        current_parse_mode = None
        if callback.message.reply_markup:
            for row in callback.message.reply_markup.inline_keyboard:
                for button in row:
                    if button.text and "Разметка" in button.text:
                        if "✅" in button.text:
                            current_parse_mode = "HTML"
                        elif "❌" in button.text:
                            current_parse_mode = None
                        break

        # Отправляем дайджест для предварительного просмотра
        await bot.send_message(
            chat_id=callback.from_user.id,
            text=text,
            parse_mode=current_parse_mode
        )

        # Отправляем сообщение с подтверждением
        confirm_keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Да",
                        callback_data=f"confirm_digest_publish:{digest_hash}"
                    ),
                    InlineKeyboardButton(
                        text="❌ Нет",
                        callback_data="cancel_digest_publish"
                    )
                ]
            ]
        )

        await callback.message.answer(
            "📋 <b>Внимательно просмотрите как дайджест будет выглядеть в канале (отправлен выше).</b>\n\n"
            "📢 <b>Опубликовать дайджест?</b>",
            reply_markup=confirm_keyboard
        )

        await callback.answer()

    except Exception as e:
        logger.error(f"Ошибка в publish_digest_callback: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


# Обновим функцию confirm_digest_publish_callback
@digest_router.callback_query(F.data.startswith("confirm_digest_publish:"))
async def confirm_digest_publish_callback(callback: CallbackQuery, state: FSMContext):
    """Подтверждение публикации дайджеста"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("🚫 Доступ запрещен", show_alert=True)
        return

    try:
        # Парсим callback_data
        data_parts = callback.data.split(":")
        if len(data_parts) != 2:
            await callback.answer("❌ Ошибка формата", show_alert=True)
            return

        _, digest_hash = data_parts

        # Получаем дайджест из базы
        digest = await get_digest_by_hash(digest_hash)
        if not digest:
            await callback.answer("❌ Дайджест не найден в базе данных", show_alert=True)
            return

        # Используем отредактированный текст, если он есть, иначе сгенерированный
        text = digest.edit_text if digest.edit_text else digest.text

        try:
            # Публикуем дайджест в канал
            await bot.send_message(
                chat_id=CHANEL_ID,
                text=text,
                parse_mode="HTML"
            )

            # Отмечаем дайджест как опубликованный
            await mark_digest_published(digest_hash)

            await callback.answer("✅ Дайджест успешно опубликован!", show_alert=True)
            await callback.message.answer("📢 Дайджест успешно опубликован в канале!")

            logger.info(f"Дайджест опубликован в канале {CHANEL_ID} администратором {callback.from_user.id}")

        except Exception as e:
            logger.error(f"Ошибка при публикации дайджеста в канал: {e}")
            await callback.answer(f"❌ Ошибка при публикации: {str(e)[:100]}", show_alert=True)
        else:
            await callback.answer("❌ Не найдено оригинальное сообщение", show_alert=True)

        await state.clear()

    except Exception as e:
        logger.error(f"Ошибка в confirm_digest_publish_callback: {e}")
        await callback.answer("❌ Произошла ошибка")
        await state.clear()


@digest_router.callback_query(F.data == "cancel_digest_publish")
async def cancel_digest_publish_callback(callback: CallbackQuery, state: FSMContext):
    """Отмена публикации дайджеста"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("🚫 Доступ запрещен", show_alert=True)
        return

    await callback.answer("❌ Отправка дайджеста отменена", show_alert=False)
    await callback.message.answer("❌ Публикация дайджеста отменена")
    await state.clear()