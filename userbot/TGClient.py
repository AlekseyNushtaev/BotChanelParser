import asyncio
from pprint import pprint

from telethon import TelegramClient, events
from telethon.events.newmessage import NewMessage
from telethon.types import Channel, Chat
from telethon.tl.types import (
    MessageEntityBold, MessageEntityItalic, MessageEntityCode, MessageEntityPre,
    MessageEntityTextUrl, MessageEntityUrl, MessageEntityMention,
    MessageEntityHashtag, MessageEntityStrike, MessageEntityBlockquote
)
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
import tempfile
import os
import html
from typing import List, Tuple, Optional
from html import escape
from bs4 import BeautifulSoup

from logger import logger
from config import ADMIN_IDS
from bot import bot
from db.posts import save_post

_client = None


def _create_post_keyboard(post_id: int, parse_mode: str = "HTML") -> InlineKeyboardMarkup:
    """Создать клавиатуру для поста с 5 кнопками"""
    # Определяем эмодзи для кнопки разметки
    markup_emoji = "✅" if parse_mode == "HTML" else "❌"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{markup_emoji} Разметка",
                    callback_data=f"toggle_parse_original:{post_id}"
                ),
                InlineKeyboardButton(
                    text="🤖 Генерация АИ",
                    callback_data=f"ai_generate:{post_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Редактировать",
                    callback_data=f"edit_post_original:{post_id}"
                ),
                InlineKeyboardButton(
                    text="📢 Опубликовать",
                    callback_data=f"publish_original:{post_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📁 Добавить в дайджест",
                    callback_data=f"add_digest:{post_id}"
                ),
                InlineKeyboardButton(
                    text="📋 Cформировать дайджест",
                    callback_data=f"do_digest"
                )
            ]
        ]
    )
    return keyboard


def create_client(api_id: int, api_hash: str, phone: str = None):
    """Создать клиент Telethon с указанными учетными данными"""
    global _client

    _client = TelegramClient(
        session='anon',
        api_id=api_id,
        api_hash=api_hash,
        device_model='MyApp',
        system_version='1.0',
        app_version='1.0',
        lang_code='en',
        system_lang_code='en'
    )
    # Регистрируем обработчик для всех входящих сообщений
    _client.on(events.NewMessage(incoming=True))(channel_event)

    return _client


def client():
    """Получить текущий клиент Telethon"""
    global _client
    return _client


def _utf16_len(text: str) -> int:
    """Возвращает длину строки в UTF-16 кодовых единицах"""
    return len(text.encode('utf-16-le')) // 2


def _utf16_offset_to_unicode(text: str, utf16_offset: int) -> int:
    """
    Преобразует UTF-16 offset в позицию в Unicode строке Python
    """
    if utf16_offset == 0:
        return 0

    utf16_bytes = text.encode('utf-16-le')

    # Если offset выходит за пределы
    if utf16_offset * 2 > len(utf16_bytes):
        return len(text)

    # Декодируем байты до указанного offset
    decoded = utf16_bytes[:utf16_offset * 2].decode('utf-16-le')
    return len(decoded)


def _apply_entities_to_html(text: str, entities) -> str:
    """
    Применяет HTML разметку к тексту на основе entities от Telegram
    с корректной обработкой вложенных сущностей
    """
    if not text:
        return ""

    # Если нет сущностей, просто экранируем текст
    if not entities:
        return escape(text)

    # Создаем список для хранения тегов
    tags: List[Tuple[int, str, Optional[dict]]] = []

    # Преобразуем сущности в теги
    for entity in entities:
        start = _utf16_offset_to_unicode(text, entity.offset)
        end = _utf16_offset_to_unicode(text, entity.offset + entity.length)

        # Проверяем корректность позиций
        if start >= len(text) or end > len(text) or start < 0 or end <= start:
            continue

        entity_text = text[start:end]

        # Определяем HTML тег в зависимости от типа сущности
        if isinstance(entity, MessageEntityBold):
            tags.append((start, 'open', {'tag': 'b'}))
            tags.append((end, 'close', {'tag': 'b'}))
        elif isinstance(entity, MessageEntityItalic):
            tags.append((start, 'open', {'tag': 'i'}))
            tags.append((end, 'close', {'tag': 'i'}))
        elif isinstance(entity, MessageEntityCode):
            tags.append((start, 'open', {'tag': 'code'}))
            tags.append((end, 'close', {'tag': 'code'}))
        elif isinstance(entity, MessageEntityPre):
            language = getattr(entity, 'language', '')
            if language:
                tags.append((start, 'open', {'tag': 'pre', 'attrs': f' language="{escape(language)}"'}))
            else:
                tags.append((start, 'open', {'tag': 'pre'}))
            tags.append((end, 'close', {'tag': 'pre'}))
        elif isinstance(entity, MessageEntityTextUrl):
            url = entity.url
            if url:
                url_escaped = escape(url)
                tags.append((start, 'open', {'tag': 'a', 'attrs': f' href="{url_escaped}"'}))
                tags.append((end, 'close', {'tag': 'a'}))
        elif isinstance(entity, MessageEntityUrl):
            url_escaped = escape(entity_text)
            tags.append((start, 'open', {'tag': 'a', 'attrs': f' href="{url_escaped}"'}))
            tags.append((end, 'close', {'tag': 'a'}))
        elif isinstance(entity, MessageEntityMention):
            if entity_text.startswith('@'):
                username = entity_text[1:] if len(entity_text) > 1 else ''
                if username:
                    tags.append((start, 'open', {'tag': 'a', 'attrs': f' href="https://t.me/{username}"'}))
                    tags.append((end, 'close', {'tag': 'a'}))
        elif isinstance(entity, MessageEntityStrike):
            tags.append((start, 'open', {'tag': 's'}))
            tags.append((end, 'close', {'tag': 's'}))
        elif isinstance(entity, MessageEntityBlockquote):
            tags.append((start, 'open', {'tag': 'blockquote'}))
            tags.append((end, 'close', {'tag': 'blockquote'}))

    # Сортируем теги по позиции, закрывающие теги перед открывающими на той же позиции
    tags.sort(key=lambda x: (x[0], 0 if x[1] == 'close' else 1))

    # Собираем результат с тегами
    result_parts = []
    last_pos = 0

    for pos, tag_type, tag_info in tags:
        # Добавляем текст между тегами
        if pos > last_pos:
            result_parts.append(escape(text[last_pos:pos]))

        # Добавляем тег
        if tag_type == 'open':
            attrs = tag_info.get('attrs', '')
            result_parts.append(f'<{tag_info["tag"]}{attrs}>')
        else:  # 'close'
            result_parts.append(f'</{tag_info["tag"]}>')

        last_pos = pos

    # Добавляем оставшийся текст после последнего тега
    if last_pos < len(text):
        result_parts.append(escape(text[last_pos:]))

    # Преобразуем в строку
    html_with_tags = ''.join(result_parts)

    # Используем BeautifulSoup для исправления порядка закрывающих тегов
    try:
        soup = BeautifulSoup(html_with_tags, 'html.parser')
        # Получаем отформатированный HTML
        fixed_html = str(soup)

        # Убираем лишние теги, которые добавляет BeautifulSoup (html, body)
        if fixed_html.startswith('<html><body>') and fixed_html.endswith('</body></html>'):
            fixed_html = fixed_html[12:-14]
        elif fixed_html.startswith('<body>') and fixed_html.endswith('</body>'):
            fixed_html = fixed_html[6:-7]

        return fixed_html
    except Exception as e:
        logger.error(f"Ошибка при исправлении HTML с помощью BeautifulSoup: {e}")
        # В случае ошибки возвращаем исходный вариант
        return html_with_tags


def _get_html_tag(entity_info, entity_text):
    """Возвращает HTML теги для сущности"""
    entity = entity_info['entity']
    entity_type = entity_info['type']

    if isinstance(entity, MessageEntityBold):
        return {'open': '<b>', 'close': '</b>'}
    elif isinstance(entity, MessageEntityItalic):
        return {'open': '<i>', 'close': '</i>'}
    elif isinstance(entity, MessageEntityCode):
        return {'open': '<code>', 'close': '</code>'}
    elif isinstance(entity, MessageEntityPre):
        language = getattr(entity, 'language', '')
        if language:
            return {'open': f'<pre language="{html.escape(language)}">', 'close': '</pre>'}
        else:
            return {'open': '<pre>', 'close': '</pre>'}
    elif isinstance(entity, MessageEntityTextUrl):
        url = entity.url
        if url:
            url_escaped = html.escape(url)
            text_escaped = html.escape(entity_text)
            return {'open': f'<a href="{url_escaped}">', 'close': '</a>'}
    elif isinstance(entity, MessageEntityUrl):
        url_escaped = html.escape(entity_text)
        text_escaped = html.escape(entity_text)
        return {'open': f'<a href="{url_escaped}">', 'close': '</a>'}
    elif isinstance(entity, MessageEntityMention):
        if entity_text.startswith('@'):
            username = entity_text[1:] if len(entity_text) > 1 else ''
            if username:
                return {'open': f'<a href="https://t.me/{username}">', 'close': '</a>'}
    elif isinstance(entity, MessageEntityHashtag):
        # Хэштеги не оборачиваем в ссылки
        return None
    elif isinstance(entity, MessageEntityStrike):
        return {'open': '<s>', 'close': '</s>'}
    elif isinstance(entity, MessageEntityBlockquote):
        return {'open': '<blockquote>', 'close': '</blockquote>'}

    return None


async def _save_post_to_db(chat, event, content_type, text, file_id=None):
    """Сохраняет пост в базу данных"""
    try:
        # Сохраняем пост в БД
        post = await save_post(
            chat_id=chat.id,
            chat_title=chat.title,
            chat_type='channel' if isinstance(chat, Channel) and chat.broadcast else 'group',
            message_id=event.message.id,
            content_type=content_type,
            text=text,
            file_id=file_id,
            original_date=event.message.date
        )

        logger.info(f"Пост сохранен в БД с ID: {post.id}")
        return post

    except Exception as e:
        logger.error(f"Ошибка при сохранении поста в БД: {e}")
        logger.exception(f"Полная трассировка ошибки: ")
        return None


async def channel_event(event: NewMessage.Event):
    """Обработчик сообщений из каналов и групп"""
    try:
        # Пропускаем исходящие сообщения (которые мы сами отправили)
        if event.out:
            return

        # Получаем информацию о чате
        chat = await event.get_chat()

        # Проверяем, что это канал (broadcast) или супергруппа
        if not isinstance(chat, (Channel, Chat)):
            return

        # Проверяем, что это именно канал (broadcast)
        if isinstance(chat, Channel) and not chat.broadcast:
            return

        # Пропускаем медиагруппы
        grouped_id = getattr(event.message, 'grouped_id', None)
        if grouped_id:
            logger.info(f"Пропускаем медиагруппу (grouped_id: {grouped_id})")
            return

        logger.info(f"Получено сообщение из чата {chat.title} (ID: {chat.id}, тип: {type(chat).__name__})")

        # Формируем текст сообщения с информацией о чате
        if isinstance(chat, Channel) and chat.broadcast:
            chat_type = "📢 Канал"
        else:
            chat_type = "👥 Группа"

        # Экранируем название чата
        chat_title_escaped = html.escape(chat.title)
        text_chanel = f"{chat_type}: <b>{chat_title_escaped}</b>\n\n"

        # Получаем текст сообщения с сохранением форматирования
        message_text = ""
        if event.message.message:
            message_text = event.message.message

            # Применяем HTML разметку на основе entities
            if hasattr(event.message, 'entities') and event.message.entities:
                try:
                    message_text = _apply_entities_to_html(message_text, event.message.entities)
                except Exception as e:
                    logger.error(f"Ошибка при применении HTML разметки: {e}")
                    # В случае ошибки просто экранируем текст
                    message_text = html.escape(message_text)
            else:
                # Если entities нет, просто экранируем HTML
                message_text = html.escape(message_text)

        # Определяем тип контента
        content_type = 'text'
        if event.message.media:
            if event.message.photo:
                content_type = 'photo'
            elif event.message.video:
                content_type = 'video'
            elif event.message.document:
                content_type = 'document'
            elif event.message.audio:
                content_type = 'audio'
            elif event.message.voice:
                content_type = 'voice'

        # Отправляем администраторам и сохраняем в БД
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, text_chanel, parse_mode=ParseMode.HTML)

                telegram_file_id = None

                # Если есть медиа
                if content_type != 'text':
                    logger.info(f'Это медиа пост')

                    # Определяем расширение файла в зависимости от типа медиа
                    suffix = '.jpg'
                    if event.message.video:
                        suffix = '.mp4'
                    elif event.message.document:
                        if hasattr(event.message.document, 'attributes'):
                            for attr in event.message.document.attributes:
                                if hasattr(attr, 'file_name'):
                                    file_name = attr.file_name
                                    suffix = os.path.splitext(file_name)[1] if '.' in file_name else '.bin'
                                    break
                    elif event.message.audio:
                        suffix = '.mp3'
                    elif event.message.voice:
                        suffix = '.ogg'

                    # Создаем временный файл для медиа
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
                        file_path = tmp_file.name

                    try:
                        # Скачиваем медиа
                        await event.message.download_media(file=file_path)

                        # Используем FSInputFile для отправки файла по пути
                        media_file = FSInputFile(file_path)

                        # Сохраняем пост в БД и получаем его ID
                        post = await _save_post_to_db(
                            chat, event, content_type, message_text
                        )

                        # Создаем клавиатуру для поста с post_id
                        keyboard = _create_post_keyboard(post.id) if post else None
                        telegram_file_id = sent_message = None
                        if event.message.photo:
                            try:
                                logger.info(f'Отправляем фото пост админам')
                                sent_message = await bot.send_photo(
                                    chat_id=admin_id,
                                    photo=media_file,
                                    caption=message_text,
                                    parse_mode=ParseMode.HTML,
                                    reply_markup=keyboard
                                )
                            except Exception as photo_error:
                                logger.warning(f"Не удалось отправить фото с HTML-подписью: {photo_error}")
                                sent_message = await bot.send_photo(
                                    chat_id=admin_id,
                                    photo=media_file,
                                    caption=html.escape(message_text),
                                    parse_mode=None,
                                    reply_markup=keyboard
                                )

                            if sent_message and sent_message.photo:
                                telegram_file_id = sent_message.photo[-1].file_id

                        elif event.message.video:
                            logger.info(f'Отправляем видео пост админам')
                            sent_message = await bot.send_video(
                                chat_id=admin_id,
                                video=media_file,
                                caption=message_text,
                                parse_mode=ParseMode.HTML,
                                reply_markup=keyboard
                            )
                            if sent_message and sent_message.video:
                                telegram_file_id = sent_message.video.file_id

                        elif event.message.document:
                            logger.info(f'Отправляем документ пост админам')
                            sent_message = await bot.send_document(
                                chat_id=admin_id,
                                document=media_file,
                                caption=message_text,
                                parse_mode=ParseMode.HTML,
                                reply_markup=keyboard
                            )
                            if sent_message and sent_message.document:
                                telegram_file_id = sent_message.document.file_id

                        elif event.message.audio:
                            logger.info(f'Отправляем фудио пост админам')
                            sent_message = await bot.send_audio(
                                chat_id=admin_id,
                                audio=media_file,
                                caption=message_text,
                                parse_mode=ParseMode.HTML,
                                reply_markup=keyboard
                            )
                            if sent_message and sent_message.audio:
                                telegram_file_id = sent_message.audio.file_id

                        elif event.message.voice:
                            logger.info(f'Отправляем войс пост админам')
                            sent_message = await bot.send_voice(
                                chat_id=admin_id,
                                voice=media_file,
                                caption=message_text,
                                parse_mode=ParseMode.HTML,
                                reply_markup=keyboard
                            )
                            if sent_message and sent_message.voice:
                                telegram_file_id = sent_message.voice.file_id
                        post = await _save_post_to_db(
                            chat, event, content_type, message_text, file_id=telegram_file_id
                        )

                    finally:
                        # Удаляем временный файл
                        if os.path.exists(file_path):
                            os.unlink(file_path)

                else:
                    logger.info(f'Отправляем текст пост админам')
                    # Сохраняем пост в БД и получаем его ID
                    post = await _save_post_to_db(chat, event, content_type, message_text)

                    # Отправляем только текст с клавиатурой
                    keyboard = _create_post_keyboard(post.id) if post else None

                    sent_message = await bot.send_message(
                        chat_id=admin_id,
                        text=message_text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=keyboard
                    )

                await asyncio.sleep(0.3)

            except Exception as e:
                logger.error(f"Ошибка при отправке сообщения администратору {admin_id}: {e}")
                logger.exception(f"Полная трассировка ошибки: ")

    except Exception as e:
        logger.error(f'Ошибка в обработчике каналов: {e}')
        logger.exception(f'Полная трассировка ошибки в обработчике каналов: ')
        if _client and not _client.is_connected():
            logger.info(f'Tg client был отключен. Пытаемся переподключить')
            try:
                await _client.connect()
            except Exception as reconnect_error:
                logger.error(f'Ошибка переподключения: {reconnect_error}')
