"""Быстрая проверка кодировки в метаданных."""
import sys
from pathlib import Path

# Добавляем путь к модулям
sys.path.insert(0, str(Path(__file__).parent))

import pickle

metadata_path = Path("data/index.metadata.pkl")

if not metadata_path.exists():
    print("❌ Метаданные не найдены!")
    sys.exit(1)

with open(metadata_path, "rb") as f:
    metadata = pickle.load(f)

print(f"✅ Всего метаданных: {len(metadata)}")

# Проверяем метаданные из book2.txt
book2_metadata = [m for m in metadata if m.get("source") == "book2.txt"]
print(f"✅ Метаданных из book2.txt: {len(book2_metadata)}")

if not book2_metadata:
    print("❌ Не найдено метаданных из book2.txt!")
    sys.exit(1)

# Проверяем первые 3 чанка из book2.txt
print("\n" + "="*80)
for i, meta in enumerate(book2_metadata[:3]):
    chunk_text = meta.get("chunk_text", "")
    chunk_idx = meta.get("chunk_index", i)
    
    print(f"\n--- Чанк {chunk_idx} из book2.txt ---")
    print(f"Длина текста: {len(chunk_text)} символов")
    
    # Показываем первые 150 символов
    preview = chunk_text[:150]
    print(f"\nПервые 150 символов:")
    print(preview)
    
    # Проверяем на кракозябры
    unreadable = sum(1 for c in preview if ord(c) > 127 and not c.isprintable() and c not in "\n\r\t" and c not in "абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ")
    if unreadable > len(preview) * 0.1:
        print(f"\n❌ ВНИМАНИЕ: Обнаружено {unreadable} нечитаемых символов из {len(preview)}!")
    else:
        print(f"\n✅ Текст выглядит нормально (нечитаемых символов: {unreadable})")
    
    # Проверяем, содержит ли текст слово "спекуляция"
    if "спекуляция" in chunk_text.lower() or "Спекуляция" in chunk_text:
        print("✅ Текст содержит слово 'спекуляция'")
    else:
        print("⚠️ Текст НЕ содержит слово 'спекуляция'")
    
    print("="*80)

