"""Утилиты для ai_library_bot.

Содержит фабрику логгера и helper для выполнения синхронных функций в executor.
"""

import asyncio
import logging
import sys
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Any, TypeVar

from src.config import Config

# Тип для функций
F = TypeVar("F", bound=Callable[..., Any])


def setup_logger(name: str, log_file: Path | None = None) -> logging.Logger:
    """Создаёт и настраивает логгер.

    Args:
        name: Имя логгера (обычно __name__ модуля).
        log_file: Опциональный путь к файлу для записи логов.

    Returns:
        Настроенный логгер.
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, Config.LOG_LEVEL, logging.INFO))

    # Если логгер уже настроен, не добавляем обработчики повторно
    if logger.handlers:
        return logger

    # Формат логов
    formatter = logging.Formatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Консольный обработчик
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Файловый обработчик (если указан путь)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def run_in_executor(func: F) -> F:
    """Декоратор для выполнения синхронной функции в executor.

    Используется для обёртки синхронных операций (например, чтение файлов,
    работа с FAISS), которые нужно выполнять в отдельном потоке, чтобы
    не блокировать event loop.

    Args:
        func: Синхронная функция для обёртки.

    Returns:
        Асинхронная функция-обёртка.

    Example:
        @run_in_executor
        def read_file_sync(path: str) -> str:
            with open(path, 'r') as f:
                return f.read()

        # Теперь можно вызывать асинхронно:
        content = await read_file_sync("file.txt")
    """

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        """Асинхронная обёртка для синхронной функции."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

    return wrapper  # type: ignore


async def run_in_executor_direct(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Прямой вызов синхронной функции в executor.

    Альтернатива декоратору @run_in_executor для случаев,
    когда нужно вызвать функцию напрямую без декоратора.

    Args:
        func: Синхронная функция для выполнения.
        *args: Позиционные аргументы для функции.
        **kwargs: Именованные аргументы для функции.

    Returns:
        Результат выполнения функции.

    Example:
        result = await run_in_executor_direct(sync_function, arg1, arg2, key=value)
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))
