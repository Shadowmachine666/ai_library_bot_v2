"""Сервис поиска релевантных чанков для ai_library_bot.

Использует FAISS для векторного поиска релевантных фрагментов текста
на основе эмбеддинга запроса пользователя.
"""

import time
from typing import Any

from src.config import Config
from src.utils import setup_logger

logger = setup_logger(__name__)

# Константа для обозначения отсутствия результатов
NOT_FOUND = "NOT_FOUND"


async def get_retriever() -> Any:
    """Инициализирует и возвращает retriever (FAISS индекс).

    Загружает FAISS индекс из файла.

    Returns:
        FAISS индекс и метаданные.

    Raises:
        FileNotFoundError: Если индекс не найден.
    """
    import faiss
    import pickle

    index_path = Config.FAISS_PATH
    metadata_path = index_path.with_suffix(".metadata.pkl")

    if not index_path.exists():
        error_msg = (
            f"FAISS индекс не найден: {index_path}. "
            f"Сначала запустите команду 'python -m src.main ingest' для создания индекса."
        )
        logger.error(f"[RETRIEVER] ❌ {error_msg}")
        raise FileNotFoundError(error_msg)

    logger.info(f"Загрузка FAISS индекса из {index_path}")
    index = faiss.read_index(str(index_path))
    
    # Загружаем метаданные
    metadata = []
    if metadata_path.exists():
        with open(metadata_path, "rb") as f:
            metadata = pickle.load(f)
        logger.info(f"Загружено {len(metadata)} метаданных")
        
        # Проверяем метаданные из book2.txt на наличие проблем с кодировкой (отладочная проверка)
        book2_metadata = [m for m in metadata if m.get("source") == "book2.txt"]
        logger.debug(f"Метаданных из book2.txt: {len(book2_metadata)}")
        
        for i, meta in enumerate(book2_metadata[:3]):  # Проверяем первые 3 чанка из book2.txt
            chunk_text = meta.get("chunk_text", "")
            chunk_idx = meta.get("chunk_index", i)
            if chunk_text:
                # Показываем первые 100 символов
                preview = chunk_text[:100]
                logger.debug(f"[ПРОВЕРКА] Чанк {chunk_idx} из book2.txt, первые 100 символов: {preview}")
                
                # Проверяем на кракозябры
                unreadable = sum(1 for c in preview if ord(c) > 127 and not c.isprintable() and c not in "\n\r\t" and c not in "абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ")
                if unreadable > len(preview) * 0.1:
                    logger.warning(f"[ПРОВЕРКА] ⚠️ Чанк {chunk_idx} из book2.txt содержит кракозябры: {unreadable} нечитаемых символов из {len(preview)}")
                else:
                    logger.debug(f"[ПРОВЕРКА] ✅ Чанк {chunk_idx} из book2.txt выглядит нормально")
    
    logger.info(f"Индекс загружен: {index.ntotal} векторов, размерность {index.d}")
    
    return {"index": index, "metadata": metadata}


async def _create_query_embedding(query: str) -> list[float]:
    """Создаёт эмбеддинг для запроса пользователя.

    Args:
        query: Текст запроса пользователя.

    Returns:
        Эмбеддинг запроса (список float).

    Raises:
        ValueError: Если не удалось создать эмбеддинг.
    """
    if not Config.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY не установлен")

    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=Config.OPENAI_API_KEY)
    
    logger.info(f"[RETRIEVER] Создание эмбеддинга для запроса через OpenAI API")
    logger.debug(f"[RETRIEVER] Запрос: {query[:100]}...")
    logger.info(f"[RETRIEVER] Модель эмбеддингов: {Config.EMBEDDING_MODEL}")
    
    try:
        response = await client.embeddings.create(
            model=Config.EMBEDDING_MODEL,
            input=query
        )
        embedding = response.data[0].embedding
        logger.info(f"[RETRIEVER] ✅ Эмбеддинг создан, размерность: {len(embedding)}")
        logger.debug(f"[RETRIEVER] Первые 5 значений эмбеддинга: {embedding[:5]}")
        return embedding
    except Exception as e:
        error_type = type(e).__name__
        query_preview = query[:100] + "..." if len(query) > 100 else query
        logger.error(
            f"[RETRIEVER] ❌ Ошибка при создании эмбеддинга запроса: "
            f"тип={error_type}, сообщение={str(e)}, "
            f"запрос='{query_preview}', "
            f"модель={Config.EMBEDDING_MODEL}"
        )
        raise ValueError(
            f"Не удалось создать эмбеддинг для запроса '{query_preview}': {error_type}: {e}"
        ) from e


async def _search_in_faiss(
    retriever: Any, query_embedding: list[float], top_k: int, query: str = ""
) -> list[tuple[Any, float]]:
    """Выполняет поиск в FAISS индексе.

    Args:
        retriever: Retriever объект с FAISS индексом и метаданными.
        query_embedding: Эмбеддинг запроса.
        top_k: Количество результатов для возврата.
        query: Текст запроса (не используется, оставлен для совместимости).

    Returns:
        Список кортежей (chunk_data, score), отсортированный по релевантности.
    """
    import numpy as np

    index = retriever["index"]
    metadata = retriever["metadata"]

    logger.info(f"[RETRIEVER] Поиск в FAISS индексе: top_k={top_k}, векторов в индексе: {index.ntotal}")

    # Преобразуем эмбеддинг запроса в numpy array
    query_vector = np.array([query_embedding], dtype=np.float32)
    logger.debug(f"[RETRIEVER] Query vector shape: {query_vector.shape}, dtype: {query_vector.dtype}")

    # Выполняем поиск (ограничиваем top_k количеством векторов в индексе)
    actual_top_k = min(top_k, index.ntotal)
    logger.info(f"[RETRIEVER] Выполнение поиска в FAISS индексе (actual_top_k={actual_top_k}, векторов в индексе={index.ntotal})...")
    
    # Для диагностики: ищем больше результатов, чтобы увидеть, есть ли чанки из других источников
    search_k = min(actual_top_k * 2, index.ntotal)  # Ищем в 2 раза больше для диагностики
    distances, indices = index.search(query_vector, search_k)
    logger.info(f"[RETRIEVER] Поиск выполнен, найдено {len(indices[0])} результатов (искали {search_k})")
    
    # Логируем распределение по источникам в расширенном поиске
    extended_sources = {}
    for idx in indices[0]:
        if idx >= 0 and idx < len(metadata):
            source = metadata[idx].get("source", "unknown")
            extended_sources[source] = extended_sources.get(source, 0) + 1
    logger.info(f"[RETRIEVER] Распределение по источникам в расширенном поиске (топ-{search_k}): {extended_sources}")

    # Берём только actual_top_k результатов для дальнейшей обработки
    results = []
    for i, (dist, idx) in enumerate(zip(distances[0][:actual_top_k], indices[0][:actual_top_k])):
        # Преобразуем расстояние в score (чем меньше расстояние, тем выше score)
        # Используем формулу: score = 1 / (1 + distance)
        distance = float(dist)
        score = 1.0 / (1.0 + distance)
        
        # Получаем метаданные чанка
        if idx < len(metadata) and idx >= 0:
            chunk_meta = metadata[idx]
            # Получаем полный текст чанка из метаданных
            chunk_text = chunk_meta.get("chunk_text", "")
            
            # Проверяем и исправляем кодировку, если текст содержит кракозябры
            if chunk_text and isinstance(chunk_text, str):
                # Проверяем первые 100 символов на наличие кракозябр
                preview = chunk_text[:100]
                # Если больше 30% символов - нечитаемые (не буквы, не цифры, не пунктуация, не пробелы, не кириллица)
                unreadable = sum(1 for c in preview if ord(c) > 127 and not c.isprintable() and c not in "\n\r\t" and c not in "абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ")
                if unreadable > len(preview) * 0.3:
                    logger.warning(f"Обнаружены кракозябры в чанке {idx}, пытаемся исправить кодировку...")
                    # Пробуем исправить: интерпретируем как latin-1 и декодируем как cp1251
                    try:
                        # Если текст был неправильно сохранён, пробуем перекодировать
                        chunk_text = chunk_text.encode("latin-1", errors="ignore").decode("cp1251", errors="replace")
                        logger.info(f"Кодировка чанка {idx} исправлена")
                    except (UnicodeEncodeError, UnicodeDecodeError):
                        logger.warning(f"Не удалось исправить кодировку чанка {idx}")
                        pass
            # Получаем source из метаданных (может быть в title или file_path)
            source = chunk_meta.get("source", "unknown")
            if source == "unknown":
                # Пробуем получить из title или file_path
                title = chunk_meta.get("title", "")
                file_path = chunk_meta.get("file_path", "")
                if title:
                    source = title
                elif file_path:
                    from pathlib import Path
                    source = Path(file_path).name
                else:
                    source = "unknown"
            
            chunk_data = {
                "text": chunk_text,
                "source": source,
                "chunk_index": idx,  # Всегда используем глобальный индекс из FAISS (idx), а не из метаданных
            }
            logger.debug(f"[RETRIEVER] Чанк {i+1} (idx={idx}): source={chunk_data['source']}, text_length={len(chunk_text)}")
            logger.debug(f"[RETRIEVER] Метаданные чанка {idx}: {list(chunk_meta.keys())}")
        else:
            # Fallback, если метаданные отсутствуют или idx < 0 (невалидный индекс от FAISS)
            if idx < 0:
                logger.warning(f"[RETRIEVER] ⚠️ Невалидный индекс от FAISS: {idx} (возможно, в индексе меньше векторов, чем запрошено)")
                continue  # Пропускаем невалидные индексы
            chunk_data = {
                "text": f"Чанк {idx}",
                "source": "unknown",
                "chunk_index": idx,
            }
            logger.warning(f"[RETRIEVER] ⚠️ Метаданные для индекса {idx} не найдены (всего метаданных: {len(metadata)})")
        
        results.append((chunk_data, score))
        logger.info(
            f"[RETRIEVER] Результат {i+1}: idx={idx}, distance={distance:.4f}, "
            f"score={score:.4f}, source={chunk_data.get('source', 'unknown')}, "
            f"text_preview={chunk_data.get('text', '')[:80]}..."
        )

    return results


def _filter_by_score(results: list[tuple[Any, float]], threshold: float) -> list[tuple[Any, float]]:
    """Фильтрует результаты по порогу релевантности.

    Args:
        results: Список кортежей (chunk_data, score).
        threshold: Минимальный score для включения результата.

    Returns:
        Отфильтрованный список результатов.
    """
    filtered = [(chunk, score) for chunk, score in results if score >= threshold]
    logger.debug(
        f"Фильтрация результатов: {len(results)} → {len(filtered)} " f"(threshold={threshold})"
    )
    return filtered


def _apply_smart_filtering(results: list[tuple[Any, float]]) -> list[tuple[Any, float]]:
    """Применяет умную фильтрацию для оптимизации количества чанков.

    Если топ-N чанков имеют высокий score (> порога), использует только их.
    Иначе использует все результаты.

    Args:
        results: Список кортежей (chunk_data, score), отсортированный по убыванию score.

    Returns:
        Отфильтрованный список результатов.
    """
    if not Config.SMART_FILTERING_ENABLED:
        return results
    
    if len(results) == 0:
        return results
    
    # Проверяем топ-N чанков
    top_n = min(Config.SMART_FILTERING_TOP_N, len(results))
    top_chunks = results[:top_n]
    
    # Проверяем, все ли топ-N чанков имеют score выше порога
    all_high_score = all(
        score >= Config.SMART_FILTERING_SCORE_THRESHOLD 
        for _, score in top_chunks
    )
    
    if all_high_score:
        # Используем только топ-N чанков
        logger.info(
            f"[RETRIEVER] 🎯 Умная фильтрация: топ-{top_n} чанков имеют score >= {Config.SMART_FILTERING_SCORE_THRESHOLD}, "
            f"используем только их (экономия: {len(results) - top_n} чанков)"
        )
        return top_chunks
    else:
        # Используем все результаты
        logger.info(
            f"[RETRIEVER] 📊 Умная фильтрация: не все топ-{top_n} чанков имеют высокий score, "
            f"используем все {len(results)} результатов"
        )
        return results


async def retrieve_chunks(query: str, filter_categories: list[str] | None = None) -> list[dict[str, Any]] | str:
    """Ищет релевантные чанки для запроса пользователя.

    Процесс:
    1. Создаёт эмбеддинг запроса
    2. Ищет в FAISS индексе top-k результатов
    3. Фильтрует по категориям (если указаны)
    4. Фильтрует по порогу релевантности (score >= 0.7)
    5. Возвращает релевантные чанки или NOT_FOUND

    Args:
        query: Текст запроса пользователя.
        filter_categories: Список категорий для фильтрации результатов.
                          Если None, фильтрация по категориям не применяется.

    Returns:
        Список словарей с релевантными чанками или строка NOT_FOUND,
        если релевантных результатов нет.

        Формат чанка:
        {
            "text": "текст чанка",
            "source": "название_книги.txt",
            "chunk_index": 0,
            "score": 0.85
        }
    """
    if not query or not query.strip():
        logger.warning("[RETRIEVER] Пустой запрос")
        return NOT_FOUND

    retrieval_start_time = time.perf_counter()
    logger.info(f"[RETRIEVER] ===== Начало поиска релевантных чанков =====")
    logger.info(f"[RETRIEVER] Запрос: {query}")

    # Инициализация retriever
    init_start_time = time.perf_counter()
    logger.info(f"[RETRIEVER] Этап 1/3: Инициализация retriever (загрузка FAISS индекса)")
    retriever = await get_retriever()
    init_time = time.perf_counter() - init_start_time
    logger.debug(f"[RETRIEVER] Инициализация завершена за {init_time:.3f}с")

    # Создание эмбеддинга запроса
    embedding_start_time = time.perf_counter()
    logger.info(f"[RETRIEVER] Этап 2/3: Создание эмбеддинга запроса через OpenAI API")
    query_embedding = await _create_query_embedding(query)
    embedding_time = time.perf_counter() - embedding_start_time
    logger.debug(f"[RETRIEVER] Создание эмбеддинга завершено за {embedding_time:.3f}с")

    # Поиск в FAISS
    search_start_time = time.perf_counter()
    logger.info(f"[RETRIEVER] Этап 3/3: Поиск в FAISS индексе (top_k={Config.TOP_K})")
    results = await _search_in_faiss(retriever, query_embedding, top_k=Config.TOP_K)
    search_time = time.perf_counter() - search_start_time
    logger.debug(f"[RETRIEVER] Поиск в FAISS завершён за {search_time:.3f}с")

    # Фильтрация по категориям (если указаны)
    if filter_categories:
        logger.info(f"[RETRIEVER] Фильтрация по категориям: {filter_categories}")
        metadata = retriever["metadata"]
        filtered_by_category = []
        
        # Нормализуем категории фильтра для сравнения
        filter_categories_lower = [cat.lower() for cat in filter_categories]
        logger.debug(
            f"[RETRIEVER] Нормализованные категории фильтра: {filter_categories_lower}"
        )
        
        for chunk_data, score in results:
            # Получаем индекс чанка
            chunk_idx = chunk_data.get("chunk_index", -1)
            source = chunk_data.get("source", "unknown")
            
            logger.debug(
                f"[RETRIEVER] [CATEGORY_FILTER] Обработка чанка {chunk_idx} "
                f"(source={source}, score={score:.4f})"
            )
            
            if chunk_idx >= 0 and chunk_idx < len(metadata):
                chunk_meta = metadata[chunk_idx]
                
                # Логируем все ключи метаданных для отладки
                logger.debug(
                    f"[RETRIEVER] [CATEGORY_FILTER] Метаданные чанка {chunk_idx}: "
                    f"ключи={list(chunk_meta.keys())}"
                )
                
                # Получаем категории из метаданных
                chunk_topics = chunk_meta.get("topics", [])
                
                logger.info(
                    f"[RETRIEVER] [CATEGORY_FILTER] Чанк {chunk_idx} ({source}): "
                    f"категории в метаданных={chunk_topics} (тип: {type(chunk_topics)})"
                )
                
                # Проверяем, есть ли пересечение категорий
                if chunk_topics:
                    # Нормализуем категории чанка
                    chunk_topics_lower = [
                        topic.lower() if isinstance(topic, str) else str(topic).lower()
                        for topic in chunk_topics
                    ]
                    logger.debug(
                        f"[RETRIEVER] [CATEGORY_FILTER] Нормализованные категории чанка: "
                        f"{chunk_topics_lower}"
                    )
                    
                    # Проверяем пересечение
                    has_match = any(
                        topic_lower in filter_categories_lower
                        for topic_lower in chunk_topics_lower
                    )
                    
                    logger.info(
                        f"[RETRIEVER] [CATEGORY_FILTER] Чанк {chunk_idx}: "
                        f"пересечение найдено={has_match} "
                        f"(категории чанка: {chunk_topics_lower}, "
                        f"категории фильтра: {filter_categories_lower})"
                    )
                    
                    if has_match:
                        filtered_by_category.append((chunk_data, score))
                        logger.debug(
                            f"[RETRIEVER] [CATEGORY_FILTER] ✅ Чанк {chunk_idx} "
                            f"прошел фильтрацию"
                        )
                    else:
                        logger.info(
                            f"[RETRIEVER] [CATEGORY_FILTER] ❌ Чанк {chunk_idx} отфильтрован: "
                            f"нет пересечения категорий "
                            f"(категории чанка: {chunk_topics}, фильтр: {filter_categories})"
                        )
                else:
                    logger.warning(
                        f"[RETRIEVER] [CATEGORY_FILTER] ⚠️ Чанк {chunk_idx} не имеет категорий "
                        f"в метаданных (chunk_topics={chunk_topics}, тип: {type(chunk_topics)}). "
                        f"Пропускаем при фильтрации."
                    )
            else:
                # Если нет метаданных, пропускаем чанк (или оставляем, в зависимости от политики)
                logger.warning(
                    f"[RETRIEVER] [CATEGORY_FILTER] ⚠️ Не удалось получить метаданные для чанка "
                    f"{chunk_idx} (всего метаданных: {len(metadata)}, "
                    f"chunk_idx={chunk_idx}, source={source}). "
                    f"Пропускаем при фильтрации по категориям."
                )
        
        logger.info(
            f"[RETRIEVER] [CATEGORY_FILTER] Результаты фильтрации: "
            f"было {len(results)} результатов, "
            f"осталось {len(filtered_by_category)} результатов"
        )
        
        if filtered_by_category:
            results = filtered_by_category
            logger.info(
                f"[RETRIEVER] ✅ После фильтрации по категориям: {len(results)} результатов"
            )
        else:
            logger.warning(
                f"[RETRIEVER] ⚠️ Все результаты отфильтрованы по категориям. "
                f"Продолжаем без фильтрации по категориям. "
                f"(Было {len(results)} результатов до фильтрации)"
            )
    else:
        logger.debug("[RETRIEVER] Фильтрация по категориям не применяется")

    # Умная фильтрация (если включена)
    if Config.SMART_FILTERING_ENABLED:
        results = _apply_smart_filtering(results)
        logger.info(f"[RETRIEVER] После умной фильтрации: {len(results)} результатов")

    # Фильтрация по порогу релевантности
    logger.info(f"[RETRIEVER] Найдено {len(results)} результатов до фильтрации")
    logger.info(f"[RETRIEVER] Порог релевантности (SCORE_THRESHOLD): {Config.SCORE_THRESHOLD}")
    
    # Подсчитываем источники
    sources_count = {}
    for chunk_data, score in results:
        source = chunk_data.get('source', 'unknown')
        sources_count[source] = sources_count.get(source, 0) + 1
    logger.info(f"[RETRIEVER] Распределение по источникам: {sources_count}")
    
    # Логируем все найденные результаты с их score
    for i, (chunk_data, score) in enumerate(results):
        logger.info(
            f"[RETRIEVER] Результат {i+1}: score={score:.4f}, "
            f"source={chunk_data.get('source', 'unknown')}, "
            f"text_preview={chunk_data.get('text', '')[:100]}..."
        )
    
    filtered_results = _filter_by_score(results, Config.SCORE_THRESHOLD)
    logger.info(f"[RETRIEVER] После фильтрации осталось {len(filtered_results)} результатов")
    
    # Подсчитываем источники после фильтрации
    filtered_sources_count = {}
    for chunk_data, score in filtered_results:
        source = chunk_data.get('source', 'unknown')
        filtered_sources_count[source] = filtered_sources_count.get(source, 0) + 1
    logger.info(f"[RETRIEVER] Распределение по источникам после фильтрации: {filtered_sources_count}")

    # Если нет релевантных результатов, но есть результаты - берём лучшие
    if not filtered_results and results:
        logger.warning(
            f"[RETRIEVER] ⚠️ Все результаты отфильтрованы (score threshold={Config.SCORE_THRESHOLD}). "
            f"Берём топ-{min(3, len(results))} результатов с наилучшими score."
        )
        # Берём топ-3 с наилучшими score, даже если они ниже threshold
        filtered_results = sorted(results, key=lambda x: x[1], reverse=True)[:3]
        logger.info(f"[RETRIEVER] Используем {len(filtered_results)} результатов с наилучшими score:")
        for i, (chunk_data, score) in enumerate(filtered_results):
            logger.info(f"[RETRIEVER]   - Результат {i+1}: score={score:.4f}, source={chunk_data.get('source', 'unknown')}")
    
    # Если всё равно нет результатов
    if not filtered_results:
        logger.warning(
            f"[RETRIEVER] ❌ Не найдено релевантных чанков для запроса "
            f"(score threshold={Config.SCORE_THRESHOLD}, всего результатов: {len(results)})"
        )
        logger.info(f"[RETRIEVER] ===== Поиск завершён: NOT_FOUND =====")
        return NOT_FOUND

    # Формирование результата
    chunks = []
    for chunk_data, score in filtered_results:
        chunk = {
            "text": chunk_data.get("text", ""),
            "source": chunk_data.get("source", "unknown"),
            "chunk_index": chunk_data.get("chunk_index", 0),
            "score": round(score, 3),
        }
        chunks.append(chunk)
        logger.debug(f"[RETRIEVER] Добавлен чанк: source={chunk['source']}, score={chunk['score']}, text_length={len(chunk['text'])}")

    logger.info(f"[RETRIEVER] ✅ Найдено {len(chunks)} релевантных чанков")
    logger.info(f"[RETRIEVER] ===== Поиск завершён успешно =====")
    return chunks

