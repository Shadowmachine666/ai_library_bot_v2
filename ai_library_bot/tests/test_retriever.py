"""Тесты для retriever_service.py."""

from unittest.mock import patch

import pytest

from src.config import Config
from src.retriever_service import (
    NOT_FOUND,
    _create_query_embedding,
    _filter_by_score,
    _search_in_faiss,
    get_retriever,
    retrieve_chunks,
)


@pytest.mark.asyncio
async def test_get_retriever():
    """Тест: инициализация retriever."""
    retriever = await get_retriever()

    # Проверяем, что retriever возвращается (mock объект)
    assert retriever is not None
    assert "type" in retriever
    assert retriever["type"] == "mock_retriever"


@pytest.mark.asyncio
async def test_create_query_embedding():
    """Тест: создание эмбеддинга запроса."""
    query = "Что такое Python?"
    embedding = await _create_query_embedding(query)

    # Проверяем, что эмбеддинг создан
    assert embedding is not None
    assert isinstance(embedding, list)
    assert len(embedding) == 1536  # Размерность для text-embedding-3-small
    assert all(isinstance(x, float) for x in embedding)


@pytest.mark.asyncio
async def test_search_in_faiss():
    """Тест: поиск в FAISS индексе."""
    mock_retriever = {"type": "mock_retriever"}
    query_embedding = [0.0] * 1536
    top_k = 5

    results = await _search_in_faiss(mock_retriever, query_embedding, top_k, query="test query")

    # Проверяем результаты
    assert len(results) == top_k
    assert all(isinstance(result, tuple) and len(result) == 2 for result in results)
    assert all(isinstance(score, float) for _, score in results)


def test_filter_by_score():
    """Тест: фильтрация результатов по score."""
    results = [
        ({"text": "chunk1"}, 0.9),
        ({"text": "chunk2"}, 0.75),
        ({"text": "chunk3"}, 0.65),  # Ниже threshold
        ({"text": "chunk4"}, 0.8),
    ]

    threshold = Config.SCORE_THRESHOLD  # 0.7
    filtered = _filter_by_score(results, threshold)

    # Должны остаться только чанки с score >= 0.7
    assert len(filtered) == 3
    assert all(score >= threshold for _, score in filtered)
    assert filtered[0][1] == 0.9  # Первый результат
    assert filtered[1][1] == 0.75
    assert filtered[2][1] == 0.8


@pytest.mark.asyncio
async def test_retrieve_chunks_success():
    """Тест: успешный поиск релевантных чанков."""
    query = "Что такое машинное обучение?"

    # Мокаем функции, чтобы вернуть релевантные результаты
    with patch("src.retriever_service._search_in_faiss") as mock_search:
        # Настраиваем mock для возврата результатов с высоким score
        mock_search.return_value = [
            ({"text": "chunk1", "source": "book1.txt", "chunk_index": 0}, 0.85),
            ({"text": "chunk2", "source": "book1.txt", "chunk_index": 1}, 0.80),
            ({"text": "chunk3", "source": "book2.txt", "chunk_index": 0}, 0.75),
        ]

        result = await retrieve_chunks(query)

        # Проверяем результат
        assert result != NOT_FOUND
        assert isinstance(result, list)
        assert len(result) == 3

        # Проверяем структуру чанков
        for chunk in result:
            assert "text" in chunk
            assert "source" in chunk
            assert "chunk_index" in chunk
            assert "score" in chunk
            assert chunk["score"] >= Config.SCORE_THRESHOLD


@pytest.mark.asyncio
async def test_retrieve_chunks_not_found():
    """Тест: отсутствие релевантных результатов."""
    query = "Очень специфичный запрос"

    # Мокаем функции, чтобы вернуть результаты с низким score
    with patch("src.retriever_service._search_in_faiss") as mock_search:
        # Настраиваем mock для возврата результатов с низким score
        mock_search.return_value = [
            ({"text": "chunk1", "source": "book1.txt", "chunk_index": 0}, 0.5),
            ({"text": "chunk2", "source": "book1.txt", "chunk_index": 1}, 0.6),
        ]

        result = await retrieve_chunks(query)

        # Должен вернуться NOT_FOUND
        assert result == NOT_FOUND


@pytest.mark.asyncio
async def test_retrieve_chunks_empty_query():
    """Тест: пустой запрос."""
    result = await retrieve_chunks("")
    assert result == NOT_FOUND

    result = await retrieve_chunks("   ")
    assert result == NOT_FOUND


@pytest.mark.asyncio
async def test_retrieve_chunks_all_filtered():
    """Тест: все результаты отфильтрованы."""
    query = "Запрос"

    # Мокаем функции, чтобы вернуть пустой список после фильтрации
    with patch("src.retriever_service._search_in_faiss") as mock_search:
        mock_search.return_value = []  # Пустые результаты

        result = await retrieve_chunks(query)
        assert result == NOT_FOUND


def test_not_found_constant():
    """Тест: константа NOT_FOUND определена."""
    assert NOT_FOUND == "NOT_FOUND"
    assert isinstance(NOT_FOUND, str)
