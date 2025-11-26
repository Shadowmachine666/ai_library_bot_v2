"""Тесты для analyzer.py."""

import json
from unittest.mock import patch

import pytest

from src.analyzer import (
    AnalysisResponse,
    Quote,
    Result,
    _build_prompt,
    _call_llm,
    _load_system_prompt,
    _parse_llm_response,
    analyze,
)


def test_load_system_prompt():
    """Тест: загрузка системного промпта."""
    prompt = _load_system_prompt()

    assert prompt is not None
    assert len(prompt) > 0
    assert "AI-библиотекарь" in prompt
    assert "JSON" in prompt


def test_build_prompt():
    """Тест: сборка промпта из чанков."""
    chunks = [
        {"text": "Фрагмент текста 1", "source": "book1.txt", "chunk_index": 0},
        {"text": "Фрагмент текста 2", "source": "book2.txt", "chunk_index": 1},
    ]
    user_query = "Что такое Python?"

    prompt = _build_prompt(chunks, user_query)

    assert user_query in prompt
    assert "Фрагмент текста 1" in prompt
    assert "Фрагмент текста 2" in prompt
    assert "book1.txt" in prompt
    assert "book2.txt" in prompt


@pytest.mark.asyncio
async def test_call_llm():
    """Тест: вызов LLM (mock)."""
    prompt = "Тестовый промпт"
    response = await _call_llm(prompt, max_retries=1)

    assert response is not None
    assert isinstance(response, str)

    # Проверяем, что это валидный JSON
    data = json.loads(response)
    assert "status" in data


@pytest.mark.asyncio
async def test_parse_llm_response_valid():
    """Тест: парсинг валидного ответа LLM."""
    valid_json = {
        "status": "SUCCESS",
        "clarification_question": None,
        "result": {
            "answer": "Ответ на вопрос",
            "quotes": [{"text": "Цитата", "source": "Книга 1"}],
            "disclaimer": "Это анализ на основе загруженных текстов.",
        },
    }

    response = await _parse_llm_response(json.dumps(valid_json, ensure_ascii=False))

    assert isinstance(response, AnalysisResponse)
    assert response.status == "SUCCESS"
    assert response.result is not None
    assert response.result.answer == "Ответ на вопрос"
    assert len(response.result.quotes) == 1


@pytest.mark.asyncio
async def test_parse_llm_response_invalid_json():
    """Тест: парсинг невалидного JSON."""
    invalid_json = "Это не JSON"

    with pytest.raises(ValueError, match="Невалидный JSON"):
        await _parse_llm_response(invalid_json)


@pytest.mark.asyncio
async def test_parse_llm_response_invalid_schema():
    """Тест: парсинг JSON с невалидной схемой."""
    invalid_schema = {"invalid": "data"}

    with pytest.raises(ValueError, match="не соответствует схеме"):
        await _parse_llm_response(json.dumps(invalid_schema))


@pytest.mark.asyncio
async def test_analyze_success():
    """Тест: успешный анализ."""
    chunks = [
        {"text": "Python - это язык программирования", "source": "book1.txt", "chunk_index": 0}
    ]
    user_query = "Что такое Python?"

    response = await analyze(chunks, user_query)

    assert isinstance(response, AnalysisResponse)
    assert response.status in ["SUCCESS", "NOT_FOUND", "CLARIFICATION_NEEDED", "CONFLICT"]


@pytest.mark.asyncio
async def test_analyze_empty_chunks():
    """Тест: анализ с пустым списком чанков."""
    chunks = []
    user_query = "Вопрос"

    response = await analyze(chunks, user_query)

    assert isinstance(response, AnalysisResponse)
    assert response.status == "NOT_FOUND"
    assert response.result is None


@pytest.mark.asyncio
async def test_analyze_retry_on_invalid_json():
    """Тест: retry при невалидном JSON."""
    chunks = [{"text": "Текст", "source": "book.txt", "chunk_index": 0}]
    user_query = "Вопрос"

    # Мокаем _call_llm, чтобы сначала вернуть невалидный JSON, затем валидный
    call_count = 0

    async def mock_call_llm(prompt: str, max_retries: int = None) -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Первая попытка - невалидный JSON
            return "Это не JSON"
        else:
            # Вторая попытка - валидный JSON
            return json.dumps(
                {
                    "status": "SUCCESS",
                    "clarification_question": None,
                    "result": {
                        "answer": "Ответ",
                        "quotes": [],
                        "disclaimer": "Это анализ на основе загруженных текстов.",
                    },
                },
                ensure_ascii=False,
            )

    with patch("src.analyzer._call_llm", side_effect=mock_call_llm):
        response = await analyze(chunks, user_query)

        # Должна быть сделана повторная попытка
        assert call_count >= 2
        assert isinstance(response, AnalysisResponse)
        assert response.status == "SUCCESS"


def test_analysis_response_model():
    """Тест: валидация модели AnalysisResponse."""
    # Валидный ответ
    valid_response = AnalysisResponse(
        status="SUCCESS",
        clarification_question=None,
        result=Result(
            answer="Ответ",
            quotes=[Quote(text="Цитата", source="Книга")],
            disclaimer="Дисклеймер",
        ),
    )

    assert valid_response.status == "SUCCESS"
    assert valid_response.result is not None

    # Невалидный статус
    with pytest.raises(ValueError, match="Статус должен быть"):
        AnalysisResponse(status="INVALID_STATUS")


def test_quote_model():
    """Тест: валидация модели Quote."""
    quote = Quote(text="Текст цитаты", source="Название книги")
    assert quote.text == "Текст цитаты"
    assert quote.source == "Название книги"


def test_result_model():
    """Тест: валидация модели Result."""
    result = Result(
        answer="Ответ",
        quotes=[Quote(text="Цитата", source="Книга")],
    )
    assert result.answer == "Ответ"
    assert len(result.quotes) == 1
    assert result.disclaimer == "Это анализ на основе загруженных текстов."
