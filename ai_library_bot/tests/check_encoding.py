"""Скрипт для проверки кодировки в метаданных FAISS индекса."""
import pickle
from pathlib import Path

# Теперь мы в tests/, нужно подняться на уровень выше
metadata_path = Path(__file__).parent.parent / "data" / "index.metadata.pkl"

if not metadata_path.exists():
    print("Метаданные не найдены!")
    exit(1)

with open(metadata_path, "rb") as f:
    metadata = pickle.load(f)

print(f"Всего метаданных: {len(metadata)}")

# Проверяем метаданные из book2.txt
book2_metadata = [m for m in metadata if m.get("source") == "book2.txt"]
print(f"\nМетаданных из book2.txt: {len(book2_metadata)}")

# Проверяем первые 5 чанков из book2.txt на кракозябры
for i, meta in enumerate(book2_metadata[:5]):
    chunk_text = meta.get("chunk_text", "")
    chunk_idx = meta.get("chunk_index", i)
    source = meta.get("source", "unknown")
    
    print(f"\n--- Чанк {chunk_idx} из {source} ---")
    print(f"Длина текста: {len(chunk_text)} символов")
    
    # Показываем первые 200 символов
    preview = chunk_text[:200]
    print(f"Первые 200 символов:")
    print(preview)
    print()
    
    # Проверяем на кракозябры
    unreadable = sum(1 for c in preview if ord(c) > 127 and not c.isprintable() and c not in "\n\r\t" and c not in "абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ")
    if unreadable > len(preview) * 0.1:
        print(f"⚠️ ВНИМАНИЕ: Обнаружено {unreadable} нечитаемых символов из {len(preview)}!")
    else:
        print("✅ Текст выглядит нормально")

