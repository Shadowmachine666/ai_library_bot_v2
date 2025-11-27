"""Управление выбором категорий пользователя.

Модуль предоставляет функции для сохранения и получения выбранных категорий
для каждого пользователя Telegram бота.
"""

from typing import Any

from src.config import Config
from src.utils import setup_logger

logger = setup_logger(__name__)

# Хранилище выбранных категорий пользователей
# Ключ: user_id (int), значение: list[str] (список категорий) или None (все категории)
_user_categories: dict[int, list[str] | None] = {}


def get_user_categories(user_id: int) -> list[str] | None:
    """Получает выбранные категории пользователя.

    Args:
        user_id: ID пользователя Telegram.

    Returns:
        Список выбранных категорий или None, если выбраны все категории.
        Если пользователь не выбирал категории, возвращает None.
    """
    return _user_categories.get(user_id, None)


def set_user_categories(user_id: int, categories: list[str] | None) -> None:
    """Устанавливает выбранные категории для пользователя.

    Args:
        user_id: ID пользователя Telegram.
        categories: Список категорий или None для выбора всех категорий.
    """
    if categories is not None:
        # Валидируем категории
        valid_categories = [cat.lower() for cat in Config.CATEGORIES]
        filtered_categories = [
            cat for cat in categories if cat.lower() in valid_categories
        ]
        
        # Приводим к оригинальному регистру из Config
        config_categories_map = {cat.lower(): cat for cat in Config.CATEGORIES}
        normalized_categories = [
            config_categories_map[cat.lower()] 
            for cat in filtered_categories 
            if cat.lower() in config_categories_map
        ]
        
        # Удаляем дубликаты, сохраняя порядок
        normalized_categories = list(dict.fromkeys(normalized_categories))
        
        if normalized_categories:
            _user_categories[user_id] = normalized_categories
            logger.info(
                f"Установлены категории для пользователя {user_id}: {normalized_categories}"
            )
        else:
            # Если все категории невалидны, выбираем все (None)
            _user_categories[user_id] = None
            logger.warning(
                f"Все категории для пользователя {user_id} были невалидны, "
                f"установлено: все категории (None)"
            )
    else:
        _user_categories[user_id] = None
        logger.info(f"Установлены все категории для пользователя {user_id} (None)")


def clear_user_categories(user_id: int) -> None:
    """Очищает выбранные категории пользователя (возвращает к выбору всех категорий).

    Args:
        user_id: ID пользователя Telegram.
    """
    _user_categories[user_id] = None
    logger.info(f"Очищены категории для пользователя {user_id}")


def has_user_selected_categories(user_id: int) -> bool:
    """Проверяет, выбрал ли пользователь конкретные категории.

    Args:
        user_id: ID пользователя Telegram.

    Returns:
        True, если пользователь выбрал конкретные категории, False если выбраны все.
    """
    categories = _user_categories.get(user_id, None)
    return categories is not None and len(categories) > 0


def get_all_user_categories() -> dict[int, list[str] | None]:
    """Получает все сохраненные категории пользователей (для отладки).

    Returns:
        Словарь с категориями всех пользователей.
    """
    return _user_categories.copy()

