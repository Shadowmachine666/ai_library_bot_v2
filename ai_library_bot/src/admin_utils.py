"""Утилиты для работы с администратором бота.

Модуль предоставляет функции для проверки прав администратора
и работы с административными функциями.
"""

from src.config import Config
from src.utils import setup_logger

logger = setup_logger(__name__)


def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь администратором.

    Сравнивает user_id с ADMIN_TELEGRAM_ID из конфигурации.

    Args:
        user_id: Telegram User ID пользователя.

    Returns:
        True если пользователь является администратором, False в противном случае.
    """
    admin_id = get_admin_id()
    
    if admin_id is None:
        logger.warning(
            f"ADMIN_TELEGRAM_ID не установлен в конфигурации. "
            f"Пользователь {user_id} не может быть администратором."
        )
        return False
    
    is_admin_user = user_id == admin_id
    
    if is_admin_user:
        logger.debug(f"Пользователь {user_id} подтверждён как администратор")
    else:
        logger.debug(f"Пользователь {user_id} не является администратором (ожидается {admin_id})")
    
    return is_admin_user


def get_admin_id() -> int | None:
    """Получает ID администратора из конфигурации.

    Returns:
        Telegram User ID администратора или None, если не установлен.
    """
    return Config.ADMIN_TELEGRAM_ID


def require_admin(user_id: int) -> None:
    """Проверяет права администратора и выбрасывает исключение, если пользователь не администратор.

    Используется для защиты функций, доступных только администратору.

    Args:
        user_id: Telegram User ID пользователя.

    Raises:
        PermissionError: Если пользователь не является администратором.
    """
    if not is_admin(user_id):
        admin_id = get_admin_id()
        error_msg = (
            f"Доступ запрещён. Пользователь {user_id} не является администратором. "
            f"Ожидается администратор с ID: {admin_id if admin_id else 'не установлен'}."
        )
        logger.warning(error_msg)
        raise PermissionError(error_msg)



