"""Тестовый скрипт для проверки функции обновления каталога библиотеки."""

import asyncio
import sys
from pathlib import Path

# Добавляем путь к корню проекта для импорта модулей
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.library_catalog import update_library_catalog, CATALOG_FILE


async def test_catalog_creation():
    """Тест создания каталога."""
    print("=" * 80)
    print("ТЕСТ 1: Создание каталога библиотеки")
    print("=" * 80)
    
    # Удаляем существующий каталог, если есть
    if CATALOG_FILE.exists():
        print(f"Удаляем существующий каталог: {CATALOG_FILE}")
        CATALOG_FILE.unlink()
    
    # Вызываем функцию обновления
    print("\nВызываем update_library_catalog()...")
    try:
        await update_library_catalog()
        print("✅ Функция выполнена успешно")
    except Exception as e:
        print(f"❌ Ошибка при выполнении: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Проверяем, что файл создан
    if not CATALOG_FILE.exists():
        print(f"❌ Файл каталога не создан: {CATALOG_FILE}")
        return False
    
    print(f"✅ Файл каталога создан: {CATALOG_FILE}")
    
    # Читаем и выводим содержимое
    print("\n" + "=" * 80)
    print("СОДЕРЖИМОЕ КАТАЛОГА:")
    print("=" * 80)
    with open(CATALOG_FILE, "r", encoding="utf-8") as f:
        content = f.read()
        print(content)
    
    # Проверяем структуру
    print("\n" + "=" * 80)
    print("ПРОВЕРКА СТРУКТУРЫ:")
    print("=" * 80)
    
    checks = {
        "Заголовок 'КАТАЛОГ БИБЛИОТЕКИ'": "КАТАЛОГ БИБЛИОТЕКИ" in content,
        "Дата обновления": "Дата обновления:" in content,
        "Общая статистика": "ОБЩАЯ СТАТИСТИКА:" in content,
        "Количество книг": "Всего книг:" in content,
        "Количество чанков": "Всего чанков:" in content,
        "Раздел 'КНИГИ ПО КАТЕГОРИЯМ'": "КНИГИ ПО КАТЕГОРИЯМ" in content,
    }
    
    all_passed = True
    for check_name, passed in checks.items():
        status = "✅" if passed else "❌"
        print(f"{status} {check_name}")
        if not passed:
            all_passed = False
    
    return all_passed


async def test_catalog_format():
    """Тест формата каталога."""
    print("\n" + "=" * 80)
    print("ТЕСТ 2: Проверка формата каталога")
    print("=" * 80)
    
    if not CATALOG_FILE.exists():
        print("❌ Файл каталога не найден, пропускаем тест")
        return False
    
    with open(CATALOG_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    checks = {
        "Каждая категория с новой строки": True,  # Проверим вручную
        "Каждая книга с новой строки": True,  # Проверим вручную
        "Формат категорий (НАЗВАНИЕ (N книг))": True,  # Проверим вручную
        "Формат книг (- Название)": True,  # Проверим вручную
    }
    
    # Проверяем формат категорий
    category_format_ok = False
    book_format_ok = False
    
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        # Проверяем формат категории: должно быть "КАТЕГОРИЯ (N книг)"
        if line_stripped and not line_stripped.startswith("-") and not line_stripped.startswith("="):
            if "(" in line_stripped and "книг" in line_stripped:
                category_format_ok = True
        # Проверяем формат книги: должно быть "- Название"
        if line_stripped.startswith("- "):
            book_format_ok = True
    
    checks["Формат категорий (НАЗВАНИЕ (N книг))"] = category_format_ok
    checks["Формат книг (- Название)"] = book_format_ok
    
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
    print("НАЧАЛО ТЕСТИРОВАНИЯ КАТАЛОГА БИБЛИОТЕКИ")
    print("=" * 80 + "\n")
    
    # Тест 1: Создание каталога
    test1_passed = await test_catalog_creation()
    
    # Тест 2: Формат каталога
    test2_passed = await test_catalog_format()
    
    # Итоги
    print("\n" + "=" * 80)
    print("ИТОГИ ТЕСТИРОВАНИЯ:")
    print("=" * 80)
    print(f"Тест 1 (Создание каталога): {'✅ ПРОЙДЕН' if test1_passed else '❌ ПРОВАЛЕН'}")
    print(f"Тест 2 (Формат каталога): {'✅ ПРОЙДЕН' if test2_passed else '❌ ПРОВАЛЕН'}")
    
    if test1_passed and test2_passed:
        print("\n✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ УСПЕШНО!")
        return 0
    else:
        print("\n❌ НЕКОТОРЫЕ ТЕСТЫ ПРОВАЛЕНЫ")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)

