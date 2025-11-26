#!/usr/bin/env python3
"""Проверка кодировки файла book2.txt напрямую"""

from pathlib import Path

file_path = Path("data/books/book2.txt")

print(f"Проверка файла: {file_path}")
print(f"Существует: {file_path.exists()}")
print()

with open(file_path, "rb") as f:
    raw = f.read()

print(f"Размер файла: {len(raw)} байт")
print(f"Первые 200 байт (hex): {raw[:200].hex()}")
print()

# Пробуем разные кодировки
encodings = ["utf-8", "utf-8-sig", "cp1251", "windows-1251", "latin-1"]

for encoding in encodings:
    try:
        content = raw.decode(encoding, errors="replace")
        preview = content[:200]
        print(f"=== {encoding} ===")
        print(f"Длина: {len(content)} символов")
        print(f"Первые 200 символов: {preview}")
        
        # Проверяем наличие кириллицы
        has_cyrillic = any('\u0400' <= c <= '\u04FF' for c in preview)
        has_speculation = "спекуляция" in preview.lower() or "Спекуляция" in preview
        
        print(f"Содержит кириллицу: {has_cyrillic}")
        print(f"Содержит 'спекуляция': {has_speculation}")
        print()
    except Exception as e:
        print(f"❌ {encoding}: ошибка - {e}")
        print()



