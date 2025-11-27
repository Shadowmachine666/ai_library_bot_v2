"""Хранение контекста запросов пользователей.

Модуль предоставляет функции для временного хранения контекста запросов,
чтобы пользователь мог изменить категории и повторить поиск.
"""

import hashlib
import time
from typing import Any

from src.utils import setup_logger

logger = setup_logger(__name__)

# Хранилище контекста запросов
# Ключ: query_hash (str), значение: dict с контекстом запроса
_query_contexts: dict[str, dict[str, Any]] = {}

# TTL для контекста запросов (1 час в секундах)
QUERY_CONTEXT_TTL = 3600


def _generate_query_hash(user_id: int, query_text: str) -> str:
    """Генерирует хеш для запроса пользователя.
    
    Args:
        user_id: ID пользователя Telegram.
        query_text: Текст запроса.
    
    Returns:
        Короткий хеш запроса (первые 16 символов SHA256).
    """
    combined = f"{user_id}:{query_text}"
    hash_obj = hashlib.sha256(combined.encode("utf-8"))
    return hash_obj.hexdigest()[:16]


def save_query_context(
    user_id: int,
    query_text: str,
    used_categories: list[str] | None,
    selected_categories: list[str] | None = None,
) -> str:
    """Сохраняет контекст запроса пользователя.
    
    Args:
        user_id: ID пользователя Telegram.
        query_text: Текст запроса.
        used_categories: Категории, использованные для поиска (None = все категории).
        selected_categories: Выбранные пользователем категории для множественного выбора (None = не выбраны).
    
    Returns:
        Хеш запроса для использования в callback'ах.
    """
    query_hash = _generate_query_hash(user_id, query_text)
    
    _query_contexts[query_hash] = {
        "user_id": user_id,
        "query_text": query_text,
        "used_categories": used_categories,
        "selected_categories": selected_categories if selected_categories is not None else [],
        "timestamp": time.time(),
    }
    
    logger.debug(
        f"Сохранен контекст запроса: hash={query_hash}, "
        f"user_id={user_id}, categories={used_categories}, selected={selected_categories}"
    )
    
    return query_hash


def get_query_context(query_hash: str) -> dict[str, Any] | None:
    """Получает контекст запроса по хешу.
    
    Args:
        query_hash: Хеш запроса.
    
    Returns:
        Словарь с контекстом запроса или None, если не найден или истек TTL.
    """
    context = _query_contexts.get(query_hash)
    
    if context is None:
        logger.debug(f"Контекст запроса не найден: hash={query_hash}")
        return None
    
    # Проверяем TTL
    elapsed = time.time() - context["timestamp"]
    if elapsed > QUERY_CONTEXT_TTL:
        logger.debug(
            f"Контекст запроса истек: hash={query_hash}, "
            f"elapsed={elapsed:.1f}s, TTL={QUERY_CONTEXT_TTL}s"
        )
        del _query_contexts[query_hash]
        return None
    
    # Обратная совместимость: если selected_categories отсутствует, инициализируем пустым списком
    if "selected_categories" not in context:
        context["selected_categories"] = []
        logger.debug(f"Инициализированы selected_categories для старого контекста: hash={query_hash}")
    
    logger.debug(f"Загружен контекст запроса: hash={query_hash}")
    return context


def update_query_selected_categories(query_hash: str, selected_categories: list[str]) -> bool:
    """Обновляет выбранные категории в контексте запроса.
    
    Args:
        query_hash: Хеш запроса.
        selected_categories: Список выбранных категорий.
    
    Returns:
        True если контекст был обновлен, False если не найден.
    """
    if query_hash not in _query_contexts:
        logger.warning(f"Попытка обновить несуществующий контекст запроса: hash={query_hash}")
        return False
    
    _query_contexts[query_hash]["selected_categories"] = selected_categories
    logger.debug(
        f"Обновлены выбранные категории для запроса {query_hash}: {selected_categories}"
    )
    return True


def delete_query_context(query_hash: str) -> bool:
    """Удаляет контекст запроса.
    
    Args:
        query_hash: Хеш запроса.
    
    Returns:
        True если контекст был удален, False если не найден.
    """
    if query_hash in _query_contexts:
        del _query_contexts[query_hash]
        logger.debug(f"Удален контекст запроса: hash={query_hash}")
        return True
    return False


def cleanup_expired_contexts() -> int:
    """Очищает истекшие контексты запросов.
    
    Returns:
        Количество удаленных контекстов.
    """
    current_time = time.time()
    expired_hashes = [
        hash_val
        for hash_val, context in _query_contexts.items()
        if current_time - context["timestamp"] > QUERY_CONTEXT_TTL
    ]
    
    for hash_val in expired_hashes:
        del _query_contexts[hash_val]
    
    if expired_hashes:
        logger.debug(f"Очищено {len(expired_hashes)} истекших контекстов запросов")
    
    return len(expired_hashes)

