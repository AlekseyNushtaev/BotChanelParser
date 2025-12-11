from datetime import datetime
from sqlalchemy import select
import hashlib
import json

from db.models import Session, Digest


async def save_digest(
        digest_text: str,
        post_ids: list = None,
        edit_text: str = None
) -> Digest:
    """
    Сохраняет дайджест в базу данных
    """
    # Создаем уникальный хэш для идентификации
    digest_hash = hashlib.md5(digest_text.encode()).hexdigest()[:8]

    async with Session() as session:
        # Проверяем, нет ли уже такого дайджеста
        stmt = select(Digest).where(Digest.digest_hash == digest_hash)
        result = await session.execute(stmt)
        existing_digest = result.scalar_one_or_none()

        if existing_digest:
            # Обновляем существующий дайджест
            existing_digest.text = digest_text
            if edit_text:
                existing_digest.edit_text = edit_text
            if post_ids:
                existing_digest.post_ids = json.dumps(post_ids)
            digest = existing_digest
        else:
            # Создаем новый дайджест
            digest = Digest(
                digest_hash=digest_hash,
                text=digest_text,
                edit_text=edit_text,
                post_ids=json.dumps(post_ids) if post_ids else None
            )
            session.add(digest)

        await session.commit()
        await session.refresh(digest)
        return digest


async def get_digest_by_hash(digest_hash: str) -> Digest:
    """
    Получает дайджест по хэшу
    """
    async with Session() as session:
        stmt = select(Digest).where(Digest.digest_hash == digest_hash)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


async def update_digest_edit_text(digest_hash: str, edit_text: str) -> bool:
    """
    Обновляет отредактированный текст дайджеста
    """
    async with Session() as session:
        stmt = select(Digest).where(Digest.digest_hash == digest_hash)
        result = await session.execute(stmt)
        digest = result.scalar_one_or_none()

        if digest:
            digest.edit_text = edit_text
            await session.commit()
            return True

        return False


async def mark_digest_published(digest_hash: str) -> bool:
    """
    Отмечает дайджест как опубликованный
    """
    async with Session() as session:
        stmt = select(Digest).where(Digest.digest_hash == digest_hash)
        result = await session.execute(stmt)
        digest = result.scalar_one_or_none()

        if digest:
            digest.published_at = datetime.now()
            await session.commit()
            return True

        return False


async def get_recent_digests(limit: int = 10) -> list[Digest]:
    """
    Получает последние дайджесты
    """
    async with Session() as session:
        stmt = select(Digest).order_by(Digest.created_at.desc()).limit(limit)
        result = await session.execute(stmt)
        return result.scalars().all()
