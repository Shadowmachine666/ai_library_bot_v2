#!/usr/bin/env python3
"""Проверка кодировки файла book2.txt"""

from pathlib import Path

# Теперь мы в tests/, нужно подняться на уровень выше
file_path = Path(__file__).parent.parent / "data" / "books" / "book2.txt"

print(f"Проверка файла: {file_path}")
print(f"Существует: {file_path.exists()}")
print()

with open(file_path, "rb") as f:
    raw = f.read()

print(f"Размер файла: {len(raw)} байт")
print()

# Пробуем разные кодировки
encodings = ["utf-8", "utf-8-sig", "cp1251", "windows-1251", "latin-1"]

for encoding in encodings:
    try:
        content = raw.decode(encoding)
        print(f"✅ {encoding}: успешно декодировано, длина: {len(content)} символов")
        preview = content[:150]
        print(f"   Первые 150 символов: {preview}")
        if "спекуляция" in preview.lower():
            print(f"   ✅ Содержит слово 'спекуляция'")
        print()
    except Exception as e:
        print(f"❌ {encoding}: ошибка - {e}")
        print()


