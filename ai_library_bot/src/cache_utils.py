"""Утилиты для работы с кэшем ответов LLM."""

from aiocache import Cache

from src.utils import setup_logger

logger = setup_logger(__name__)

# Инициализация кэша (такой же, как в telegram_bot.py)
cache = Cache(Cache.MEMORY)


async def clear_cache() -> None:
    """Очищает весь кэш ответов LLM.
    
    Используется при удалении книг из индекса, чтобы гарантировать,
    что пользователи не получат устаревшие ответы, основанные на удаленных книгах.
    """
    try:
        await cache.clear()
        logger.info("[CACHE] ✅ Кэш ответов LLM полностью очищен")
    except Exception as e:
        error_type = type(e).__name__
        logger.warning(
            f"[CACHE] ⚠️ Ошибка при очистке кэша: "
            f"тип={error_type}, сообщение={str(e)}"
        )

