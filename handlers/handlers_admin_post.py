from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, KeyboardButton, \
    ReplyKeyboardMarkup, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select

from ai_gen import post_gen
from config import ADMIN_IDS, CHANEL_ID
from db.models import Session, Post
from logger import logger
from db.posts import get_post_by_id, update_post_digest, update_post_ai_gen
from bot import bot
from aiogram.exceptions import TelegramBadRequest
import html

from userbot.TGClient import _create_post_keyboard

post_router = Router()


class PublishStates(StatesGroup):
    """Состояния для публикации постов"""
    waiting_confirmation = State()


class EditPost(StatesGroup):
    """Состояния для редактирования постов"""
    waiting_edit_text = State()


def _create_ai_keyboard(post_id: int, parse_mode: str = "HTML") -> InlineKeyboardMarkup:
    """Создать клавиатуру для AI-генерации"""
    # Определяем эмодзи для кнопки разметки
    markup_emoji = "✅" if parse_mode == "HTML" else "❌"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{markup_emoji} Разметка",
                    callback_data=f"toggle_parse_ai:{post_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🤖 Генерация АИ",
                    callback_data=f"ai_generate:{post_id}"
                ),
                InlineKeyboardButton(
                    text="✏️ Редактировать",
                    callback_data=f"edit_post_ai:{post_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📁 В дайджест",
                    callback_data=f"add_digest:{post_id}"
                ),
                InlineKeyboardButton(
                    text="📢 Опубликовать",
                    callback_data=f"publish_ai:{post_id}"
                )
            ]
        ]
    )
    return keyboard


def _create_edit_keyboard(post_id: int, parse_mode: str = "HTML") -> InlineKeyboardMarkup:
    """Создать клавиатуру для отредактированного поста"""
    markup_emoji = "✅" if parse_mode == "HTML" else "❌"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{markup_emoji} Разметка",
                    callback_data=f"toggle_parse_edit:{post_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Редактировать",
                    callback_data=f"edit_post_new:{post_id}"
                ),
                InlineKeyboardButton(
                    text="📢 Опубликовать",
                    callback_data=f"publish_edit:{post_id}"
                )
            ]
        ]
    )
    return keyboard


@post_router.callback_query(F.data.startswith("ai_generate:"))
async def ai_generate_callback(callback: CallbackQuery):
    """Обработчик генерации AI текста"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("🚫 Доступ запрещен", show_alert=True)
        return

    try:
        # Парсим callback_data
        data_parts = callback.data.split(":")
        if len(data_parts) != 2:
            await callback.answer("❌ Ошибка формата", show_alert=True)
            return

        _, post_id_str = data_parts
        post_id = int(post_id_str)

        # Получаем пост из БД
        post = await get_post_by_id(post_id)
        if not post:
            await callback.answer("❌ Пост не найден в базе данных", show_alert=True)
            return
        if not post.text:
            await callback.answer("❌ Нет текста для генерации", show_alert=True)
            return

        # Немедленно отвечаем на callback query
        await callback.answer('Генерация началась, ждите...')

        # Редактируем сообщение, показывая что идет генерация
        try:
            if post.content_type == 'text':
                await bot.edit_message_text(
                    chat_id=callback.from_user.id,
                    message_id=callback.message.message_id,
                    text="🔄 Генерация текста...",
                    parse_mode=None
                )
            else:
                await bot.edit_message_caption(
                    chat_id=callback.from_user.id,
                    message_id=callback.message.message_id,
                    caption="🔄 Генерация текста...",
                    parse_mode=None
                )
        except Exception as e:
            logger.error(f"Ошибка при редактировании сообщения: {e}")
            # Продолжаем выполнение даже если редактирование не удалось

        # Создаем AI текст (асинхронно)
        ai_text = await post_gen(post.text)

        # Обновляем запись в БД
        success = await update_post_ai_gen(post_id, ai_text)
        if not success:
            # Отправляем сообщение об ошибке, а не используем callback.answer
            await bot.send_message(
                chat_id=callback.from_user.id,
                text="❌ Ошибка сохранения AI текста"
            )
            return

        # Определяем текущий режим разметки из сообщения
        current_parse_mode = "HTML"  # по умолчанию
        if callback.message.reply_markup:
            for row in callback.message.reply_markup.inline_keyboard:
                for button in row:
                    if button.text and "Разметка" in button.text:
                        if "✅" in button.text:
                            current_parse_mode = "HTML"
                        elif "❌" in button.text:
                            current_parse_mode = None
                        break

        try:
            # Редактируем сообщение с AI текстом и новой клавиатурой
            if post.content_type == 'text':
                await bot.edit_message_text(
                    chat_id=callback.from_user.id,
                    message_id=callback.message.message_id,
                    text=ai_text,
                    parse_mode=current_parse_mode,
                    reply_markup=_create_ai_keyboard(post_id, current_parse_mode)
                )
            else:
                await bot.edit_message_caption(
                    chat_id=callback.from_user.id,
                    message_id=callback.message.message_id,
                    caption=ai_text,
                    parse_mode=current_parse_mode,
                    reply_markup=_create_ai_keyboard(post_id, current_parse_mode)
                )

            # Отправляем отдельное сообщение об успешной генерации
            await bot.send_message(
                chat_id=callback.from_user.id,
                text="✅ AI текст сгенерирован!",
                reply_to_message_id=callback.message.message_id
            )

        except TelegramBadRequest as e:
            if "message is not modified" in str(e).lower():
                # Просто игнорируем эту ошибку
                pass
            elif "can't parse entities" in str(e).lower():
                try:
                    # Пробуем отправить без разметки
                    if post.content_type == 'text':
                        await bot.edit_message_text(
                            chat_id=callback.from_user.id,
                            message_id=callback.message.message_id,
                            text=html.escape(ai_text),
                            parse_mode=None,
                            reply_markup=_create_ai_keyboard(post_id)
                        )
                    else:
                        await bot.edit_message_caption(
                            chat_id=callback.from_user.id,
                            message_id=callback.message.message_id,
                            caption=html.escape(ai_text),
                            parse_mode=None,
                            reply_markup=_create_ai_keyboard(post_id)
                        )
                    await bot.send_message(
                        chat_id=callback.from_user.id,
                        text="⚠️ Автоматически отключена HTML разметка из-за ошибки",
                        reply_to_message_id=callback.message.message_id
                    )
                except Exception as fallback_error:
                    await bot.send_message(
                        chat_id=callback.from_user.id,
                        text=f"❌ Ошибка: {str(fallback_error)[:100]}"
                    )
            else:
                await bot.send_message(
                    chat_id=callback.from_user.id,
                    text=f"❌ Ошибка редактирования: {str(e)[:100]}"
                )
                logger.error(f"Ошибка редактирования сообщения: {e}")

    except Exception as e:
        logger.error(f"Ошибка в ai_generate_callback: {e}")
        # Отправляем сообщение об ошибке, а не используем callback.answer
        await bot.send_message(
            chat_id=callback.from_user.id,
            text="❌ Произошла ошибка при генерации текста"
        )


@post_router.callback_query(F.data.startswith("toggle_parse_"))
async def toggle_parse_callback(callback: CallbackQuery):
    """Обработчик переключения разметки для всех типов сообщений"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("🚫 Доступ запрещен", show_alert=True)
        return

    try:
        # Парсим callback_data
        data_parts = callback.data.split(":")
        if len(data_parts) != 2:
            await callback.answer("❌ Ошибка формата", show_alert=True)
            return

        parse_type, post_id_str = data_parts
        post_id = int(post_id_str)
        admin_id = callback.from_user.id

        # Получаем пост из БД
        post = await get_post_by_id(post_id)
        if not post:
            await callback.answer("❌ Пост не найден в базе данных", show_alert=True)
            return

        # Получаем текущее состояние из сообщения (кнопки)
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

        # Определяем какой текст показывать в зависимости от типа
        if parse_type == "toggle_parse_original":
            text = post.text if post.text else ""
            keyboard = _create_post_keyboard(post.id, new_parse_mode)
        elif parse_type == "toggle_parse_ai":
            text = post.ai_gen if post.ai_gen else ""
            keyboard = _create_ai_keyboard(post.id, new_parse_mode)
        else:
            text = post.edit_text if post.edit_text else ""
            keyboard = _create_edit_keyboard(post.id, new_parse_mode)

        try:
            if post.content_type == 'text':
                await bot.edit_message_text(
                    chat_id=admin_id,
                    message_id=callback.message.message_id,
                    text=text,
                    parse_mode=new_parse_mode,
                    reply_markup=keyboard
                )
            else:
                await bot.edit_message_caption(
                    chat_id=admin_id,
                    message_id=callback.message.message_id,
                    caption=text,
                    parse_mode=new_parse_mode,
                    reply_markup=keyboard
                )

            await callback.answer(f"Разметка {'включена' if new_parse_mode == 'HTML' else 'отключена'}!",
                                  show_alert=False)

        except TelegramBadRequest as e:
            if "message is not modified" in str(e).lower():
                await callback.answer("Сообщение не изменено", show_alert=False)
            elif "can't parse entities" in str(e).lower():
                try:
                    # Пробуем отправить без разметки
                    await bot.edit_message_text(
                        chat_id=admin_id,
                        message_id=callback.message.message_id,
                        text=html.escape(text),
                        parse_mode=None,
                        reply_markup=keyboard
                    )
                    await callback.answer("⚠️ Автоматически отключена HTML разметка из-за ошибки", show_alert=True)
                except Exception as fallback_error:
                    await callback.answer(f"❌ Ошибка: {str(fallback_error)[:100]}", show_alert=True)
            else:
                await callback.answer(f"❌ Ошибка редактирования: {str(e)[:100]}", show_alert=True)
                logger.error(f"Ошибка редактирования сообщения: {e}")

    except Exception as e:
        logger.error(f"Ошибка в toggle_parse_callback: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@post_router.callback_query(F.data.startswith("edit_post_"))
async def edit_post_callback(callback: CallbackQuery, state: FSMContext):
    """Обработчик начала редактирования поста"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("🚫 Доступ запрещен", show_alert=True)
        return

    try:
        # Парсим callback_data
        data_parts = callback.data.split(":")
        if len(data_parts) != 2:
            await callback.answer("❌ Ошибка формата", show_alert=True)
            return

        action, post_id_str = data_parts
        post_id = int(post_id_str)
        admin_id = callback.from_user.id

        # Получаем пост из БД
        post = await get_post_by_id(post_id)
        if not post:
            await callback.answer("❌ Пост не найден в базе данных", show_alert=True)
            return

        # Определяем какой текст редактировать
        if action == "edit_post_original":
            text = post.text if post.text else ""
        elif action == "edit_post_ai":
            text = post.ai_gen if post.ai_gen else ""
        elif action == "edit_post_new":
            text = post.edit_text if post.edit_text else ""
        else:
            await callback.answer("❌ Неизвестный тип редактирования", show_alert=True)
            return

        if not text:
            await callback.answer("❌ Текст для редактирования отсутствует", show_alert=True)
            return

        # Сохраняем данные в состоянии
        await state.update_data(
            post_id=post_id,
            original_message_id=callback.message.message_id,
            chat_id=admin_id,
            text_type=action.split("_")[-1]  # original, ai или new
        )

        # Отправляем сообщение с просьбой отредактировать
        await callback.message.answer(
            "Скопируйте сообщение без разметки и отредактируйте его, результат отправьте мне:\n\n"
            f"{text}",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="Отмена")]],
                resize_keyboard=True
            ),
            parse_mode=None
        )

        # Устанавливаем состояние ожидания отредактированного текста
        await state.set_state(EditPost.waiting_edit_text)
        await callback.answer("✏️ Готов к редактированию. Отправьте исправленный текст.", show_alert=False)

    except Exception as e:
        logger.error(f"Ошибка в edit_post_callback: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


# Добавляем обработчик для получения отредактированного текста
@post_router.message(EditPost.waiting_edit_text, F.text)
async def process_edited_text(message: Message, state: FSMContext):
    """Обработчик получения отредактированного текста"""
    if message.from_user.id not in ADMIN_IDS:
        return

    # Проверяем отмену
    if message.text == "Отмена":
        await state.clear()
        await message.answer("Редактирование отменено")
        return

    try:
        # Получаем данные из состояния
        data = await state.get_data()
        post_id = data.get('post_id')
        original_message_id = data.get('original_message_id')
        chat_id = data.get('chat_id')
        text_type = data.get('text_type')

        if not post_id:
            await message.answer("❌ Ошибка: не найден ID поста")
            await state.clear()
            return

        # Получаем пост
        post = await get_post_by_id(post_id)
        if not post:
            await message.answer("❌ Пост не найден в базе данных")
            await state.clear()
            return

        # Обновляем отредактированный текст в БД
        async with Session() as session:
            stmt = select(Post).where(Post.id == post_id)
            result = await session.execute(stmt)
            post_db = result.scalar_one_or_none()

            if post_db:
                post_db.edit_text = message.text
                await session.commit()
        print(post.content_type)
        print(post.file_id)
        # Отправляем отредактированный текст пользователю с новой клавиатурой
        keyboard = _create_edit_keyboard(post_id, 'net')
        if post.content_type == 'text':
            await bot.send_message(
                chat_id=chat_id,
                text=message.text,
                parse_mode=None,  # по умолчанию без разметки
                reply_markup=keyboard
            )
        elif post.content_type == 'photo':
            await bot.send_photo(
                chat_id=chat_id,
                photo=post.file_id,
                caption=message.text,
                parse_mode=None,  # по умолчанию без разметки
                reply_markup=keyboard
            )
        elif post.content_type == 'video':
            await bot.send_video(
                chat_id=chat_id,
                video=post.file_id,
                caption=message.text,
                parse_mode=None,  # по умолчанию без разметки
                reply_markup=keyboard
            )
        elif post.content_type == 'document':
            await bot.send_document(
                chat_id=chat_id,
                document=post.file_id,
                caption=message.text,
                parse_mode=None,  # по умолчанию без разметки
                reply_markup=keyboard
            )
        elif post.content_type == 'audio':
            await bot.send_audio(
                chat_id=chat_id,
                audio=post.file_id,
                caption=message.text,
                parse_mode=None,  # по умолчанию без разметки
                reply_markup=keyboard
            )
        elif post.content_type == 'voice':
            await bot.send_voice(
                chat_id=chat_id,
                voice=post.file_id,
                caption=message.text,
                parse_mode=None,  # по умолчанию без разметки
                reply_markup=keyboard
            )
        await message.answer("✅ Текст успешно отредактирован и сохранен!")
        await state.clear()

    except Exception as e:
        logger.error(f"Ошибка в process_edited_text: {e}")
        await message.answer("❌ Произошла ошибка при сохранении")
        await state.clear()


@post_router.callback_query(F.data.startswith("add_digest:"))
async def add_digest_callback(callback: CallbackQuery):
    """Обработчик добавления поста в дайджест"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("🚫 Доступ запрещен", show_alert=True)
        return

    try:
        data_parts = callback.data.split(":")
        if len(data_parts) != 2:
            await callback.answer("❌ Ошибка формата", show_alert=True)
            return

        _, post_id_str = data_parts
        post_id = int(post_id_str)

        post = await get_post_by_id(post_id)
        if not post:
            await callback.answer("❌ Пост не найден в базе данных", show_alert=True)
            return

        if post.digest:
            await callback.answer("📁 Пост уже в дайджесте! ✅", show_alert=False)
        else:
            success = await update_post_digest(post_id, True)
            if success:
                await callback.answer("✅ Пост добавлен в дайджест! 📁", show_alert=False)
                logger.info(f"Пост ID:{post_id} добавлен в дайджест администратором {callback.from_user.id}")
            else:
                await callback.answer("❌ Ошибка при добавлении в дайджест", show_alert=True)

    except Exception as e:
        logger.error(f"Ошибка в add_digest_callback: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@post_router.callback_query(F.data.startswith("publish_"),
                             ~F.data.startswith("publish_digest:"))
async def publish_callback(callback: CallbackQuery, state: FSMContext):
    """Обработчик публикации поста с подтверждением"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("🚫 Доступ запрещен", show_alert=True)
        return

    try:
        # Парсим callback_data
        data_parts = callback.data.split(":")
        if len(data_parts) != 2:
            await callback.answer("❌ Ошибка формата", show_alert=True)
            return

        publish_type, post_id_str = data_parts
        post_id = int(post_id_str)

        # Определяем тип публикации (original, ai, edit)
        text_type = publish_type.split("_")[1]  # original, ai или edit

        # Получаем пост из БД
        post = await get_post_by_id(post_id)
        if not post:
            await callback.answer("❌ Пост не найден в базе данных", show_alert=True)
            return

        # Определяем текст для публикации
        if text_type == "original":
            text = post.text if post.text else ""
        elif text_type == "ai":
            text = post.ai_gen if post.ai_gen else ""
        elif text_type == "edit":
            text = post.edit_text if post.edit_text else ""
        else:
            await callback.answer("❌ Неизвестный тип публикации", show_alert=True)
            return

        if not text and not post.file_id:
            await callback.answer("❌ Нет текста или медиа для публикации", show_alert=True)
            return

        # Сохраняем данные в состоянии для подтверждения
        await state.update_data(
            post_id=post_id,
            text_type=text_type,
            publish_type=publish_type,
            chat_id=callback.from_user.id,
            message_id=callback.message.message_id
        )

        # Отправляем пост для предварительного просмотра
        await _send_preview_post(callback.from_user.id, post, text)

        # Отправляем сообщение с подтверждением
        confirm_keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Да",
                        callback_data=f"confirm_publish:{post_id}:{text_type}"
                    ),
                    InlineKeyboardButton(
                        text="❌ Нет",
                        callback_data="cancel_publish"
                    )
                ]
            ]
        )

        await callback.message.answer(
            "📋 <b>Внимательно просмотрите как пост будет выглядеть в канале (отправлен выше).</b>\n\n"
            "📢 <b>Опубликовать?</b>",
            reply_markup=confirm_keyboard
        )

        await callback.answer()

    except Exception as e:
        logger.error(f"Ошибка в publish_callback: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


async def _send_preview_post(chat_id: int, post: Post, text: str):
    """Отправить пост для предварительного просмотра"""
    try:
        if post.content_type == 'text':
            await bot.send_message(
                chat_id=chat_id,
                text=text
            )
        elif post.content_type == 'photo':
            await bot.send_photo(
                chat_id=chat_id,
                photo=post.file_id,
                caption=text
            )
        elif post.content_type == 'video':
            await bot.send_video(
                chat_id=chat_id,
                video=post.file_id,
                caption=text
            )
        elif post.content_type == 'document':
            await bot.send_document(
                chat_id=chat_id,
                document=post.file_id,
                caption=text
            )
        elif post.content_type == 'audio':
            await bot.send_audio(
                chat_id=chat_id,
                audio=post.file_id,
                caption=text
            )
        elif post.content_type == 'voice':
            await bot.send_voice(
                chat_id=chat_id,
                voice=post.file_id,
                caption=text
            )
    except Exception as e:
        logger.error(f"Ошибка при отправке предпросмотра: {e}")
        raise


@post_router.callback_query(F.data.startswith("confirm_publish:"))
async def confirm_publish_callback(callback: CallbackQuery, state: FSMContext):
    """Подтверждение публикации поста"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("🚫 Доступ запрещен", show_alert=True)
        return

    try:
        # Парсим callback_data
        data_parts = callback.data.split(":")
        if len(data_parts) != 3:
            await callback.answer("❌ Ошибка формата", show_alert=True)
            return

        _, post_id_str, text_type = data_parts
        post_id = int(post_id_str)

        # Получаем пост из БД
        post = await get_post_by_id(post_id)
        if not post:
            await callback.answer("❌ Пост не найден в базе данных", show_alert=True)
            return

        # Определяем текст для публикации
        if text_type == "original":
            text = post.text if post.text else ""
        elif text_type == "ai":
            text = post.ai_gen if post.ai_gen else ""
        elif text_type == "edit":
            text = post.edit_text if post.edit_text else ""
        else:
            await callback.answer("❌ Неизвестный тип текста", show_alert=True)
            return

        # Публикуем пост в канал
        try:
            if post.content_type == 'text':
                await bot.send_message(
                    chat_id=CHANEL_ID,
                    text=text
                )
            elif post.content_type == 'photo':
                await bot.send_photo(
                    chat_id=CHANEL_ID,
                    photo=post.file_id,
                    caption=text
                )
            elif post.content_type == 'video':
                await bot.send_video(
                    chat_id=CHANEL_ID,
                    video=post.file_id,
                    caption=text
                )
            elif post.content_type == 'document':
                await bot.send_document(
                    chat_id=CHANEL_ID,
                    document=post.file_id,
                    caption=text
                )
            elif post.content_type == 'audio':
                await bot.send_audio(
                    chat_id=CHANEL_ID,
                    audio=post.file_id,
                    caption=text
                )
            elif post.content_type == 'voice':
                await bot.send_voice(
                    chat_id=CHANEL_ID,
                    voice=post.file_id,
                    caption=text
                )

            await callback.answer("✅ Пост успешно опубликован!", show_alert=True)
            await callback.message.answer("📢 Пост успешно опубликован в канале!")

            logger.info(f"Пост ID:{post_id} опубликован в канале {CHANEL_ID} администратором {callback.from_user.id}")

        except Exception as e:
            logger.error(f"Ошибка при публикации в канал: {e}")
            await callback.answer(f"❌ Ошибка при публикации: {str(e)[:100]}", show_alert=True)
            await callback.message.answer("❌ Ошибка при публикации в канал")

        await state.clear()

    except Exception as e:
        logger.error(f"Ошибка в confirm_publish_callback: {e}")
        await callback.answer("❌ Произошла ошибка")
        await state.clear()


@post_router.callback_query(F.data == "cancel_publish")
async def cancel_publish_callback(callback: CallbackQuery, state: FSMContext):
    """Отмена публикации поста"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("🚫 Доступ запрещен", show_alert=True)
        return

    await callback.answer("❌ Отправка отменена", show_alert=False)
    await callback.message.answer("❌ Публикация отменена")
    await state.clear()
