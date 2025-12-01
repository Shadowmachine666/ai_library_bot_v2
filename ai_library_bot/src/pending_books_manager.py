"""Управление непроиндексированными книгами.

Модуль предоставляет функции для хранения и управления списком книг,
которые были обнаружены в папке, но еще не проиндексированы.
"""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from src.utils import setup_logger

logger = setup_logger(__name__)

# Путь к файлу с непроиндексированными книгами
PENDING_BOOKS_FILE = Path("./data/pending_books.json")


def _load_pending_books() -> dict[str, dict[str, Any]]:
    """Загружает список непроиндексированных книг из файла.
    
    Returns:
        Словарь с информацией о непроиндексированных книгах.
        Ключ: путь к файлу (str), значение: информация о книге (dict).
    """
    if not PENDING_BOOKS_FILE.exists():
        logger.debug(f"Файл {PENDING_BOOKS_FILE} не существует, возвращаем пустой словарь")
        return {}
    
    try:
        with open(PENDING_BOOKS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            logger.debug(f"Загружено {len(data)} непроиндексированных книг из {PENDING_BOOKS_FILE}")
            return data
    except Exception as e:
        logger.error(f"Ошибка при загрузке непроиндексированных книг из {PENDING_BOOKS_FILE}: {e}", exc_info=True)
        return {}


def _save_pending_books(pending_books: dict[str, dict[str, Any]]) -> None:
    """Сохраняет список непроиндексированных книг в файл.
    
    Args:
        pending_books: Словарь с информацией о непроиндексированных книгах.
    """
    try:
        # Создаем директорию, если её нет
        PENDING_BOOKS_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        with open(PENDING_BOOKS_FILE, "w", encoding="utf-8") as f:
            json.dump(pending_books, f, ensure_ascii=False, indent=2)
        logger.debug(f"Сохранено {len(pending_books)} непроиндексированных книг в {PENDING_BOOKS_FILE}")
    except Exception as e:
        logger.error(f"Ошибка при сохранении непроиндексированных книг в {PENDING_BOOKS_FILE}: {e}", exc_info=True)
        raise


def get_pending_books() -> list[dict[str, Any]]:
    """Получает список непроиндексированных книг.
    
    Returns:
        Список словарей с информацией о непроиндексированных книгах.
        Каждый словарь содержит: file_path, added_at, notification_sent, message_id, file_size.
    """
    pending_books = _load_pending_books()
    
    # Преобразуем в список и валидируем существование файлов
    result = []
    to_remove = []
    
    for file_path_str, book_info in pending_books.items():
        file_path = Path(file_path_str)
        
        # Проверяем, существует ли файл
        if not file_path.exists():
            logger.debug(f"Файл {file_path_str} не существует, удаляем из списка ожидания")
            to_remove.append(file_path_str)
            continue
        
        result.append({
            "file_path": file_path_str,
            "file_name": file_path.name,
            "added_at": book_info.get("added_at", ""),
            "notification_sent": book_info.get("notification_sent", False),
            "message_id": book_info.get("message_id"),
            "file_size": book_info.get("file_size", 0),
        })
    
    # Удаляем несуществующие файлы
    if to_remove:
        for file_path_str in to_remove:
            del pending_books[file_path_str]
        _save_pending_books(pending_books)
        logger.info(f"Удалено {len(to_remove)} несуществующих файлов из списка ожидания")
    
    return result


def add_pending_book(file_path: Path) -> bool:
    """Добавляет книгу в список непроиндексированных.
    
    Args:
        file_path: Путь к файлу книги.
    
    Returns:
        True если книга была добавлена, False если уже существует.
    """
    file_path_str = str(file_path.absolute())
    
    if not file_path.exists():
        logger.warning(f"Попытка добавить несуществующий файл в список ожидания: {file_path_str}")
        return False
    
    pending_books = _load_pending_books()
    
    # Проверяем, не добавлена ли уже книга
    if file_path_str in pending_books:
        logger.debug(f"Книга {file_path.name} уже в списке ожидания")
        return False
    
    # Добавляем книгу
    file_size = file_path.stat().st_size
    pending_books[file_path_str] = {
        "added_at": datetime.now().isoformat(),
        "notification_sent": False,
        "message_id": None,
        "file_size": file_size,
    }
    
    _save_pending_books(pending_books)
    logger.info(f"Добавлена книга в список ожидания: {file_path.name} ({file_size / 1024 / 1024:.2f} MB)")
    return True


def remove_pending_book(file_path: Path | str) -> bool:
    """Удаляет книгу из списка непроиндексированных.
    
    Args:
        file_path: Путь к файлу книги (Path или str).
    
    Returns:
        True если книга была удалена, False если не найдена.
    """
    file_path_str = str(Path(file_path).absolute()) if isinstance(file_path, Path) else file_path
    
    pending_books = _load_pending_books()
    
    if file_path_str not in pending_books:
        logger.debug(f"Книга {file_path_str} не найдена в списке ожидания")
        return False
    
    book_name = Path(file_path_str).name
    del pending_books[file_path_str]
    _save_pending_books(pending_books)
    logger.info(f"Удалена книга из списка ожидания: {book_name}")
    return True


def mark_notification_sent(file_path: Path | str, message_id: int) -> bool:
    """Отмечает, что уведомление о книге было отправлено.
    
    Args:
        file_path: Путь к файлу книги (Path или str).
        message_id: ID сообщения Telegram с уведомлением.
    
    Returns:
        True если обновление прошло успешно, False если книга не найдена.
    """
    file_path_str = str(Path(file_path).absolute()) if isinstance(file_path, Path) else file_path
    
    pending_books = _load_pending_books()
    
    if file_path_str not in pending_books:
        logger.warning(f"Попытка отметить уведомление для несуществующей книги: {file_path_str}")
        return False
    
    pending_books[file_path_str]["notification_sent"] = True
    pending_books[file_path_str]["message_id"] = message_id
    
    _save_pending_books(pending_books)
    logger.debug(f"Отмечено, что уведомление отправлено для книги {Path(file_path_str).name}, message_id={message_id}")
    return True


def is_notification_sent(file_path: Path | str) -> bool:
    """Проверяет, было ли отправлено уведомление о книге.
    
    Args:
        file_path: Путь к файлу книги (Path или str).
    
    Returns:
        True если уведомление было отправлено, False в противном случае.
    """
    file_path_str = str(Path(file_path).absolute()) if isinstance(file_path, Path) else file_path
    
    pending_books = _load_pending_books()
    book_info = pending_books.get(file_path_str)
    
    if book_info is None:
        return False
    
    return book_info.get("notification_sent", False)


def clear_all_pending_books() -> int:
    """Очищает весь список непроиндексированных книг.
    
    Returns:
        Количество удаленных книг.
    """
    pending_books = _load_pending_books()
    count = len(pending_books)
    
    if count > 0:
        _save_pending_books({})
        logger.info(f"Очищено {count} книг из списка ожидания")
    
    return count


def remove_missing_files() -> int:
    """Удаляет из списка ожидания файлы, которые больше не существуют.
    
    Returns:
        Количество удаленных записей.
    """
    pending_books = _load_pending_books()
    to_remove = []
    
    for file_path_str in pending_books.keys():
        file_path = Path(file_path_str)
        if not file_path.exists():
            to_remove.append(file_path_str)
    
    for file_path_str in to_remove:
        del pending_books[file_path_str]
    
    if to_remove:
        _save_pending_books(pending_books)
        logger.info(f"Удалено {len(to_remove)} несуществующих файлов из списка ожидания")
    
    return len(to_remove)



