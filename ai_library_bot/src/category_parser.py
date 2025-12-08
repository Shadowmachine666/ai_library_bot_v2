"""Парсер категорий из имени файла.

Модуль предоставляет функции для извлечения категорий из имени файла
в формате: "Название книги (категория1, категория2).pdf"
"""

import re
from pathlib import Path

from src.config import Config
from src.utils import setup_logger

logger = setup_logger(__name__)


def parse_categories_from_filename(file_path: Path) -> tuple[str, list[str]]:
    """Парсит категории из имени файла.

    Извлекает название книги и список категорий из имени файла.
    Формат имени файла: "Название книги (категория1, категория2).pdf"

    Args:
        file_path: Путь к файлу.

    Returns:
        Кортеж (название_книги, список_категорий):
        - название_книги: Название книги без категорий и расширения
        - список_категорий: Список категорий (может быть пустым, если не найдены)

    Примеры:
        >>> parse_categories_from_filename(Path("Книга (бизнес).pdf"))
        ("Книга", ["бизнес"])

        >>> parse_categories_from_filename(Path("Книга (бизнес, маркетинг).pdf"))
        ("Книга", ["бизнес", "маркетинг"])

        >>> parse_categories_from_filename(Path("Книга.pdf"))
        ("Книга", [])
    """
    # Получаем имя файла без расширения
    file_stem = file_path.stem
    logger.debug(f"Парсинг категорий из имени файла: {file_path.name} (stem: {file_stem})")

    # Ищем последние скобки перед расширением
    # Паттерн: (категория1, категория2) в конце строки
    pattern = r"\(([^)]+)\)\s*$"
    match = re.search(pattern, file_stem)

    if not match:
        # Категории не найдены
        logger.debug(f"Категории не найдены в имени файла: {file_path.name}")
        return file_stem.strip(), []

    # Извлекаем текст в скобках
    categories_text = match.group(1)
    logger.debug(f"Найден текст категорий в скобках: '{categories_text}'")

    # Извлекаем название книги (всё до скобок)
    book_title = file_stem[: match.start()].strip()
    logger.debug(f"Извлечено название книги: '{book_title}'")

    # Разделяем категории по запятой
    categories_raw = [cat.strip() for cat in categories_text.split(",")]
    logger.debug(f"Разделены категории: {categories_raw}")

    # Очищаем и нормализуем категории (приводим к нижнему регистру)
    categories_normalized = [cat.lower().strip() for cat in categories_raw if cat.strip()]
    logger.debug(f"Нормализованы категории: {categories_normalized}")

    # Валидируем категории
    valid_categories, invalid_categories = validate_categories(categories_normalized)

    if invalid_categories:
        logger.warning(
            f"Найдены невалидные категории в файле {file_path.name}: {invalid_categories}. "
            f"Валидные категории: {valid_categories}"
        )

    if valid_categories:
        logger.info(
            f"Извлечено {len(valid_categories)} валидных категорий из файла {file_path.name}: {valid_categories}"
        )
    else:
        logger.debug(f"Валидные категории не найдены в файле {file_path.name}")

    return book_title, valid_categories


def validate_categories(categories: list[str]) -> tuple[list[str], list[str]]:
    """Валидирует категории по фиксированному списку.

    Проверяет, что все категории присутствуют в Config.CATEGORIES.

    Args:
        categories: Список категорий для валидации.

    Returns:
        Кортеж (валидные_категории, невалидные_категории):
        - валидные_категории: Список категорий, которые есть в Config.CATEGORIES
        - невалидные_категории: Список категорий, которых нет в Config.CATEGORIES

    Примеры:
        >>> validate_categories(["бизнес", "маркетинг"])
        (["бизнес", "маркетинг"], [])

        >>> validate_categories(["бизнес", "неизвестная"])
        (["бизнес"], ["неизвестная"])
    """
    valid_categories = []
    invalid_categories = []

    # Получаем список допустимых категорий из конфигурации
    allowed_categories = [cat.lower() for cat in Config.CATEGORIES]

    for category in categories:
        category_lower = category.lower().strip()
        if category_lower in allowed_categories:
            # Используем оригинальное название из Config (для консистентности)
            original_category = next(
                (cat for cat in Config.CATEGORIES if cat.lower() == category_lower),
                category_lower,
            )
            if original_category not in valid_categories:  # Избегаем дубликатов
                valid_categories.append(original_category)
        else:
            if category_lower not in invalid_categories:  # Избегаем дубликатов
                invalid_categories.append(category_lower)

    logger.debug(
        f"Валидация категорий: валидных={len(valid_categories)}, "
        f"невалидных={len(invalid_categories)}"
    )

    return valid_categories, invalid_categories


def extract_book_title_only(file_path: Path) -> str:
    """Извлекает только название книги из имени файла (без категорий).

    Удобная функция для получения чистого названия книги.

    Args:
        file_path: Путь к файлу.

    Returns:
        Название книги без категорий и расширения.

    Примеры:
        >>> extract_book_title_only(Path("Книга (бизнес).pdf"))
        "Книга"

        >>> extract_book_title_only(Path("Книга.pdf"))
        "Книга"
    """
    title, _ = parse_categories_from_filename(file_path)
    return title







