from sqlalchemy import Column, Integer, String, DateTime, Boolean, BigInteger, ForeignKey, Text, JSON
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, relationship
from datetime import datetime

# Настройка асинхронного подключения к SQLite3
DB_URL = "sqlite+aiosqlite:///db/database.db"
engine = create_async_engine(DB_URL)  # Асинхронный движок SQLAlchemy
Session = async_sessionmaker(expire_on_commit=False, bind=engine)  # Фабрика сессий


class Base(DeclarativeBase, AsyncAttrs):
    pass


class Post(Base):
    """Таблица для хранения постов из каналов"""
    __tablename__ = "posts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger, nullable=False)  # ID чата/канала
    chat_title = Column(String(255), nullable=False)  # Название чата
    chat_type = Column(String(50), nullable=False)  # Тип чата: 'channel' или 'group'
    message_id = Column(BigInteger, nullable=False)  # ID сообщения в чате
    grouped_id = Column(BigInteger, nullable=True)  # ID медиагруппы (пока пустое поле, медиагруппы не обрабатываем)

    # Тип контента
    content_type = Column(String(50),
                          nullable=False)  # 'text', 'photo', 'video', 'document', 'audio', 'voice'

    # Текст сообщения
    text = Column(Text, nullable=True)

    # Telegram file_id (если есть)
    file_id = Column(String(255), nullable=True)  # медиа файл

    # Статусы
    digest = Column(Boolean, default=False)  # Включен ли в дайджест
    ai_gen = Column(Text, nullable=True)  # Сгенерированный AI текст
    edit_text = Column(Text, nullable=True)  # Сгенерированный AI текст

    # Временные метки
    original_date = Column(DateTime, nullable=False)  # Оригинальная дата сообщения
    received_at = Column(DateTime, default=datetime.now)  # Когда получено админом
    processed_at = Column(DateTime, nullable=True)  # Когда обработано


class Digest(Base):
    """Таблица для хранения дайджестов"""
    __tablename__ = "digests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    digest_hash = Column(String(32), nullable=False, unique=True, index=True)  # Хэш для идентификации
    text = Column(Text, nullable=False)  # Сгенерированный AI текст
    edit_text = Column(Text, nullable=True)  # Отредактированный текст
    created_at = Column(DateTime, default=datetime.now)  # Дата создания
    published_at = Column(DateTime, nullable=True)  # Дата публикации
    post_ids = Column(JSON, nullable=True)  # JSON массив с ID постов, вошедших в дайджест


async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
