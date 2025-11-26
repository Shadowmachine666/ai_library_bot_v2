# Метрики проекта ai_library_bot

Документ описывает метрики, которые необходимо отслеживать для мониторинга работы системы.

## Основные метрики

### 1. Latency (Задержка)

**Описание:** Время от получения запроса пользователя до отправки ответа.

**Типы задержек:**
- **Retrieval latency** — время поиска релевантных чанков в FAISS
- **Embedding latency** — время создания эмбеддинга для запроса
- **LLM latency** — время генерации ответа LLM
- **Total latency** — общее время обработки запроса

**Целевые значения:**
- Retrieval: < 100ms
- Embedding: < 200ms
- LLM: < 3s (gpt-4o-mini), < 5s (gpt-4o)
- Total: < 4s

**Как измерять:**
```python
import time

start = time.time()
result = await retrieve_chunks(query)
latency = time.time() - start
```

### 2. Errors (Ошибки)

**Описание:** Количество и типы ошибок в системе.

**Типы ошибок:**
- **Retrieval errors** — ошибки при поиске в FAISS
- **Embedding errors** — ошибки при создании эмбеддингов
- **LLM errors** — ошибки при вызове OpenAI API
- **Telegram errors** — ошибки при отправке сообщений
- **File processing errors** — ошибки при обработке файлов

**Целевые значения:**
- Error rate: < 1% от всех запросов
- Retry success rate: > 90%

**Как измерять:**
```python
try:
    result = await operation()
except Exception as e:
    logger.error(f"Error in operation: {e}")
    error_count += 1
```

### 3. Index Size (Размер индекса)

**Описание:** Размер FAISS индекса и количество проиндексированных документов.

**Метрики:**
- **Number of chunks** — количество чанков в индексе
- **Index file size** — размер файла индекса на диске (MB)
- **Number of books** — количество проиндексированных книг
- **Average chunks per book** — среднее количество чанков на книгу

**Целевые значения:**
- Max chunks: 50,000 (для 50 книг по ~1000 чанков)
- Max index size: ~500 MB (зависит от размерности эмбеддингов)

**Как измерять:**
```python
import os
from pathlib import Path

index_path = Path(Config.FAISS_PATH)
index_size_mb = index_path.stat().st_size / (1024 * 1024)
num_chunks = index.ntotal  # для FAISS
```

### 4. Embedding Cost (Стоимость эмбеддингов)

**Описание:** Стоимость использования OpenAI API для создания эмбеддингов.

**Метрики:**
- **Total tokens** — общее количество токенов, отправленных в API
- **Total cost** — общая стоимость в USD
- **Cost per book** — средняя стоимость индексации одной книги
- **Cost per query** — средняя стоимость обработки одного запроса

**Целевые значения:**
- Embedding model: `text-embedding-3-small` — $0.02 / 1M tokens
- Для 50 книг (примерно 50,000 чанков): ~$1-2 за индексацию
- Запрос: ~$0.00001 за запрос (1 эмбеддинг)

**Как измерять:**
```python
# Пример расчёта стоимости
tokens_per_chunk = 200  # примерное значение
total_chunks = 50000
total_tokens = tokens_per_chunk * total_chunks
cost_per_1m_tokens = 0.02
total_cost = (total_tokens / 1_000_000) * cost_per_1m_tokens
```

## Дополнительные метрики

### 5. Cache Hit Rate

**Описание:** Процент запросов, которые были обработаны из кэша.

**Целевое значение:** > 30% (для повторяющихся запросов)

### 6. Retrieval Quality

**Описание:** Качество поиска релевантных чанков.

**Метрики:**
- **Average score** — средний score релевантности найденных чанков
- **Chunks above threshold** — количество чанков с score > 0.7
- **NOT_FOUND rate** — процент запросов без релевантных результатов

**Целевые значения:**
- Average score: > 0.75
- NOT_FOUND rate: < 10%

### 7. User Engagement

**Описание:** Активность пользователей бота.

**Метрики:**
- **Active users** — количество уникальных пользователей за период
- **Queries per user** — среднее количество запросов на пользователя
- **Session duration** — средняя длительность сессии

## Рекомендации по мониторингу

1. **Логирование:** Все метрики должны логироваться в файл `logs/metrics.log`
2. **Алерты:** Настроить алерты при превышении пороговых значений
3. **Дашборд:** Создать простой дашборд для визуализации метрик (опционально)
4. **Периодичность:** Собирать метрики в реальном времени, агрегировать ежедневно

## Пример структуры логов метрик

```
2025-11-26 12:00:00 - METRICS - INFO - retrieval_latency=85ms, embedding_latency=150ms, llm_latency=2500ms, total_latency=2735ms
2025-11-26 12:00:01 - METRICS - INFO - index_size=245MB, num_chunks=45230, num_books=48
2025-11-26 12:00:02 - METRICS - INFO - embedding_cost=0.00001, total_cost=1.85
```






