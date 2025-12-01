"""Модуль для создания и обновления каталога библиотеки.

Создаёт текстовый файл library_catalog.txt с списком всех проиндексированных книг,
сгруппированных по категориям, с общей статистикой.
"""

import pickle
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config import Config
from src.utils import run_in_executor, setup_logger

logger = setup_logger(__name__)

# Путь к файлу каталога
CATALOG_FILE = Config.FAISS_INDEX_DIR / "library_catalog.txt"


@run_in_executor
def _load_metadata() -> list[dict[str, Any]]:
    """Загружает метаданные из index.metadata.pkl.

    Returns:
        Список всех метаданных чанков. Если файл не найден или произошла ошибка,
        возвращает пустой список.
    """
    metadata_path = Config.FAISS_PATH.with_suffix(".metadata.pkl")

    if not metadata_path.exists():
        logger.debug("Файл метаданных не найден, возвращаем пустой список")
        return []

    try:
        with open(metadata_path, "rb") as f:
            metadata = pickle.load(f)
        logger.debug(f"Загружено {len(metadata)} метаданных чанков")
        return metadata
    except Exception as e:
        logger.error(f"Ошибка при загрузке метаданных: {e}")
        return []


def _extract_books_info(metadata: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Извлекает информацию о книгах из метаданных.

    Группирует чанки по книгам (по file_path) и собирает информацию о каждой книге.

    Args:
        metadata: Список метаданных чанков.

    Returns:
        Словарь, где ключ - file_path (строка), значение - словарь с информацией:
        {
            "title": str,           # Название книги
            "file_path": str,       # Полный путь к файлу
            "categories": set[str], # Уникальные категории из всех чанков
            "chunks_count": int,    # Количество чанков
        }
    """
    books_info: dict[str, dict[str, Any]] = {}

    for chunk_meta in metadata:
        # Получаем file_path (может быть в разных форматах)
        file_path_str = chunk_meta.get("file_path", "")
        if not file_path_str:
            # Пробуем получить из source
            source = chunk_meta.get("source", "")
            if source:
                # Если source - это имя файла, нужно найти полный путь
                # Но для группировки можем использовать source как ключ
                file_path_str = source
            else:
                logger.warning("Чанк не содержит file_path или source, пропускаем")
                continue

        # Нормализуем путь (приводим к абсолютному)
        try:
            file_path = Path(file_path_str)
            if not file_path.is_absolute():
                # Если путь относительный, пробуем найти его относительно data/books
                books_dir = Config.FAISS_INDEX_DIR / "books"
                potential_path = books_dir / file_path.name
                if potential_path.exists():
                    file_path = potential_path.absolute()
                else:
                    file_path = file_path.absolute()
            file_path_str = str(file_path.absolute())
        except Exception as e:
            logger.debug(f"Ошибка при нормализации пути {file_path_str}: {e}")
            # Используем исходный путь как есть

        # Получаем или создаём запись о книге
        if file_path_str not in books_info:
            title = chunk_meta.get("title", "")
            if not title:
                # Если title нет, используем имя файла
                title = Path(file_path_str).stem

            books_info[file_path_str] = {
                "title": title,
                "file_path": file_path_str,
                "categories": set(),
                "chunks_count": 0,
            }

        # Добавляем категории из чанка
        book_info = books_info[file_path_str]
        topics = chunk_meta.get("topics", [])
        if topics:
            if isinstance(topics, list):
                book_info["categories"].update(topics)
            elif isinstance(topics, str):
                book_info["categories"].add(topics)

        # Увеличиваем счётчик чанков
        book_info["chunks_count"] += 1

    # Преобразуем sets в sorted lists для удобства
    for book_info in books_info.values():
        book_info["categories"] = sorted(list(book_info["categories"]))

    logger.info(f"Извлечена информация о {len(books_info)} книгах")
    return books_info


def _calculate_statistics(books_info: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Вычисляет общую статистику по библиотеке.

    Args:
        books_info: Словарь с информацией о книгах.

    Returns:
        Словарь со статистикой:
        {
            "total_books": int,                    # Общее количество книг
            "total_chunks": int,                   # Общее количество чанков
            "categories_count": dict[str, int],    # Количество книг по категориям
            "used_categories": set[str],           # Используемые категории
            "update_date": str,                    # Дата обновления
        }
    """
    total_books = len(books_info)
    total_chunks = sum(book["chunks_count"] for book in books_info.values())

    # Подсчитываем количество книг по категориям
    categories_count: dict[str, int] = defaultdict(int)
    used_categories: set[str] = set()
    books_without_categories = 0

    for book_info in books_info.values():
        categories = book_info.get("categories", [])
        if not categories:
            books_without_categories += 1
            continue

        for category in categories:
            # Проверяем, является ли категория валидной
            if category in Config.CATEGORIES:
                categories_count[category] += 1
                used_categories.add(category)
            else:
                # Невалидная категория - добавляем в "Другое"
                categories_count["Другое"] = categories_count.get("Другое", 0) + 1
                used_categories.add("Другое")
                logger.warning(
                    f"Найдена невалидная категория '{category}' для книги '{book_info['title']}'"
                )

    if books_without_categories > 0:
        logger.warning(f"Найдено {books_without_categories} книг без категорий")

    statistics = {
        "total_books": total_books,
        "total_chunks": total_chunks,
        "categories_count": dict(categories_count),
        "used_categories": sorted(list(used_categories)),
        "update_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "books_without_categories": books_without_categories,
    }

    logger.debug(f"Статистика: {total_books} книг, {total_chunks} чанков, {len(used_categories)} категорий")
    return statistics


def _group_books_by_categories(books_info: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Группирует книги по категориям.

    Книга может быть в нескольких категориях.

    Args:
        books_info: Словарь с информацией о книгах.

    Returns:
        Словарь, где ключ - название категории, значение - список книг:
        {
            "категория": [
                {
                    "title": str,
                    "file_path": str,
                    "chunks_count": int,
                },
                ...
            ],
            ...
        }
    """
    books_by_categories: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for book_info in books_info.values():
        categories = book_info.get("categories", [])
        if not categories:
            # Книги без категорий добавляем в специальную категорию
            books_by_categories["Без категории"].append(
                {
                    "title": book_info["title"],
                    "file_path": book_info["file_path"],
                    "chunks_count": book_info["chunks_count"],
                }
            )
            continue

        for category in categories:
            # Проверяем валидность категории
            if category in Config.CATEGORIES:
                valid_category = category
            else:
                # Невалидная категория - добавляем в "Другое"
                valid_category = "Другое"

            books_by_categories[valid_category].append(
                {
                    "title": book_info["title"],
                    "file_path": book_info["file_path"],
                    "chunks_count": book_info["chunks_count"],
                }
            )

    # Сортируем книги внутри каждой категории по названию
    for category in books_by_categories:
        books_by_categories[category].sort(key=lambda x: x["title"].lower())

    logger.debug(f"Книги сгруппированы по {len(books_by_categories)} категориям")
    return dict(books_by_categories)


def _format_catalog_text(statistics: dict[str, Any], books_by_categories: dict[str, list[dict[str, Any]]]) -> str:
    """Форматирует каталог в читаемый текст.

    Args:
        statistics: Словарь со статистикой.
        books_by_categories: Словарь с книгами, сгруппированными по категориям.

    Returns:
        Отформатированный текст каталога.
    """
    lines = []
    lines.append("=" * 80)
    lines.append("КАТАЛОГ БИБЛИОТЕКИ")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"Дата обновления: {statistics['update_date']}")
    lines.append("")
    lines.append("ОБЩАЯ СТАТИСТИКА:")
    lines.append(f"- Всего книг: {statistics['total_books']}")
    lines.append(f"- Всего чанков: {statistics['total_chunks']}")
    lines.append(f"- Категорий: {len(statistics['used_categories'])}")
    if statistics.get("books_without_categories", 0) > 0:
        lines.append(f"- Книг без категорий: {statistics['books_without_categories']}")
    lines.append("")

    # Статистика по категориям
    if statistics["categories_count"]:
        lines.append("КОЛИЧЕСТВО КНИГ ПО КАТЕГОРИЯМ:")
        # Сортируем категории по количеству книг (по убыванию), затем по алфавиту
        sorted_categories = sorted(
            statistics["categories_count"].items(),
            key=lambda x: (-x[1], x[0].lower()),
        )
        for category, count in sorted_categories:
            lines.append(f"- {category}: {count}")
        lines.append("")

    lines.append("=" * 80)
    lines.append("КНИГИ ПО КАТЕГОРИЯМ")
    lines.append("=" * 80)
    lines.append("")

    # Если нет книг
    if not books_by_categories:
        lines.append("Библиотека пуста.")
        return "\n".join(lines)

    # Сортируем категории: сначала валидные по алфавиту, потом "Без категории", потом "Другое"
    def category_sort_key(category: str) -> tuple[int, str]:
        """Ключ для сортировки категорий."""
        if category in Config.CATEGORIES:
            # Валидные категории - по алфавиту
            return (0, category.lower())
        elif category == "Без категории":
            return (1, "")
        else:  # "Другое" или другие невалидные
            return (2, category.lower())

    sorted_category_names = sorted(books_by_categories.keys(), key=category_sort_key)

    # Форматируем каждую категорию
    for category in sorted_category_names:
        books = books_by_categories[category]
        category_upper = category.upper()
        lines.append(f"{category_upper} ({len(books)} книг)")
        for book in books:
            lines.append(f"- {book['title']}")
        lines.append("")

    return "\n".join(lines)


@run_in_executor
def _save_catalog(catalog_text: str) -> None:
    """Сохраняет каталог в файл.

    Args:
        catalog_text: Текст каталога для сохранения.
    """
    try:
        # Создаём директорию, если её нет
        CATALOG_FILE.parent.mkdir(parents=True, exist_ok=True)

        # Сохраняем файл с кодировкой UTF-8
        with open(CATALOG_FILE, "w", encoding="utf-8") as f:
            f.write(catalog_text)

        logger.info(f"Каталог сохранён: {CATALOG_FILE}")
    except Exception as e:
        logger.error(f"Ошибка при сохранении каталога: {e}")
        raise ValueError(f"Не удалось сохранить каталог: {e}") from e


async def update_library_catalog() -> None:
    """Главная функция для обновления каталога библиотеки.

    Загружает метаданные, извлекает информацию о книгах, вычисляет статистику,
    группирует по категориям, форматирует и сохраняет в файл library_catalog.txt.

    Обрабатывает ошибки и не прерывает выполнение при неудаче.
    """
    try:
        logger.info("[CATALOG] Начало обновления каталога библиотеки")

        # Загружаем метаданные
        metadata = await _load_metadata()

        if not metadata:
            logger.warning("[CATALOG] Метаданные не найдены или пусты, создаём пустой каталог")
            # Создаём пустой каталог
            empty_statistics = {
                "total_books": 0,
                "total_chunks": 0,
                "categories_count": {},
                "used_categories": [],
                "update_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "books_without_categories": 0,
            }
            # Добавляем статистику по всем категориям (0 книг)
            for category in Config.CATEGORIES:
                empty_statistics["categories_count"][category] = 0

            catalog_text = _format_catalog_text(empty_statistics, {})
            await _save_catalog(catalog_text)
            logger.info("[CATALOG] Пустой каталог создан")
            return

        # Извлекаем информацию о книгах
        books_info = _extract_books_info(metadata)
        logger.info(f"[CATALOG] Обработано {len(books_info)} книг")

        if not books_info:
            logger.warning("[CATALOG] Не найдено ни одной книги, создаём пустой каталог")
            empty_statistics = {
                "total_books": 0,
                "total_chunks": 0,
                "categories_count": {},
                "used_categories": [],
                "update_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "books_without_categories": 0,
            }
            for category in Config.CATEGORIES:
                empty_statistics["categories_count"][category] = 0
            catalog_text = _format_catalog_text(empty_statistics, {})
            await _save_catalog(catalog_text)
            return

        # Вычисляем статистику
        statistics = _calculate_statistics(books_info)
        logger.debug(f"[CATALOG] Статистика вычислена: {statistics['total_books']} книг")

        # Группируем по категориям
        books_by_categories = _group_books_by_categories(books_info)
        logger.debug(f"[CATALOG] Книги сгруппированы по {len(books_by_categories)} категориям")

        # Форматируем каталог
        catalog_text = _format_catalog_text(statistics, books_by_categories)

        # Сохраняем каталог
        await _save_catalog(catalog_text)

        logger.info(
            f"[CATALOG] ✅ Каталог успешно обновлён: {statistics['total_books']} книг, "
            f"{len(statistics['used_categories'])} категорий"
        )

    except Exception as e:
        logger.error(f"[CATALOG] ❌ Ошибка при обновлении каталога: {e}", exc_info=True)
        # Не прерываем выполнение - ошибка обновления каталога не должна останавливать индексацию


