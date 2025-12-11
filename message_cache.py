# Хранение состояния сообщений для быстрого доступа
from typing import Dict, Tuple, Optional
import asyncio

# Глобальная блокировка для потокобезопасности
_cache_lock = asyncio.Lock()

# Кэш для хранения состояния парсинга сообщений
# Структура: {(post_id, admin_id): {"parse_mode": "HTML"|None, "message_id": int, "has_media": bool}}
_message_cache: Dict[Tuple[int, int], Dict] = {}

# Кэш для медиагрупп
# Структура: {(post_id, admin_id): {"parse_mode": "HTML"|None, "message_id": int}}
_media_group_cache: Dict[Tuple[int, int], Dict] = {}


async def get_message_state(post_id: int, admin_id: int) -> Optional[Dict]:
    """Получить состояние сообщения из кэша"""
    async with _cache_lock:
        return _message_cache.get((post_id, admin_id))


async def set_message_state(post_id: int, admin_id: int, state: Dict):
    """Установить состояние сообщения в кэш"""
    async with _cache_lock:
        _message_cache[(post_id, admin_id)] = state


async def delete_message_state(post_id: int, admin_id: int):
    """Устать состояние сообщения из кэша"""
    async with _cache_lock:
        key = (post_id, admin_id)
        if key in _message_cache:
            del _message_cache[key]


async def get_media_group_state(post_id: int, admin_id: int) -> Optional[Dict]:
    """Получить состояние медиагруппы из кэша"""
    async with _cache_lock:
        return _media_group_cache.get((post_id, admin_id))


async def set_media_group_state(post_id: int, admin_id: int, message_id: int, parse_mode: str = "HTML"):
    """Установить состояние медиагруппы в кэш"""
    async with _cache_lock:
        _media_group_cache[(post_id, admin_id)] = {
            "parse_mode": parse_mode,
            "message_id": message_id
        }


async def update_media_group_parse_mode(post_id: int, admin_id: int, parse_mode: str):
    """Обновить режим парсинга медиагруппы"""
    async with _cache_lock:
        key = (post_id, admin_id)
        if key in _media_group_cache:
            _media_group_cache[key]["parse_mode"] = parse_mode


async def delete_media_group_state(post_id: int, admin_id: int):
    """Удалить состояние медиагруппы из кэша"""
    async with _cache_lock:
        key = (post_id, admin_id)
        if key in _media_group_cache:
            del _media_group_cache[key]
