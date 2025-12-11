from datetime import datetime
from sqlalchemy import select

from db.models import Session, Post


async def save_post(
        chat_id: int,
        chat_title: str,
        chat_type: str,
        message_id: int,
        content_type: str,
        text: str = None,
        file_id: str = None,
        original_date: datetime = None
) -> Post:
    """
    Сохраняет пост в базу данных
    """
    async with Session() as session:
        # Проверяем, нет ли уже такого поста
        stmt = select(Post).where(
            Post.chat_id == chat_id,
            Post.message_id == message_id
        )
        result = await session.execute(stmt)
        existing_post = result.scalar_one_or_none()

        if existing_post:
            # Обновляем существующий пост
            existing_post.text = text
            existing_post.file_id = file_id
            existing_post.received_at = datetime.now()
            post = existing_post
        else:
            # Создаем новый пост
            post = Post(
                chat_id=chat_id,
                chat_title=chat_title,
                chat_type=chat_type,
                message_id=message_id,
                content_type=content_type,
                text=text,  # Сохраняем HTML разметку
                file_id=file_id,
                original_date=original_date or datetime.now()
            )
            session.add(post)

        await session.commit()
        await session.refresh(post)
        return post


async def get_posts(
        chat_id: int = None,
        content_type: str = None,
        has_digest: bool = None,
        limit: int = 100,
        offset: int = 0
) -> list[Post]:
    """
    Получает посты из базы данных с фильтрацией
    """
    async with Session() as session:
        stmt = select(Post)

        if chat_id:
            stmt = stmt.where(Post.chat_id == chat_id)

        if content_type:
            stmt = stmt.where(Post.content_type == content_type)

        if has_digest is not None:
            stmt = stmt.where(Post.digest == has_digest)

        stmt = stmt.order_by(Post.original_date.desc())
        stmt = stmt.offset(offset).limit(limit)

        result = await session.execute(stmt)
        return result.scalars().all()


async def update_post_digest(post_id: int, digest: bool) -> bool:
    """
    Обновляет статус дайджеста для поста
    """
    async with Session() as session:
        stmt = select(Post).where(Post.id == post_id)
        result = await session.execute(stmt)
        post = result.scalar_one_or_none()

        if post:
            post.digest = digest
            post.processed_at = datetime.now() if digest else None
            await session.commit()
            return True

        return False


async def get_post_by_id(post_id: int) -> Post:
    """
    Получает пост по ID
    """
    async with Session() as session:
        stmt = select(Post).where(Post.id == post_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


async def update_post_ai_gen(post_id: int, ai_text: str) -> bool:
    """
    Обновляет AI сгенерированный текст для поста
    """
    async with Session() as session:
        stmt = select(Post).where(Post.id == post_id)
        result = await session.execute(stmt)
        post = result.scalar_one_or_none()

        if post:
            post.ai_gen = ai_text
            await session.commit()
            return True

        return False
