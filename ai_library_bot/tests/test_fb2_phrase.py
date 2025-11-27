#!/usr/bin/env python3
"""Тестовый скрипт для проверки наличия фразы в FB2 файле и индексе"""

import sys
import os
from pathlib import Path
import pickle
import faiss
import numpy as np

# Определяем базовую директорию проекта (на уровень выше tests/)
SCRIPT_DIR = Path(__file__).parent.parent.absolute()
os.chdir(SCRIPT_DIR)

# Добавляем путь к модулям
sys.path.insert(0, str(SCRIPT_DIR))

from src.config import Config
from src.ingest_service import _read_fb2_file
from src.utils import setup_logger
import asyncio

logger = setup_logger(__name__)

PHRASE = "Ротация — это не абстракция"


async def test_fb2_phrase():
    """Проверяет наличие фразы в FB2 файле и индексе"""
    print(f"\n{'='*80}")
    print(f"ПОИСК ФРАЗЫ: '{PHRASE}'")
    print(f"{'='*80}\n")
    
    # Находим FB2 файлы
    script_dir = Path(__file__).parent.parent
    books_dir = script_dir / "data" / "books"
    fb2_files = list(books_dir.glob("*.fb2"))
    
    if not fb2_files:
        print("❌ FB2 файлы не найдены!")
        return
    
    print(f"Найдено {len(fb2_files)} FB2 файлов\n")
    
    # Проверяем каждый FB2 файл
    for fb2_file in fb2_files:
        print(f"\n{'='*80}")
        print(f"Проверка файла: {fb2_file.name}")
        print(f"{'='*80}\n")
        
        # Читаем FB2 файл
        print("1. Чтение FB2 файла...")
        try:
            content = await _read_fb2_file(fb2_file)
            print(f"✅ Файл прочитан, длина: {len(content)} символов\n")
        except Exception as e:
            print(f"❌ Ошибка при чтении: {e}\n")
            continue
        
        # Ищем фразу в тексте
        print(f"2. Поиск фразы '{PHRASE}' в тексте...")
        phrase_lower = PHRASE.lower()
        content_lower = content.lower()
        
        if phrase_lower in content_lower:
            # Находим все вхождения
            positions = []
            start = 0
            while True:
                pos = content_lower.find(phrase_lower, start)
                if pos == -1:
                    break
                positions.append(pos)
                start = pos + 1
            
            print(f"✅ Фраза найдена {len(positions)} раз(а) в позициях: {positions}\n")
            
            # Показываем контекст вокруг каждого вхождения
            for i, pos in enumerate(positions, 1):
                start_ctx = max(0, pos - 200)
                end_ctx = min(len(content), pos + len(PHRASE) + 200)
                context = content[start_ctx:end_ctx]
                
                print(f"--- Вхождение {i} (позиция {pos}) ---")
                print(f"Контекст (200 символов до и после):")
                print(f"...{context}...")
                print()
        else:
            print(f"❌ Фраза НЕ найдена в тексте!\n")
            
            # Пробуем найти похожие фразы
            print("3. Поиск похожих фраз...")
            words = PHRASE.lower().split()
            for word in words:
                if word in content_lower:
                    print(f"  ✅ Слово '{word}' найдено")
                else:
                    print(f"  ❌ Слово '{word}' НЕ найдено")
            print()
    
    # Проверяем индекс
    print(f"\n{'='*80}")
    print("Проверка FAISS индекса")
    print(f"{'='*80}\n")
    
    script_dir = Path(__file__).parent.parent
    index_path = script_dir / Config.FAISS_PATH
    metadata_path = index_path.with_suffix(".metadata.pkl")
    
    if not index_path.exists() or not metadata_path.exists():
        print("❌ Индекс не найден!")
        return
    
    print("4. Загрузка метаданных из индекса...")
    with open(metadata_path, "rb") as f:
        metadata = pickle.load(f)
    
    print(f"✅ Загружено {len(metadata)} метаданных\n")
    
    # Ищем фразу в метаданных (в chunk_text)
    print(f"5. Поиск фразы '{PHRASE}' в метаданных индекса...")
    found_in_metadata = []
    
    for i, meta in enumerate(metadata):
        chunk_text = meta.get("chunk_text", "")
        source = meta.get("source", "unknown")
        
        if phrase_lower in chunk_text.lower():
            found_in_metadata.append({
                "index": i,
                "source": source,
                "chunk_index": meta.get("chunk_index", i),
                "position": chunk_text.lower().find(phrase_lower),
                "preview": chunk_text[max(0, chunk_text.lower().find(phrase_lower) - 100):
                                     min(len(chunk_text), chunk_text.lower().find(phrase_lower) + len(PHRASE) + 100)]
            })
    
    if found_in_metadata:
        print(f"✅ Фраза найдена в {len(found_in_metadata)} чанке(ах) индекса:\n")
        for item in found_in_metadata:
            print(f"--- Чанк {item['chunk_index']} из {item['source']} (индекс {item['index']}) ---")
            print(f"Позиция в чанке: {item['position']}")
            print(f"Контекст: ...{item['preview']}...")
            print()
    else:
        print(f"❌ Фраза НЕ найдена в метаданных индекса!\n")
        
        # Проверяем, есть ли хотя бы слова из фразы
        print("6. Поиск отдельных слов из фразы в индексе...")
        words = PHRASE.lower().split()
        word_counts = {word: 0 for word in words}
        
        for meta in metadata:
            chunk_text = meta.get("chunk_text", "").lower()
            source = meta.get("source", "unknown")
            
            for word in words:
                if word in chunk_text:
                    word_counts[word] += 1
        
        for word, count in word_counts.items():
            if count > 0:
                print(f"  ✅ Слово '{word}' найдено в {count} чанках")
            else:
                print(f"  ❌ Слово '{word}' НЕ найдено")
        print()


if __name__ == "__main__":
    asyncio.run(test_fb2_phrase())



