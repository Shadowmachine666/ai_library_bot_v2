#!/usr/bin/env python3
"""Тестовый скрипт для проверки бота с запросом"""

import asyncio
import sys
from pathlib import Path

# Добавляем путь к модулям (теперь мы в tests/, нужно подняться на уровень выше)
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.analyzer import analyze
from src.retriever_service import retrieve_chunks, NOT_FOUND
from src.formatters import format_response
from src.utils import setup_logger

logger = setup_logger(__name__)


async def test_query(query: str):
    """Тестирует запрос через весь pipeline бота"""
    print(f"\n{'='*80}")
    print(f"ТЕСТОВЫЙ ЗАПРОС: {query}")
    print(f"{'='*80}\n")
    
    # Этап 1: Поиск релевантных чанков
    print("🔍 Этап 1: Поиск релевантных чанков...")
    chunks = await retrieve_chunks(query)
    
    if chunks == NOT_FOUND:
        print("❌ Не найдено релевантных чанков")
        return
    
    print(f"✅ Найдено {len(chunks)} релевантных чанков\n")
    
    # Показываем найденные чанки
    for i, chunk in enumerate(chunks[:3], 1):
        print(f"--- Чанк {i} ---")
        print(f"Источник: {chunk.get('source', 'unknown')}")
        print(f"Score: {chunk.get('score', 'N/A')}")
        print(f"Текст (первые 200 символов): {chunk.get('text', '')[:200]}...")
        print()
    
    # Этап 2: Анализ через LLM
    print("🤖 Этап 2: Анализ через LLM...")
    analysis_response = await analyze(chunks, query)
    
    print(f"✅ Анализ завершён, статус: {analysis_response.status}\n")
    
    # Этап 3: Форматирование ответа
    print("📝 Этап 3: Форматирование ответа...")
    response_text = format_response(analysis_response)
    
    print(f"\n{'='*80}")
    print("ОТВЕТ БОТА:")
    print(f"{'='*80}\n")
    print(response_text)
    print(f"\n{'='*80}\n")


if __name__ == "__main__":
    query = "ЗАЧЕМ ИЗУЧАТЬ ЭТОЛОГИЮ?"
    asyncio.run(test_query(query))

