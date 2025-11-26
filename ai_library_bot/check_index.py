import pickle
import os
from pathlib import Path

# Определяем путь к файлу индекса относительно расположения скрипта
script_dir = Path(__file__).parent
index_path = script_dir / "data" / "index.files.pkl"

if not index_path.exists():
    print(f"❌ Индекс файлов не найден: {index_path}")
    exit(1)

idx = pickle.load(open(index_path, 'rb'))
print(f'✅ Файлов в индексе: {len(idx)}\n')

for k, v in idx.items():
    file_name = Path(k).name
    chunks_count = v.get("chunks_count", 0)
    file_hash = v.get("file_hash", "")[:16]
    file_type = v.get("file_type", "unknown")
    indexed_at = v.get("indexed_at", "unknown")
    print(f'  📄 {file_name}')
    print(f'     Тип: {file_type}')
    print(f'     Чанков: {chunks_count}')
    print(f'     Хеш: {file_hash}...')
    print(f'     Индексирован: {indexed_at}')
    print()