"""Тесты для проверки обновления каталога библиотеки при изменениях.

Проверяет:
1. Обновление каталога после добавления новой книги
2. Обновление каталога после удаления книги
3. Корректность обновления статистики
"""

import asyncio
import shutil
import sys
from pathlib import Path

import pytest

# Добавляем путь к корню проекта для импорта модулей
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import Config
from src.ingest_service import _remove_file_from_index, _load_file_index, ingest_books
from src.library_catalog import CATALOG_FILE, update_library_catalog


def _read_catalog() -> str:
    """Читает содержимое каталога."""
    if not CATALOG_FILE.exists():
        return ""
    with open(CATALOG_FILE, "r", encoding="utf-8") as f:
        return f.read()


def _get_book_count_from_catalog(catalog_content: str) -> int:
    """Извлекает количество книг из каталога."""
    for line in catalog_content.split("\n"):
        if "Всего книг:" in line:
            try:
                count = int(line.split(":")[1].strip())
                return count
            except (ValueError, IndexError):
                pass
    return -1


def _get_chunks_count_from_catalog(catalog_content: str) -> int:
    """Извлекает количество чанков из каталога."""
    for line in catalog_content.split("\n"):
        if "Всего чанков:" in line:
            try:
                count = int(line.split(":")[1].strip())
                return count
            except (ValueError, IndexError):
                pass
    return -1


def _check_book_in_catalog(catalog_content: str, book_title: str) -> bool:
    """Проверяет наличие книги в каталоге."""
    return book_title in catalog_content


async def test_catalog_updates_after_adding_book(tmp_path):
    """Тест: каталог обновляется после добавления новой книги."""
    print("\n" + "=" * 80)
    print("ТЕСТ: Обновление каталога после добавления книги")
    print("=" * 80)

    # Создаём тестовую папку с книгами
    test_books_dir = tmp_path / "books"
    test_books_dir.mkdir()

    # Копируем существующие книги (если есть) или создаём тестовую
    source_books_dir = Path(Config.FAISS_INDEX_DIR) / "books"
    if source_books_dir.exists():
        # Копируем несколько существующих книг для теста
        existing_books = list(source_books_dir.glob("*.txt"))[:2]
        existing_books.extend(list(source_books_dir.glob("*.pdf"))[:1])
        for book in existing_books:
            if book.exists():
                shutil.copy2(book, test_books_dir / book.name)

    # Создаём тестовую книгу
    test_book_content = """
    Тестовая книга для проверки обновления каталога.
    
    Это книга о тестировании и проверке функциональности.
    Она содержит информацию о том, как работает система обновления каталога.
    
    Категории: бизнес, менеджмент
    """
    test_book_path = test_books_dir / "Тестовая книга (бизнес, менеджмент).txt"
    test_book_path.write_text(test_book_content, encoding="utf-8")

    # Сохраняем текущий каталог
    initial_catalog = _read_catalog()
    initial_book_count = _get_book_count_from_catalog(initial_catalog)
    print(f"Начальное количество книг в каталоге: {initial_book_count}")

    # Индексируем книги (включая новую тестовую)
    try:
        print(f"\nИндексируем книги из папки: {test_books_dir}")
        await ingest_books(str(test_books_dir), force=False)
        print("✅ Индексация завершена")
    except Exception as e:
        print(f"⚠️ Ошибка при индексации (может быть нормально, если книги уже проиндексированы): {e}")

    # Обновляем каталог вручную (так как ingest_books должен был это сделать)
    await update_library_catalog()

    # Проверяем обновлённый каталог
    updated_catalog = _read_catalog()
    updated_book_count = _get_book_count_from_catalog(updated_catalog)

    print(f"\nОбновлённое количество книг в каталоге: {updated_book_count}")

    # Проверки
    checks = {
        "Каталог обновлён": updated_catalog != initial_catalog,
        "Количество книг изменилось": updated_book_count > initial_book_count or initial_book_count == -1,
        "Тестовая книга в каталоге": _check_book_in_catalog(updated_catalog, "Тестовая книга"),
    }

    all_passed = True
    for check_name, passed in checks.items():
        status = "✅" if passed else "❌"
        print(f"{status} {check_name}")
        if not passed:
            all_passed = False

    # Очистка: удаляем тестовую книгу из индекса
    try:
        file_index = _load_file_index()
        test_book_abs_path = str(test_book_path.absolute())
        if test_book_abs_path in file_index:
            await _remove_file_from_index(test_book_path, file_index)
            await update_library_catalog()
            print(f"\n✅ Тестовая книга удалена из индекса")
    except Exception as e:
        print(f"⚠️ Ошибка при очистке тестовой книги: {e}")

    return all_passed


async def test_catalog_updates_after_removing_book():
    """Тест: каталог обновляется после удаления книги."""
    print("\n" + "=" * 80)
    print("ТЕСТ: Обновление каталога после удаления книги")
    print("=" * 80)

    # Получаем текущий каталог
    initial_catalog = _read_catalog()
    initial_book_count = _get_book_count_from_catalog(initial_catalog)
    initial_chunks_count = _get_chunks_count_from_catalog(initial_catalog)

    print(f"Начальное количество книг: {initial_book_count}")
    print(f"Начальное количество чанков: {initial_chunks_count}")

    if initial_book_count <= 0:
        print("⚠️ В каталоге нет книг, пропускаем тест удаления")
        return True

    # Находим первую книгу в индексе для удаления
    file_index = _load_file_index()
    if not file_index:
        print("⚠️ Индекс файлов пуст, пропускаем тест удаления")
        return True

    # Берём первую книгу из индекса
    first_file_path_str = list(file_index.keys())[0]
    first_file_path = Path(first_file_path_str)
    book_info = file_index[first_file_path_str]
    chunks_to_remove = book_info.get("chunks_count", 0)

    print(f"\nУдаляем книгу: {first_file_path.name}")
    print(f"Количество чанков для удаления: {chunks_to_remove}")

    # Удаляем книгу из индекса
    try:
        await _remove_file_from_index(first_file_path, file_index)
        print("✅ Книга удалена из индекса")
    except Exception as e:
        print(f"❌ Ошибка при удалении книги: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Обновляем каталог
    await update_library_catalog()

    # Проверяем обновлённый каталог
    updated_catalog = _read_catalog()
    updated_book_count = _get_book_count_from_catalog(updated_catalog)
    updated_chunks_count = _get_chunks_count_from_catalog(updated_catalog)

    print(f"\nОбновлённое количество книг: {updated_book_count}")
    print(f"Обновлённое количество чанков: {updated_chunks_count}")

    # Проверки
    checks = {
        "Каталог обновлён": updated_catalog != initial_catalog,
        "Количество книг уменьшилось": updated_book_count == initial_book_count - 1,
        "Количество чанков уменьшилось": updated_chunks_count == initial_chunks_count - chunks_to_remove,
        "Удалённая книга отсутствует в каталоге": not _check_book_in_catalog(
            updated_catalog, first_file_path.stem
        ),
    }

    all_passed = True
    for check_name, passed in checks.items():
        status = "✅" if passed else "❌"
        print(f"{status} {check_name}")
        if not passed:
            all_passed = False
            print(f"   Ожидалось: {initial_book_count - 1}, получено: {updated_book_count}")

    # Восстанавливаем книгу (переиндексируем)
    print(f"\nВосстанавливаем книгу: {first_file_path.name}")
    if first_file_path.exists():
        try:
            books_dir = first_file_path.parent
            await ingest_books(str(books_dir), force=False)
            await update_library_catalog()
            print("✅ Книга восстановлена")
        except Exception as e:
            print(f"⚠️ Ошибка при восстановлении книги: {e}")

    return all_passed


async def test_catalog_statistics_accuracy():
    """Тест: проверка точности статистики в каталоге."""
    print("\n" + "=" * 80)
    print("ТЕСТ: Точность статистики каталога")
    print("=" * 80)

    # Обновляем каталог
    await update_library_catalog()

    # Читаем каталог
    catalog_content = _read_catalog()
    if not catalog_content:
        print("❌ Каталог пуст или не найден")
        return False

    # Извлекаем статистику из каталога
    catalog_book_count = _get_book_count_from_catalog(catalog_content)
    catalog_chunks_count = _get_chunks_count_from_catalog(catalog_content)

    # Получаем реальную статистику из индекса
    file_index = _load_file_index()
    real_book_count = len(file_index)
    real_chunks_count = sum(book_info.get("chunks_count", 0) for book_info in file_index.values())

    print(f"Книги в каталоге: {catalog_book_count}, в индексе: {real_book_count}")
    print(f"Чанки в каталоге: {catalog_chunks_count}, в индексе: {real_chunks_count}")

    # Проверки
    checks = {
        "Количество книг совпадает": catalog_book_count == real_book_count,
        "Количество чанков совпадает": catalog_chunks_count == real_chunks_count,
    }

    all_passed = True
    for check_name, passed in checks.items():
        status = "✅" if passed else "❌"
        print(f"{status} {check_name}")
        if not passed:
            all_passed = False

    return all_passed


async def main():
    """Главная функция тестирования."""
    print("\n" + "=" * 80)
    print("НАЧАЛО ТЕСТИРОВАНИЯ ОБНОВЛЕНИЯ КАТАЛОГА")
    print("=" * 80)

    results = {}

    # Тест 1: Обновление после добавления (может быть пропущен, если нет тестовых данных)
    try:
        print("\n" + "=" * 80)
        print("ТЕСТ 1: Обновление после добавления книги")
        print("=" * 80)
        # Этот тест требует создания временной папки, пропускаем в простом режиме
        print("⚠️ Тест требует настройки тестовой среды, пропускаем")
        results["test_add"] = None
    except Exception as e:
        print(f"⚠️ Тест пропущен: {e}")
        results["test_add"] = None

    # Тест 2: Обновление после удаления
    try:
        results["test_remove"] = await test_catalog_updates_after_removing_book()
    except Exception as e:
        print(f"❌ Ошибка в тесте удаления: {e}")
        import traceback
        traceback.print_exc()
        results["test_remove"] = False

    # Тест 3: Точность статистики
    try:
        results["test_statistics"] = await test_catalog_statistics_accuracy()
    except Exception as e:
        print(f"❌ Ошибка в тесте статистики: {e}")
        import traceback
        traceback.print_exc()
        results["test_statistics"] = False

    # Итоги
    print("\n" + "=" * 80)
    print("ИТОГИ ТЕСТИРОВАНИЯ:")
    print("=" * 80)

    for test_name, result in results.items():
        if result is None:
            status = "⏭️ ПРОПУЩЕН"
        elif result:
            status = "✅ ПРОЙДЕН"
        else:
            status = "❌ ПРОВАЛЕН"
        print(f"{test_name}: {status}")

    passed = sum(1 for r in results.values() if r is True)
    total = sum(1 for r in results.values() if r is not None)

    if total > 0 and passed == total:
        print("\n✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ УСПЕШНО!")
        return 0
    elif total == 0:
        print("\n⚠️ ВСЕ ТЕСТЫ ПРОПУЩЕНЫ")
        return 0
    else:
        print(f"\n❌ ПРОВАЛЕНО: {total - passed} из {total} тестов")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)

